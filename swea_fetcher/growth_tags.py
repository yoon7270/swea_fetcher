"""성장 기록 분류 체계와 태그 추출 (M19). 순수 함수 (I/O·Qt 없음).

- 분류 12개는 append-only: id 는 불변 (스냅샷·이벤트가 id 만 저장), 표시 이름·정의·팁은 바꿔도 된다. 새 카테고리는 끝에 추가.
- AI 응답 맨 끝의 ```profile 블록(JSON)에서 약점·강점 태그를 읽고, 블록은 표시·캐시·다음 힌트 프롬프트 어디에도 남기지 않는다.
- `extract` 는 clean_titles / filter_hint / first_code_block 보다 먼저 호출해야 한다 (블록이 6줄을 넘어 힌트 필터에 지워지거나 정답 코드로 잡히는 것을 막는다).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

TAXONOMY_VERSION = 1
MAX_TAGS = 4  # 응답 1건당 태그 상한
MAX_BLOCK_CHARS = 2048  # 블록이 이보다 크면 손상으로 본다 (제거는 하되 태그는 버림)
KIND_ALIASES = {"weak": "weak", "weakness": "weak", "약점": "weak", "strong": "strong", "strength": "strong", "강점": "strong"}


@dataclass(frozen=True)
class Category:
    id: str
    name: str  # 표시 이름
    definition: str  # 프롬프트에 그대로 들어가는 정의
    tip: str  # 같은 약점이 반복될 때 보여주는 고정 문구


TAXONOMY: tuple[Category, ...] = (
    Category("parse", "입력 파싱", "입력 형식 해석 오류: 여러 줄/공백 구분, 테스트케이스 반복, `input()`·`split`·`map` 처리", "입력 예시를 손으로 한 번 파싱해 보고 코드를 쓰세요"),
    Category("edge", "경계·예외 조건", "최소/최대/빈 값/중복/음수 등 극단 입력 누락, 예외 케이스 처리", "제출 전에 최솟값·최댓값·빈 경우를 한 번씩 돌려 보세요"),
    Category("impl", "구현 정확성·인덱스", "오프바이원, 인덱스 범위, 초기화·갱신 순서, 변수 덮어쓰기, 시뮬레이션 절차 오류", "반복문의 시작·끝 값과 초기화 위치를 주석으로 적어 보세요"),
    Category("time", "시간 복잡도", "불필요한 중첩 반복, 반복 계산, 제한 대비 과한 연산량, 시간초과", "N 최대치로 연산 횟수를 먼저 어림해 보세요"),
    Category("space", "공간·메모리", "큰 배열/중복 저장, 불필요한 복사, 메모리 초과 위험", "큰 배열을 만들기 전에 크기를 계산해 보세요"),
    Category("search", "재귀·DFS/BFS", "재귀 종료 조건·깊이(SWEA 는 재귀 한도 변경 불가), 방문 처리, 큐/스택 탐색, 그래프·트리 순회", "종료 조건과 방문 처리를 코드보다 먼저 적어 보세요"),
    Category("brute", "완전탐색·백트래킹", "순열/조합/부분집합 열거, 가지치기, 비트마스크 열거", "열거할 경우의 수와 가지치기 조건을 먼저 정리해 보세요"),
    Category("dp", "DP·그리디·정렬", "점화식·메모이제이션, 탐욕 선택의 근거, 정렬 기반 접근", "작은 입력으로 점화식/선택 기준을 손으로 검증해 보세요"),
    Category("ds", "자료구조 선택", "list/deque/set/dict/heap 등 문제에 맞는 선택과 사용", "자주 하는 연산(검색·삽입·삭제)에 맞는 자료구조를 골라 보세요"),
    Category("math", "수학·수 처리", "진법, 나머지, 약수/소수, 좌표·기하, 정수/실수 처리", "공식은 작은 예로 먼저 확인해 보세요"),
    Category("readability", "가독성·구조", "변수/함수 이름, 함수 분리, 중복 코드, 매직 넘버, 주석", "이름을 의미 있게 바꾸고 반복되는 부분을 함수로 묶어 보세요"),
    Category("pythonic", "파이썬 관용구", "컴프리헨션, 내장함수/`collections`/`itertools`, 슬라이싱, 언패킹 활용", "반복문 대신 내장함수·컴프리헨션으로 줄일 곳을 찾아 보세요"),
)
CATEGORY_IDS = tuple(c.id for c in TAXONOMY)
_BY_ID = {c.id: c for c in TAXONOMY}


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", str(text)).lower()


_BY_KEY = {**{c.id: c.id for c in TAXONOMY}, **{_squash(c.name): c.id for c in TAXONOMY}}


def name_of(cid: str) -> str | None:
    """표시 이름. 알 수 없는 id 는 None (화면에서 숨긴다 — id 를 그대로 보이지 않는다)."""
    c = _BY_ID.get(cid)
    return c.name if c else None


def tip_of(cid: str) -> str | None:
    c = _BY_ID.get(cid)
    return c.tip if c else None


@dataclass(frozen=True)
class Tag:
    c: str  # 카테고리 id
    k: str  # "weak" | "strong"
    s: int  # 강도 1~3

    def to_dict(self) -> dict:
        return {"c": self.c, "k": self.k, "s": self.s}


@dataclass(frozen=True)
class Parsed:
    tags: tuple[Tag, ...] = ()
    ok: bool = True  # JSON 이 유효하면 태그가 0개여도 True ("특기할 것 없음")


# --- 프롬프트 섹션 ------------------------------------------------------------------------


def wants_tags(kind: str, level: int = 1) -> bool:
    """태그를 요청하는 종류: 코드 평가·정답 풀이·힌트 2단계 이상. 힌트 1단계(방향 제시)·연결 테스트는 요청하지 않는다."""
    return kind in ("review", "solution") or (kind == "hint" and level >= 2)


def prompt_section(kind: str) -> str:
    """프롬프트 맨 끝에 붙이는 분류 요청 섹션. 강점(strong)은 코드 평가에서만 허용한다."""
    kinds = "`weak` 또는 `strong`" if kind == "review" else "`weak` 만"
    cats = "\n".join(f"- `{c.id}` {c.definition}" for c in TAXONOMY)
    return (
        "[성장 기록용 분류] 답변의 **맨 마지막**에 아래 형식의 블록을 정확히 1개 붙이세요. "
        "앱이 읽고 지우는 기계용 블록이며 사용자에게 보이지 않습니다. 이 블록은 \"코드 블록 금지\" 같은 앞선 지시의 예외입니다.\n\n"
        "```profile\n"
        '{"v":1,"tags":[{"c":"edge","k":"weak","s":2}]}\n'
        "```\n\n"
        f"규칙: `c` 는 아래 id 중에서만. `k` 는 {kinds}. `s`: 1=언급 수준, 2=뚜렷함, 3=핵심 원인·특징. "
        "이 답변에서 **실제로 근거를 든 것만**, 최대 4개. 해당 없으면 `\"tags\":[]`. 블록 밖에 분류 설명을 쓰지 마세요.\n"
        "카테고리:\n" + cats
    )


# --- 파싱 ---------------------------------------------------------------------------------

_OPEN_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*([^`\n]*?)[ \t]*$")


@dataclass
class _Block:
    start: int  # 여는 펜스 줄 인덱스
    end: int  # 마지막 줄 인덱스 (닫는 펜스 포함, 미종결이면 마지막 줄)
    info: str
    body: str
    closed: bool


def _scan_blocks(lines: list[str]) -> list[_Block]:
    """펜스 코드 블록 전부 (미종결은 끝까지 하나로)."""
    blocks: list[_Block] = []
    i = 0
    while i < len(lines):
        m = _OPEN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        fence, info = m.group(1), m.group(2).strip().lower()
        close_re = re.compile(r"^[ \t]{0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*$")
        j = i + 1
        while j < len(lines) and not close_re.match(lines[j]):
            j += 1
        closed = j < len(lines)
        end = j if closed else len(lines) - 1
        blocks.append(_Block(i, end, info, "\n".join(lines[i + 1 : (j if closed else len(lines))]), closed))
        i = end + 1
    return blocks


def _normalize(raw) -> Parsed | None:
    """JSON 값 → Parsed. 스키마가 안 맞으면 None. 무효 항목은 버리고 유효한 것만 (규칙은 growth_tags 모듈 문서 4절)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("tags"), list):
        return None
    best: dict[tuple[str, str], int] = {}
    order: list[tuple[str, str]] = []
    for item in raw["tags"]:
        if not isinstance(item, dict):
            continue
        cid = _BY_KEY.get(_squash(item.get("c", ""))) if isinstance(item.get("c"), str) else None
        kind = KIND_ALIASES.get(_squash(item.get("k", ""))) if isinstance(item.get("k"), str) else None
        if cid is None or kind is None:
            continue
        s = item.get("s")
        strength = 1 if isinstance(s, bool) or not isinstance(s, (int, float)) else max(1, min(3, int(s)))
        key = (cid, kind)
        if key not in best:
            order.append(key)
        best[key] = max(best.get(key, 0), strength)
    # 같은 카테고리가 weak·strong 둘 다면 강도 높은 쪽 (동률이면 weak)
    for cid in {c for c, _k in best}:
        w, st = best.get((cid, "weak")), best.get((cid, "strong"))
        if w is not None and st is not None:
            best.pop((cid, "strong" if w >= st else "weak"))
    tags = [Tag(c, k, best[(c, k)]) for c, k in order if (c, k) in best]
    tags.sort(key=lambda t: -t.s)  # 안정 정렬: 강도 내림차순, 같으면 등장 순서
    return Parsed(tuple(tags[:MAX_TAGS]), True)


