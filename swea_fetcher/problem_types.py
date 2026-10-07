"""풀이 유형 분류 체계 · 학습 경로 · 유형 캐시 (M24.1). Qt·네트워크·AI 를 모른다 (캐시 파일 입출력만).

오늘의 추천이 "난이도만 같은" 문제를 가져오면 안 된다 — 내가 완전탐색만 풀어 봤는데 같은 D3 라고 BFS 를 주면 잘못된 추천이다.
그래서 문제마다 **풀이 유형**(알고리즘)을 붙이고, 내가 풀어 본 유형 안에서만 일반 칸을 고르고, 아직 안 풀어 본 유형은
학습 경로상 "다음 유형" 1문제만 한 단계 쉬운 난이도로 소개한다 (recommend.build_set).

- 이 분류는 growth_tags(약점 분류)와 **별개**다 (growth_tags 는 DFS/BFS 를 한 덩어리로 묶고 오답 원인도 섞여 있다).
- 유형 id 는 append-only: 캐시가 id 만 저장한다. 표시 이름·정의는 바꿔도 되고, 의미가 바뀌면 TAXONOMY_VERSION 을 올려 캐시를 무효화한다.
- 유형은 문제당 1~2개, 첫 번째가 주 유형. AI 가 문제를 직접 풀어 보는 짧은 풀이 설계(plan)를 쓰고, 그 설계가 쓰는 기법으로 정한다
  (service.classify_types / classify_background, M24.2). 설계(plan)는 스포일러라 저장하지 않고, 이유 한 줄(why)만 칩 툴팁용으로 저장한다. 제목 키워드는 보조/폴백이다.
- 폴더 이름(BFS, DFS1 …)은 "그 유형을 안다" 는 증거가 아니다. 앱에 기록된 Pass 문제의 유형만 증거다 (count_known).
- 캐시는 공개 데이터라 `cache/problem_types.json` (루트·GitHub 밖). `logout --all` 이 카탈로그와 함께 지운다.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Collection, Iterable, Mapping, Sequence

from .config import Settings

log = logging.getLogger("swea_fetcher.problem_types")

TAXONOMY_VERSION = 3  # 3: 풀이 설계 기반 분류(M24.2) + recursion 유형 추가. 2: 제약 조건(N 범위) 기준 추가 — 이전 결과는 다시 분류
CACHE_FILE = "problem_types.json"
_FILE_VERSION = 1
MAX_TYPES = 2  # 문제당 유형 수 상한 (첫 번째가 주 유형)
NEG_RETRY_DAYS = 14  # AI 가 유형을 정하지 못한 문제는 이 기간 뒤에 한 번 더 시도한다


@dataclass(frozen=True)
class PType:
    id: str
    name: str  # 표시 이름
    definition: str  # 프롬프트에 그대로 들어가는 한 줄 정의


TYPES: tuple[PType, ...] = (
    PType("impl", "구현·시뮬레이션", "규칙·절차를 그대로 코드로 옮기는 문제 (격자·배열 시뮬레이션, 단순 조건 처리). 다른 뚜렷한 알고리즘이 없을 때"),
    PType("brute", "완전탐색", "순열·조합·부분집합·중첩 반복으로 모든 경우를 직접 열거해 확인하는 문제 (재귀 DFS 가 핵심이 아닌 단순 열거)"),
    PType("backtrack", "DFS·백트래킹", "탐색 문제: 재귀/스택 DFS 로 깊이 우선 탐색하거나, 가지치기하며 상태를 되돌리는 백트래킹"),
    PType("bfs", "BFS", "큐로 가까운 곳부터 퍼져 나가는 탐색 (최소 이동 횟수, 단계별 확산, 가중치 없는 최단 거리)"),
    PType("shortest", "최단경로", "가중치 있는 그래프의 최단 경로 (다익스트라, 벨만-포드, 플로이드-워셜, 우선순위 큐 활용)"),
    PType("graph", "그래프·유니온파인드", "정점·간선 모델링, 연결 요소, 서로소 집합(유니온 파인드), 위상 정렬, 최소 신장 트리"),
    PType("tree", "트리·힙", "트리 순회·이진 트리·트라이·세그먼트 트리, 힙(우선순위 큐) 자체가 핵심인 문제"),
    PType("stackqueue", "스택·큐", "스택·큐·덱의 성질 자체가 핵심인 문제 (괄호 검사, 후위 표기, 모노토닉 스택, 큐 시뮬레이션)"),
    PType("sort_bs", "정렬·이분탐색", "정렬 후 처리하거나 이분 탐색(매개변수 탐색 포함)으로 푸는 문제"),
    PType("greedy", "그리디", "매 순간 최선의 선택(정렬 기준 선택, 구간 스케줄링 등)이 정답이 되는 문제"),
    PType("dp", "DP", "점화식·메모이제이션으로 부분 문제의 답을 재사용하는 문제 (배낭, LIS, 격자 경로 개수 등)"),
    PType("string", "문자열", "문자열 처리·패턴 검색·회문·파싱이 핵심인 문제"),
    PType("math", "수학", "소수·약수·진법·나머지·조합론·기하 등 수식과 수학적 관찰이 핵심인 문제"),
    PType("prefix", "누적합·투포인터", "누적합, 슬라이딩 윈도우, 투 포인터로 구간을 효율적으로 다루는 문제"),
    PType("recursion", "재귀·분할정복", "재귀 함수로 문제를 작게 나눠 푸는 문제 (거듭제곱·하노이·팩토리얼·병합/퀵 정렬·분할 정복). 탐색(DFS)이 아니라 재귀 구조 자체가 핵심"),
)
TYPE_IDS = tuple(t.id for t in TYPES)
_BY_ID = {t.id: t for t in TYPES}

# 학습 경로: 이 순서로 "다음 유형" 을 소개한다 (string/math 는 아무 때나 입문 가능해 맨 뒤).
# 오늘의 추천에서 고른 문제를 저장할 주제 폴더 (주 유형 → 폴더 이름). 유형을 모르면 UNKNOWN_FOLDER
FOLDERS = {
    "impl": "implementation",
    "brute": "bruteforce",
    "backtrack": "backtracking",
    "bfs": "bfs",
    "shortest": "shortest_path",
    "graph": "graph",
    "tree": "tree",
    "stackqueue": "stack_queue",
    "sort_bs": "sort_search",
    "greedy": "greedy",
    "dp": "dp",
    "string": "string",
    "math": "math",
    "prefix": "prefix_sum",
    "recursion": "recursion",
}
UNKNOWN_FOLDER = "recommend"


def folder_for(types) -> str:
    """주 유형(첫 번째)의 저장 폴더 이름. 유형이 없거나 모르는 id 면 UNKNOWN_FOLDER."""
    for tid in types or ():
        if tid in FOLDERS:
            return FOLDERS[tid]
        break
    return UNKNOWN_FOLDER


PATH_ORDER = ("impl", "brute", "recursion", "backtrack", "stackqueue", "bfs", "sort_bs", "prefix", "greedy", "dp", "tree", "graph", "shortest", "string", "math")
# 선행 유형: 값 중 **하나라도** 알면 충족 (bfs 는 백트래킹이나 스택·큐). 없는 유형은 입문 유형.
PREREQS: dict[str, tuple[str, ...]] = {
    "recursion": ("brute", "impl"),
    "backtrack": ("recursion", "brute"),
    "bfs": ("backtrack", "stackqueue"),
    "shortest": ("bfs",),
    "graph": ("bfs",),
    "tree": ("backtrack",),
    "prefix": ("impl",),
    "greedy": ("sort_bs",),
    "dp": ("brute",),
}
ENTRY_TYPES = ("impl", "brute", "math", "string", "sort_bs", "stackqueue")  # 선행 유형이 없는 입문 유형 (아는 유형이 없을 때 일반 칸에 쓴다)


def name_of(tid: str) -> str | None:
    """표시 이름. 모르는 id 는 None (화면에 id 를 그대로 보이지 않는다)."""
    t = _BY_ID.get(tid)
    return t.name if t else None


def names_of(ids: Iterable[str]) -> list[str]:
    return [n for n in (name_of(i) for i in ids) if n]


def clean_ids(raw: object) -> tuple[str, ...]:
    """id 목록 정리: 분류에 있는 문자열 id 만, 중복 제거, 최대 MAX_TYPES 개 (이상한 값은 걸러낸다)."""
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x in _BY_ID and x not in out:
            out.append(x)
    return tuple(out[:MAX_TYPES])


# --- 학습 경로 -------------------------------------------------------------------------------------


def implied(known: Collection[str]) -> frozenset[str]:
    """아는 유형이 전제로 삼는 유형 (선행 유형이 하나뿐이면 반드시 알 것) + 가장 기본인 구현. 증거는 아니므로 "다음 유형" 계산에만 쓴다."""
    out = set(known)
    if out:
        out.add("impl")  # 뭐라도 풀었다면 구현은 했다
    changed = True
    while changed:
        changed = False
        for t in list(out):
            pre = PREREQS.get(t, ())
            if len(pre) == 1 and pre[0] not in out:
                out.add(pre[0])
                changed = True
    return frozenset(out)


def prereq_met(tid: str, known: Collection[str]) -> bool:
    pre = PREREQS.get(tid)
    return True if not pre else any(p in known for p in pre)


def next_types(known: Collection[str]) -> list[str]:
    """"새 유형" 후보 (경로 순서): 아직 모르고 선행 유형을 아는 유형. 아는 유형이 하나도 없으면 빈 목록 (증거 없이 소개하지 않는다)."""
    if not known:
        return []
    eff = implied(known)
    return [t for t in PATH_ORDER if t not in eff and prereq_met(t, eff)]


def allowed_for(known: Collection[str]) -> frozenset[str]:
    """수준 맞춤·한 단계 위 칸에 쓸 수 있는 유형: 풀어 본 유형, 하나도 없으면 입문 유형."""
    return frozenset(known) if known else frozenset(ENTRY_TYPES)


def type_ok(types: Sequence[str], allowed: Collection[str]) -> bool:
    """유형을 알고 있고 모두 허용된 유형 안인가 (모르는 문제는 False)."""
    return bool(types) and all(t in allowed for t in types)


def prereq_names(tid: str, known: Collection[str]) -> list[str]:
    """이유 문구용: tid 의 선행 유형 중 이미 아는 것의 표시 이름."""
    return names_of(p for p in PREREQS.get(tid, ()) if p in known)


def count_known(solved_nums: Iterable[int], types_of: Callable[[int], Sequence[str]]) -> Counter:
    """푼 문제(앱에 Pass 기록)의 유형별 개수. 문제 하나가 가진 유형(주·부)마다 1씩. 유형을 모르는 문제는 세지 않는다."""
    counts: Counter = Counter()
    for n in set(solved_nums):
        for t in clean_ids(types_of(n)):
            counts[t] += 1
    return counts


def known_line(counts: Mapping[str, int], limit: int = 4) -> str:
    """"풀어 본 유형: 완전탐색 5 · 구현 3" (많이 푼 순, 상위 limit 개 + 나머지 개수). 없으면 ""."""
    rows = sorted(((n, c) for t, c in counts.items() if c > 0 for n in [name_of(t)] if n), key=lambda r: (-r[1], r[0]))
    if not rows:
        return ""
    text = " · ".join(f"{n} {c}" for n, c in rows[:limit])
    if len(rows) > limit:
        text += f" 외 {len(rows) - limit}개"
    return "풀어 본 유형: " + text


# --- 제목 키워드 (AI 를 못 쓸 때의 폴백 · 지문 없이 분명한 제목만) -------------------------------------
# 보수적으로: "미로"(BFS/DFS 모호)·"최단"·"정렬"·"이진"(이진수) 같은 모호한 단어는 넣지 않는다.
_H = r"(?<![가-힣])"  # 한글 단어 중간 매치 방지 ("큐브" 의 "큐")
_HE = r"(?![가-힣])"
_KEYWORDS: tuple[tuple[str, re.Pattern], ...] = tuple(
    (tid, re.compile(rx, re.I))
    for tid, rx in (
        ("bfs", r"(?<![A-Za-z])BFS(?![A-Za-z])|너비\s*우선"),
        ("backtrack", r"(?<![A-Za-z])DFS(?![A-Za-z])|깊이\s*우선|백트래킹"),
        ("shortest", r"다익스트라|dijkstra|플로이드|벨만\s*-?\s*포드"),
        ("graph", r"위상\s*정렬|유니온|union\s*-?\s*find|서로소\s*집합|분리\s*집합|최소\s*신장"),
        ("tree", _H + r"트리" + _HE + r"|" + _H + r"힙" + _HE + r"|우선순위\s*큐"),
        ("stackqueue", r"스택|" + _H + r"큐" + _HE + r"|(?<![A-Za-z])deque(?![A-Za-z])"),
        ("brute", r"순열|부분\s*집합|" + _H + r"조합" + _HE + r"|완전\s*탐색"),
        ("sort_bs", r"이진\s*탐색|이분\s*탐색|이진탐색|이분탐색"),
        ("greedy", r"그리디|탐욕"),
        ("dp", r"(?<![A-Za-z])DP(?![A-Za-z])|동적\s*계획|다이나믹"),
        ("prefix", r"누적\s*합|투\s*포인터|슬라이딩\s*윈도우"),
        ("recursion", r"재귀|하노이|분할\s*정복"),
    )
)


def title_types(title: str) -> tuple[str, ...]:
    """제목에 분명한 키워드가 있을 때만 유형 (최대 2개). 없으면 ()."""
    text = title or ""
    found = [tid for tid, rx in _KEYWORDS if rx.search(text)]
    return tuple(found[:MAX_TYPES])


# --- 캐시 -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TypeEntry:
    t: tuple[str, ...]  # 빈 튜플 = AI 가 정하지 못함 (NEG_RETRY_DAYS 뒤 재시도)
    src: str = "ai"  # "ai" | "title"
    eng: str = ""
    at: str = ""
    why: str = ""  # "왜 이 유형?" 한 줄 (WHY_MAX 자 이내, 풀이를 알려 주지 않는 이유만). 풀이 설계(plan)는 저장하지 않는다

    def to_dict(self) -> dict:
        d = {"t": list(self.t), "src": self.src, "eng": self.eng, "at": self.at}
        if self.why:
            d["why"] = self.why
        return d


@dataclass
class TypeCache:
    entries: dict[int, TypeEntry] = field(default_factory=dict)
    day: str = ""  # 오늘 분류에 쓴 개수를 센 날짜
    used: int = 0  # day 에 분류를 시도한 문제 수 (일일 상한)
    fail_day: str = ""  # 엔진 호출이 실패한 날 (같은 날 자동 재시도 금지)
    hour: str = ""  # 시간당 상한을 세는 시각 ("YYYY-MM-DDTHH", 시계 기준 1시간 단위)
    hour_used: int = 0
    limit_day: str = ""  # AI 사용량·요청 한도 오류를 만난 날 (그날은 더 부르지 않는다)

    def used_on(self, today: date) -> int:
        return self.used if self.day == today.isoformat() else 0

    def add_used(self, today: date, n: int) -> None:
        if self.day != today.isoformat():
            self.day, self.used = today.isoformat(), 0
        self.used += n

    def used_in_hour(self, stamp: datetime) -> int:
        return self.hour_used if self.hour == hour_key(stamp) else 0

    def add_used_at(self, stamp: datetime, n: int) -> None:
        """하루·시간 사용량을 함께 올린다 (분류 한 묶음을 시도할 때마다)."""
        self.add_used(stamp.date(), n)
        key = hour_key(stamp)
        if self.hour != key:
            self.hour, self.hour_used = key, 0
        self.hour_used += n

    def budget(self, stamp: datetime, day_cap: int, hour_cap: int) -> tuple[int, str]:
        """지금 더 분류할 수 있는 문제 수와 막힌 이유 ("" | "day" | "hour"). 일일 상한이 시간 상한보다 먼저 보고된다."""
        day_left = day_cap - self.used_on(stamp.date())
        if day_left <= 0:
            return 0, "day"
        hour_left = hour_cap - self.used_in_hour(stamp)
        if hour_left <= 0:
            return 0, "hour"
        return min(day_left, hour_left), ""

    def types_of(self, num: int) -> tuple[str, ...]:
        e = self.entries.get(num)
        return e.t if e else ()

    def fresh(self, num: int, today: date) -> bool:
        """이미 시도한 문제인가 (성공했거나, 정하지 못했어도 재시도 기간 안)."""
        e = self.entries.get(num)
        if e is None:
            return False
        if e.t:
            return True
        try:
            return (today - datetime.fromisoformat(e.at).date()).days < NEG_RETRY_DAYS
        except ValueError:
            return False

    def to_dict(self) -> dict:
        return {"v": _FILE_VERSION, "tax": TAXONOMY_VERSION, "day": self.day, "used": self.used, "fail_day": self.fail_day,
                "hour": self.hour, "hour_used": self.hour_used, "limit_day": self.limit_day,
                "types": {str(n): e.to_dict() for n, e in sorted(self.entries.items())}}


def hour_key(stamp: datetime) -> str:
    return stamp.strftime("%Y-%m-%dT%H")


def cache_path(settings: Settings) -> Path:
    return settings.cache_dir / CACHE_FILE


def _inside(path: Path, base: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except (ValueError, OSError):
        return False


def _quarantine(path: Path) -> None:
    try:
        os.replace(path, path.with_suffix(path.suffix + ".corrupt"))
    except OSError:
        pass


def load(settings: Settings) -> TypeCache:
    """유형 캐시. 없거나 손상·버전 불일치면 빈 캐시 (손상 파일은 .corrupt 로 이동). 분류 체계 버전이 다르면 항목만 버린다. 예외 없음."""
    path = cache_path(settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return TypeCache()
    except (OSError, ValueError) as e:
        log.warning("풀이 유형 캐시를 읽을 수 없어 새로 시작합니다: %s", e)
        _quarantine(path)
        return TypeCache()
    if not isinstance(raw, dict) or raw.get("v") != _FILE_VERSION:
        _quarantine(path)
        return TypeCache()
    try:
        used = int(raw.get("used") or 0)
    except (TypeError, ValueError):
        used = 0
    try:
        hour_used = int(raw.get("hour_used") or 0)
    except (TypeError, ValueError):
        hour_used = 0
    cache = TypeCache(day=str(raw.get("day") or ""), used=max(0, used), fail_day=str(raw.get("fail_day") or ""),
                      hour=str(raw.get("hour") or ""), hour_used=max(0, hour_used), limit_day=str(raw.get("limit_day") or ""))
    if raw.get("tax") != TAXONOMY_VERSION or not isinstance(raw.get("types"), dict):
        return TypeCache()  # 분류 체계가 바뀌었다: 옛 결과는 쓰지 않고, 다시 분류할 수 있게 오늘 사용량도 0 부터
    for key, val in raw["types"].items():
        try:
            num = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(val, dict):
            continue
        ids = clean_ids(val.get("t"))
        if val.get("t") and not ids:
            continue  # 알 수 없는 id 만 있는 항목은 없는 것으로
        src = "title" if val.get("src") == "title" else "ai"
        cache.entries[num] = TypeEntry(ids, src, str(val.get("eng") or ""), str(val.get("at") or ""), clean_why(val.get("why")))
    return cache


def save(settings: Settings, cache: TypeCache) -> bool:
    """tmp + os.replace 원자 쓰기. 루트 폴더 안이면 거부 (공개 데이터지만 풀이 저장소·GitHub 에는 올리지 않는다). 예외 없음 (실패는 False)."""
    if _inside(settings.cache_dir, settings.root):
        log.warning("풀이 유형 캐시 위치가 루트 폴더 안이라 기록하지 않습니다: %s", settings.cache_dir)
        return False
    path = cache_path(settings)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(cache.to_dict(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        log.warning("풀이 유형 캐시 저장 실패: %s", e)
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True


def clear(config_dir: Path) -> int:
    """캐시 파일 삭제 (`logout --all`). 지운 파일 수. content_cache.clear 보다 먼저 부를 것 (빈 cache/ 폴더 정리)."""
    cache = Path(config_dir) / "cache"
    n = 0
    for suffix in ("", ".tmp", ".corrupt"):
        try:
            (cache / (CACHE_FILE + suffix)).unlink()
            n += 1
        except OSError:
            pass
    return n


def effective_types(cache: TypeCache, num: int, title: str = "") -> tuple[str, ...]:
    """푼 문제(내가 아는 유형)에 쓰는 유형: AI 결과 > 제목 키워드 > ()."""
    e = cache.entries.get(num)
    if e is not None and e.t:
        return e.t
    return title_types(title)


def ai_types(cache: TypeCache, num: int) -> tuple[str, ...]:
    """추천 후보에 쓰는 유형: AI 가 지문을 읽고 정한 결과만. 제목 키워드 추정은 쓰지 않는다
    (예: "부분 집합의 합" 은 제목만 보면 완전탐색이지만 N≤100 이라 가지치기·DP 가 필요하다). 모르면 () = 유형 미확인."""
    e = cache.entries.get(num)
    return e.t if e is not None and e.src == "ai" else ()


# --- AI 응답 검증 -----------------------------------------------------------------------------------

WHY_MAX = 40  # "왜 이 유형?" 한 줄의 글자 상한
_WHY_STRIP_RE = re.compile(r"```|~~~|`|https?://\S*|www\.\S*|\[[^\]]*\]\([^)]*\)|[\x00-\x1f\x7f]")


def clean_why(raw: object) -> str:
    """AI 가 쓴 이유 한 줄 정리: 코드 펜스·백틱·링크·제어 문자를 지우고 공백을 하나로, WHY_MAX 자로 자른다 (문자열이 아니면 "")."""
    if not isinstance(raw, str):
        return ""
    text = " ".join(_WHY_STRIP_RE.sub(" ", raw).split())
    return text[:WHY_MAX].rstrip()


def parse_batch(text: str, batch_nums: Collection[int]) -> tuple[dict[int, tuple[str, ...]], set[int], dict[int, str]] | None:
    """AI 응답 → (유효한 {번호: 유형}, 응답에 있었지만 쓸 수 없는 번호, {번호: 이유 한 줄}). 첫 `{` ~ 마지막 `}` 를 JSON 으로 읽는다 (코드 펜스·잡문 허용).

    형식 {"v":2,"types":[{"n":1217,"plan":"…","t":["recursion"],"why":"…"}]}. 검증: 요청한 번호만, id 는 분류에 있는 것만, 유형은 1~2개
    (3개 이상·0개·형식 오류는 "유형 미확인"). `plan`(풀이 설계)은 AI 가 근거를 쓰게 하는 용도라 읽지도 저장하지도 않는다 (스포일러).
    `why` 는 clean_why 로 정리해 돌려준다 (없으면 해당 번호가 빠진다). JSON 자체가 아니면 None.
    """
    if not isinstance(text, str):
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        raw = json.loads(text[start : end + 1])
    except ValueError:
        return None
    rows = raw.get("types") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return None
    allowed = set(batch_nums)
    valid: dict[int, tuple[str, ...]] = {}
    whys: dict[int, str] = {}
    bad: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        n = row.get("n")
        if isinstance(n, bool) or not isinstance(n, int) or n not in allowed or n in valid or n in bad:
            continue
        t = row.get("t")
        if not isinstance(t, list) or not 1 <= len(t) <= MAX_TYPES or len(set(map(str, t))) != len(t):
            bad.add(n)
            continue
        ids = clean_ids(t)
        if len(ids) != len(t):  # 모르는 id 가 섞였다
            bad.add(n)
            continue
        valid[n] = ids
        why = clean_why(row.get("why"))
        if why:
            whys[n] = why
    return valid, bad, whys


def stamp_entries(valid: Mapping[int, Sequence[str]], bad: Iterable[int], engine: str, now: datetime, whys: Mapping[int, str] | None = None) -> dict[int, TypeEntry]:
    at = now.isoformat(timespec="seconds")
    out = {n: TypeEntry(tuple(t), "ai", engine, at, (whys or {}).get(n, "")) for n, t in valid.items()}
    for n in bad:
        out[n] = TypeEntry((), "ai", engine, at)
    return out