def _parse_json(text: str) -> Parsed | None:
    if len(text) > MAX_BLOCK_CHARS:
        return None
    try:
        return _normalize(json.loads(text))
    except ValueError:
        return None


def extract(text: str, kind: str = "review") -> tuple[str, Parsed | None]:
    """응답에서 profile 블록을 떼어 (깨끗한 본문, 태그) 를 돌려준다. 순수 함수.

    - ` ```profile ` 펜스(대소문자 무시)를 전부 찾아 파싱 성공 여부와 무관하게 본문에서 제거한다. 미종결(잘린) 블록은 끝까지.
    - 없으면 폴백: 응답의 마지막 펜스가 ` ```json ` 이고 `{"v":..,"tags":[..]}` 스키마와 일치할 때만 프로필로 취급.
    - 여러 개면 마지막 유효 블록을 쓴다. kind 가 hint/solution 이면 strong 태그는 버린다.
    - 블록이 없거나 JSON 이 깨졌으면 태그는 None (본문은 블록 제거 후 그대로).
    """
    src = text or ""
    lines = src.split("\n")
    blocks = _scan_blocks(lines)
    found = [b for b in blocks if b.info == "profile"]
    if not found and blocks:
        last = blocks[-1]
        if last.info == "json" and last.closed and _looks_like_profile(last.body):
            found = [last]
    if not found:
        return src, None
    drop: set[int] = set()
    parsed: Parsed | None = None
    for b in found:
        drop.update(range(b.start, b.end + 1))
        p = _parse_json(b.body)
        if p is not None:
            parsed = p
    clean = "\n".join(ln for i, ln in enumerate(lines) if i not in drop).rstrip()
    if parsed is not None and kind in ("hint", "solution"):
        parsed = Parsed(tuple(t for t in parsed.tags if t.k == "weak"), True)
    return clean, parsed


def _looks_like_profile(body: str) -> bool:
    try:
        raw = json.loads(body) if len(body) <= MAX_BLOCK_CHARS else None
    except ValueError:
        return False
    return isinstance(raw, dict) and "v" in raw and isinstance(raw.get("tags"), list)
