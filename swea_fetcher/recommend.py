"""오늘의 추천 (M24): 수준 모델 · 후보 선정 · 오늘의 세트 · AI 선별 보조 (파싱·합산·payload).

내 Pass 이력과 오답 횟수로 현재 수준(D1~D8)을 **규칙(사다리)** 으로 추정하고, 공개 문제 카탈로그(catalog.py)에서
아직 안 푼 문제 3~5개를 고른다. AI 는 선택 층이다 — 후보 풀 안에서만 고르게 하고 결과를 검증해(parse_ai) 쓰며,
없거나 실패하면 규칙 기반 세트가 그대로 성립한다.

- 순수 계산(수준·후보·시드·payload·파서)은 파일·네트워크·Qt·AI 를 모른다. 입력은 이미 읽어 온 값 객체다.
  세트 파일(`coach/profile/recommend.json`) 입출력만 이 모듈이 growth 의 락·원자 쓰기로 한다 (예외는 삼키고 로그만).
- 시각은 `today`/`now` 인자로 주입한다. 시드는 sha256 (파이썬 내장 hash() 금지 — 프로세스마다 달라진다).
- 수준 임계는 `THRESH` 한 곳. 실사용 뒤 이 상수만 조정한다 (초기 추정치).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Collection, Iterable, Mapping, Sequence

from . import coach, growth, problem_types as pt
from .catalog import CatalogItem, CatalogStatus
from .config import Settings

log = logging.getLogger("swea_fetcher.recommend")

DAY_FILE = "recommend.json"
DAY_VERSION = 3  # 2: 항목에 풀이 유형("ty") 추가. 3: 후보 유형은 AI 분류만 (2 이하는 제목 추정 유형이 섞여 있어 버리고 새로 만든다)
DAY_VERSIONS = (3,)
MAX_LEVEL = 8

# 수준 모델 상수 (초기 추정치 — 실사용 뒤 이 한 곳만 조정한다). 경계값은 포함.
THRESH = {
    "window_days": 90,  # 수준 판단에 쓰는 기간 (날짜 있는 사실만)
    "half_life_days": 30,  # 가중 w = 0.5^(age/30)
    "clean_max_wb": 1,  # 직전 오답 <= 1 이면 깨끗한 Pass
    "hard_min_wb": 3,  # 직전 오답 >= 3 (또는 미해결 오답 >= 3) 이면 고전
    "master_min_clean": 3,  # 숙달 판정에 필요한 깨끗한 Pass 개수 (원 개수)
    "master_max_hard_ratio": 0.5,  # hard 가중합 <= 0.5 x clean 가중합 이면 숙달 유지
    "min_known_solves": 3,  # 자동 모델로 전환하는 난이도 판명 해결 수
    "default_start": 2,  # 콜드 스타트 시작 수준
    "ok_known": 6,  # confidence "ok" 가 되는 판명 해결 수
}
_EPS = 1e-9

# 후보 선정
SET_SIZE = 4  # 기본 (3~5 허용)
RETRY_MIN_WRONG = 3  # 앱 기록상 오답 누적 이 횟수 이상이고 아직 Pass 못 한 문제 → "다시 도전"
RECENT_DAYS = 3  # 최근 며칠 안에 보여준 번호는 제외 (풀이 모자라면 완화)
RECENT_KEEP_DAYS = 14
MIN_PARTICIPANTS = 200  # 품질 하한 (소프트: 풀이 충분할 때만 적용)
MIN_PASS_RATE = 20.0
WEIGHTS_FIT = (0.4, 0.4, 0.2)  # (정답률, 참여자, 추천) 백분위 가중
WEIGHTS_STRETCH = (0.6, 0.3, 0.1)  # 한 단계 위는 정답률 높은 문제부터
SHORTLIST_FACTOR = 3  # 필요수 x 3 개의 상위 후보에서 가중 추출
AI_PICK_MAX = 8
AI_PICK_MIN = 3  # 유효 3개 미만이면 AI 실패로 본다
AI_POOL_MAX = 30
AI_REASON_MAX = 60

# 풀이 유형 분류 예산 — 방문 때(service.classify_types)와 백그라운드(service.classify_background)가 같은 상한·카운터를 쓴다 (한 곳에서만 고친다)
# 한 번 호출에 5문제(풀이 설계를 쓰게 하므로 작게), 시간당 60문제 · 하루 400문제. 방문 때는 한 번 실행에서 푼 문제 24 · 새 유형 후보 12 · 일반 후보 16 까지만
CLASSIFY_BATCH = 5
CLASSIFY_HOURLY_CAP = 60
CLASSIFY_DAILY_CAP = 400
CLASSIFY_SOLVED_MAX = 24
CLASSIFY_NEWTYPE_MAX = 12
CLASSIFY_CAND_MAX = 16

KIND_ORDER = ("retry", "fit", "stretch", "fill", "newtype")
KIND_LABEL = {"retry": "다시 도전", "fit": "수준 맞춤", "stretch": "한 단계 위", "fill": "수준 맞춤", "newtype": "새 유형"}
AI_STATUSES = ("none", "pending", "ok", "failed", "skipped")


# --- 데이터 -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SolveFact:
    """수준 판단의 사실 1건. level 이 None 이면 카탈로그에서 난이도를 모르는 문제."""

    num: int
    level: int | None
    day: date | None  # 날짜 미상은 None (SWEA 정답 목록)
    struggle: int = 0  # Pass 직전 오답 누적 (미해결이면 오답 누적)
    source: str = "app"  # "app" | "swea"
    solved: bool = True


@dataclass(frozen=True)
class LevelEstimate:
    level: int  # C: 1..8
    confidence: str  # "cold" | "low" | "ok"
    basis: str  # 화면용 한 줄
    n_known: int = 0  # 난이도가 판명된 해결 수
    n_unknown: int = 0  # 난이도를 몰라 제외한 해결 수
    per_level: dict = field(default_factory=dict)  # {L: (clean 가중합, hard 가중합)}
    clean_n: dict = field(default_factory=dict)  # {L: 깨끗한 Pass 원 개수}
    source: str = "app"  # "app" | "swea" | "cold"

    @property
    def cold(self) -> bool:
        return self.confidence == "cold"

    @property
    def levels(self) -> tuple[int, ...]:
        """후보 구간 {C, C+1} (C=8 이면 {8})."""
        return (self.level,) if self.level >= MAX_LEVEL else (self.level, self.level + 1)


@dataclass(frozen=True)
class RetryCand:
    num: int
    wrong_count: int


@dataclass(frozen=True)
class AiPick:
    num: int
    reason: str | None = None


@dataclass
class Pick:
    """오늘의 세트 한 칸 (표시 전 단계)."""

    num: int
    kind: str  # retry | fit | stretch | fill | newtype
    reason: str
    source: str = "rule"  # "rule" | "ai"
    key: float = 0.0  # 같은 kind 안 정렬 키 (작을수록 먼저)
    types: tuple[str, ...] = ()  # 풀이 유형 (주 유형 먼저). 비어 있으면 유형 미확인


@dataclass
class SetBuild:
    picks: list[Pick] = field(default_factory=list)
    ai_used: int = 0  # 이번 세트에 쓴 AI 순위 소비량 (ai.cursor 전진량)
    short: bool = False  # 3개 미만


@dataclass
class Recommendation:
    num: int
    title: str
    level: int
    pass_rate: float | None
    participants: int | None
    kind: str
    reason: str
    source: str  # "rule" | "ai"
    solved_today: bool = False
    types: tuple[str, ...] = ()  # 풀이 유형 id (주 유형 먼저). 비어 있으면 유형 미확인
    why: str = ""  # AI 가 그 유형이라고 본 이유 한 줄 (칩 툴팁 "왜 이 유형?"). 없으면 ""


@dataclass
class RecommendResult:
    day: date
    items: list[Recommendation] = field(default_factory=list)
    level: LevelEstimate | None = None
    source: str = "rule"  # rule | ai | mixed
    ai_status: str = "off"  # off | skipped_low_data | needs_consent | no_engine | pending | ok | failed | cancelled | none
    ai_engines: list[str] = field(default_factory=list)
    catalog: CatalogStatus | None = None
    shuffle: int = 0
    notes: list[str] = field(default_factory=list)
    used_swea_passed: bool = False
    weak_tagged: int = 0  # 최근 28일 분류 그룹 수 (AI 안내 문구용)
    type_counts: dict = field(default_factory=dict)  # {유형 id: 앱에 Pass 기록된 문제 수} — "풀어 본 유형" 줄 (폴더 이름은 증거가 아니다)
    type_progress: tuple[int, int] = (0, 0)  # (유형을 분류한 카탈로그 문제 수, 카탈로그 문제 수) — 카드 푸터 "풀이 유형 분류 312 / 926"
    type_capped: str = ""  # 분류 상한에 막힌 상태: "" | "day"(오늘 한도 도달) | "hour"(이번 시간 한도 도달)


# --- 수준 모델 ------------------------------------------------------------------------------------


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def _clamp_level(x: int) -> int:
    return max(1, min(MAX_LEVEL, int(x)))


def _weighted_median(pairs: list[tuple[int, float]]) -> float:
    """[(레벨, 가중)] 의 가중 중앙값. 누적이 정확히 절반이면 다음 레벨과의 평균."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    acc = 0.0
    for i, (lv, w) in enumerate(pairs):
        acc += w
        if acc > total / 2 + _EPS:
            return float(lv)
        if abs(acc - total / 2) <= _EPS and i + 1 < len(pairs):
            return (lv + pairs[i + 1][0]) / 2
    return float(pairs[-1][0])


def _percentile(levels: list[int], q: float) -> float:
    s = sorted(levels)
    if len(s) == 1:
        return float(s[0])
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def estimate_level(facts: Iterable[SolveFact], today: date, start_level: int | None = None) -> LevelEstimate:
    """사다리 규칙으로 현재 수준 C 추정 (설계 6.2).

    1. 최근 90일 날짜 있는 사실을 레벨별 clean/hard 가중합으로 모은다 (가중 0.5^(나이/30)).
    2. 깨끗한 Pass 가 3개 이상이고 hard <= 0.5 x clean 인 레벨을 "숙달" 로 보고 C = 숙달 최고 레벨.
    3. 숙달이 없으면 판명 해결이 3개 이상일 때 가중 중앙값, 그보다 적으면 SWEA 정답 목록 근사(70분위) 또는
       콜드 스타트 max(시작 수준, 가장 높은 해결 레벨).
    """
    t = THRESH
    start = _clamp_level(start_level if start_level else t["default_start"])
    by_num: dict[int, SolveFact] = {}
    for f in facts:  # 같은 문제는 1건: 해결 > 미해결, 앱 기록(날짜·고전 있음) > SWEA 정답 목록
        cur = by_num.get(f.num)
        if cur is None or (f.solved and not cur.solved) or (f.solved == cur.solved and f.source == "app" and cur.source != "app"):
            by_num[f.num] = f
    in_scope: list[SolveFact] = []  # 최근 90일 날짜 있는 사실 + 날짜 미상(SWEA)
    for f in by_num.values():
        if f.day is None:
            in_scope.append(f)
        elif 0 <= (today - f.day).days <= t["window_days"] or (today - f.day).days < 0:
            in_scope.append(f)

    clean_w: dict[int, float] = defaultdict(float)
    hard_w: dict[int, float] = defaultdict(float)
    n_clean: Counter = Counter()
    for f in in_scope:
        if f.day is None or not f.level:
            continue
        w = 0.5 ** (max(0, (today - f.day).days) / t["half_life_days"])
        if f.solved and f.struggle <= t["clean_max_wb"]:
            clean_w[f.level] += w
            n_clean[f.level] += 1
        elif f.struggle >= t["hard_min_wb"]:
            hard_w[f.level] += w
    per_level = {lv: (round(clean_w[lv], 4), round(hard_w[lv], 4)) for lv in sorted(set(clean_w) | set(hard_w))}

    solved_scope = [f for f in in_scope if f.solved]
    known = [f for f in solved_scope if f.level]
    n_known = len(known)
    n_unknown = len(solved_scope) - n_known
    app_known = [f for f in known if f.source == "app" and f.day is not None]
    tail = f" · 난이도를 모르는 {n_unknown}문제 제외" if n_unknown else ""

    mastered = [lv for lv in range(1, MAX_LEVEL + 1)
                if n_clean[lv] >= t["master_min_clean"] and hard_w[lv] <= t["master_max_hard_ratio"] * clean_w[lv] + _EPS]
    source = "app"
    if mastered:
        c = max(mastered)
    elif len(app_known) >= t["min_known_solves"]:
        pairs = [(f.level, 0.5 ** (max(0, (today - f.day).days) / t["half_life_days"])) for f in app_known]  # type: ignore[arg-type]
        c = _round_half_up(_weighted_median(pairs))
    elif n_known >= t["min_known_solves"] and any(f.source == "swea" for f in known):
        c = _round_half_up(_percentile([f.level for f in known], 0.7))  # type: ignore[misc]
        source = "swea"
    else:
        highest = max((f.level for f in by_num.values() if f.solved and f.level), default=0)  # 오래된 해결까지 반영
        c = max(start, highest)
        source = "cold"
    c = _clamp_level(c)

    if source == "cold" or n_known < t["min_known_solves"]:
        conf, basis = "cold", f"기록이 적어 D{c} 부터 시작해요" + tail
        source = "cold"
    elif source == "swea":
        conf, basis = "low", "SWEA 에서 푼 문제 기준" + tail
    else:
        conf = "ok" if n_known >= t["ok_known"] else "low"
        basis = f"최근 {t['window_days']}일 {n_known}문제 기준" + tail
    return LevelEstimate(c, conf, basis, n_known, n_unknown, per_level, dict(n_clean), source)


def facts_from_history(
    *,
    solved_first_day: Mapping[int, date],
    pass_wb: Mapping[int, int],
    unsolved: Iterable[tuple[int, int, date | None]],
    swea_passed: Iterable[int],
    levels: Mapping[int, int],
) -> list[SolveFact]:
    """이미 읽어 온 기록 → 사실 목록 (순수).

    solved_first_day: 앱 기록 해결 문제의 첫 Pass 날짜 / pass_wb: 그 Pass 직전 오답 (이벤트 없으면 0)
    unsolved: (번호, 오답 누적, 마지막 제출 날짜) — 오답 3회 이상 미해결만 / swea_passed: SWEA 정답 목록 번호
    levels: 카탈로그 {번호: 난이도 1..8} (모르면 없음)
    """
    facts: list[SolveFact] = []
    solved_nums = set(solved_first_day)
    for num, day in solved_first_day.items():
        facts.append(SolveFact(num, levels.get(num) or None, day, max(0, int(pass_wb.get(num, 0))), "app", True))
    for num, wrong, day in unsolved:
        if num in solved_nums or wrong < THRESH["hard_min_wb"]:
            continue
        facts.append(SolveFact(num, levels.get(num) or None, day, int(wrong), "app", False))
    for num in swea_passed:
        if num not in solved_nums:
            facts.append(SolveFact(num, levels.get(num) or None, None, 0, "swea", True))
    return facts


def retry_candidates(records: Iterable[tuple[int, int, str]], solved_nums: Collection[int]) -> list[RetryCand]:
    """오답 누적 >= 3 인데 아직 Pass 못 한 문제. records: (번호, 오답 누적, 마지막 결과)."""
    out = [RetryCand(n, wc) for n, wc, last in records if wc >= RETRY_MIN_WRONG and last != "pass" and n not in solved_nums]
    return sorted(out, key=lambda r: (-r.wrong_count, r.num))


# --- 후보 선정 · 오늘의 세트 --------------------------------------------------------------------------


_ROMAN_TAIL_RE = re.compile(r"[\s\-_.:]+(?:i{1,3}|iv|v|vi{1,3}|ix|x)$", re.I)
_TAIL_RES = (re.compile(r"\s*\[\d+\]\s*$"), re.compile(r"[\s\-_.:]*\d+\s*$"), re.compile(r"[\s\-_.:]*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s*$"), _ROMAN_TAIL_RE)


def stem(title: str) -> str:
    """제목 어간: 끝의 숫자·로마숫자·[n]·공백을 반복해서 걷어낸 casefold ("미로 1"/"미로 2" → "미로")."""
    s = (title or "").strip()
    for _ in range(6):
        before = s
        for rx in _TAIL_RES:
            s = rx.sub("", s)
        s = s.strip()
        if s == before:
            break
    return (s or (title or "").strip()).casefold()


def day_seed(day: date, shuffle: int, level: int) -> int:
    """날짜+셔플 카운터+수준으로 만든 결정적 시드 (sha256; 내장 hash() 금지)."""
    return int(hashlib.sha256(f"{day.isoformat()}:{shuffle}:{level}".encode("utf-8")).hexdigest()[:16], 16)


def _percentiles(values: list[float | None]) -> list[float]:
    """중간 순위 백분위 (0~1). 결측은 0.5."""
    known = [v for v in values if v is not None]
    n = len(known)
    out: list[float] = []
    for v in values:
        if v is None or n == 0:
            out.append(0.5)
            continue
        less = sum(1 for k in known if k < v)
        equal = sum(1 for k in known if k == v)
        out.append((less + 0.5 * equal) / n)
    return out


def quality_scores(items: Sequence[CatalogItem], weights: tuple[float, float, float]) -> dict[int, float]:
    """같은 풀 안 백분위 가중합 (정답률 · 참여자 · 추천)."""
    if not items:
        return {}
    pr = _percentiles([it.pr for it in items])
    pa = _percentiles([float(it.pa) if it.pa is not None else None for it in items])
    rc = _percentiles([float(it.rc) if it.rc is not None else None for it in items])
    wp, wa, wr = weights
    return {it.num: wp * pr[i] + wa * pa[i] + wr * rc[i] for i, it in enumerate(items)}


def _apply_quality_floor(pool: list[CatalogItem], need: int) -> list[CatalogItem]:
    """참여자·정답률 하한 (소프트): 하한을 적용해도 풀이 필요량의 2배 이상 남을 때만 쓴다. 값이 None 이면 하한 미적용."""
    kept = [it for it in pool if not ((it.pa is not None and it.pa < MIN_PARTICIPANTS) or (it.pr is not None and it.pr < MIN_PASS_RATE))]
    return kept if len(kept) >= 2 * need else pool


def _draw(rng: random.Random, pool: list[CatalogItem], scores: Mapping[int, float], need: int, used_stems: set[str]) -> list[CatalogItem]:
    """상위 후보(필요수 x 3)에서 quality + 0.05 가중으로 비복원 추출. 같은 어간은 한 세트에 1개."""
    k = max(1, need) * SHORTLIST_FACTOR
    out: list[CatalogItem] = []
    remaining = [it for it in pool if stem(it.title) not in used_stems]
    while remaining and len(out) < need:
        remaining.sort(key=lambda it: (-scores.get(it.num, 0.0), it.num))
        short = remaining[:k]
        weights = [scores.get(it.num, 0.0) + 0.05 for it in short]
        r = rng.random() * sum(weights)
        acc = 0.0
        chosen = short[-1]
        for it, w in zip(short, weights):
            acc += w
            if r < acc:
                chosen = it
                break
        out.append(chosen)
        used_stems.add(stem(chosen.title))
        remaining = [it for it in remaining if it.num != chosen.num and stem(it.title) not in used_stems]
    return out


def _tiered_pool(base: list[CatalogItem], need: int, recent: Collection[int], day_shown: Collection[int]) -> list[CatalogItem]:
    """제외 단계: (최근 노출 + 오늘 노출) → (오늘 노출) → 없음. 앞 단계에서 풀이 필요량의 2배 미만이면 완화."""
    t1 = [it for it in base if it.num not in recent and it.num not in day_shown]
    if len(t1) >= 2 * need:
        return t1
    t2 = [it for it in base if it.num not in day_shown]
    if len(t2) >= 2 * need:
        return t2
    return base


def _type_name(types: Sequence[str]) -> str:
    return (pt.name_of(types[0]) or "") if types else ""


def reason_for(kind: str, est: LevelEstimate, wrong_count: int = 0, *, types: Sequence[str] = (), counts: Mapping[str, int] | None = None) -> str:
    """규칙 기반 이유 문구 (숫자는 계산값만). types 가 있으면 주 유형 이름을 앞에 붙인다."""
    c = est.level
    if kind == "retry":
        return f"오답 {wrong_count}회로 남아 있어요 · 다시 도전해 볼까요"
    name = _type_name(types)
    n = (counts or {}).get(types[0], 0) if types else 0  # 이 유형으로 앱에 Pass 기록된 문제 수
    if kind == "fit":
        if name:
            return f"{name} · 풀어 본 유형이에요 ({n}문제 해결) · D{c} 감을 굳혀요" if n else f"{name} · 입문 유형으로 D{c} 부터 시작해요"
        if est.cold:
            return f"기록이 적어 D{c} 부터 시작해요"
        k = est.clean_n.get(c, 0)
        if k >= 1:
            return f"최근 D{c} 를 {k}문제 안정적으로 풀었어요 · 같은 수준으로 감을 굳혀요"
        return f"요즘 푸는 D{c} 수준에 맞춰 골랐어요"
    if kind == "stretch":
        if name:
            return f"{name} · 풀어 본 유형으로 한 단계 위 D{c + 1} 에 도전해요" if n else f"{name} · 입문 유형으로 한 단계 위에 가볍게 도전해요"
        if est.cold:
            return "한 단계 위 문제로 가볍게 도전해요"
        if est.clean_n.get(c, 0) >= THRESH["master_min_clean"]:
            return f"D{c} 를 안정적으로 풀었어요 · 한 단계 올려 볼 때예요"
        return "한 단계 위 문제로 가볍게 도전해요"
    if name:
        return f"{name} · 풀어 본 유형 중 비슷한 난이도예요" if n else f"{name} · 입문 유형 중 비슷한 난이도예요"
    return "비슷한 난이도 중 많은 사람이 푼 문제예요"


def newtype_reason(tid: str, lv: int, est: LevelEstimate, known: Collection[str]) -> str:
    """새 유형 칸 이유: 어떤 유형을, 얼마나 쉬운 난이도로, 어떤 경험을 바탕으로 소개하는지."""
    name = pt.name_of(tid) or ""
    diff = est.level - lv
    step = "지금 수준과 같은" if diff <= 0 else ("한 단계 쉬운" if diff == 1 else f"{diff}단계 쉬운")
    pre = pt.prereq_names(tid, known) or pt.prereq_names(tid, pt.implied(known))
    tail = f"{'·'.join(pre)} 경험이 있어 다음 단계예요" if pre else "기본 유형이라 먼저 익혀 두면 좋아요"
    return f"{name} 첫걸음 · {step} D{lv} 로 시작해요 ({tail})"


def build_set(
    catalog: Mapping[int, CatalogItem],
    est: LevelEstimate,
    *,
    day: date,
    shuffle: int = 0,
    solved_nums: Collection[int] = (),
    retry: Sequence[RetryCand] = (),
    recent_shown: Mapping[int, date] | None = None,
    day_shown: Collection[int] = (),
    ai_picks: Sequence[AiPick] = (),
    ai_cursor: int = 0,
    size: int = SET_SIZE,
    types: Mapping[int, Sequence[str]] | None = None,
    known: Collection[str] = (),
    type_counts: Mapping[str, int] | None = None,
) -> SetBuild:
    """오늘의 세트: 재도전 0~1 + 새 유형 0~1 + 수준 맞춤(C) + 한 단계 위(C+1), 부족하면 C-1 → C+2 로 확장 (설계 7.2, M24.1).

    같은 (날짜, 셔플, 수준, 입력) 이면 항상 같은 세트. AI 순위(ai_picks[ai_cursor:])가 있으면 "나머지 칸"을 먼저 AI 순위로
    채우고(풀·구간·유형 검증을 다시 통과한 것만) 모자란 칸은 규칙으로 채운다.

    풀이 유형 (types: {번호: 유형 id 들}, known: 내가 풀어 본 유형): 수준 맞춤·한 단계 위·확장 칸은 **유형이 모두 풀어 본 유형 안**인 문제만
    고른다 (아는 유형이 없으면 입문 유형). 유형을 모르는 문제는 그런 후보가 바닥난 뒤에만 채운다. 풀어 보지 않은 유형은 "새 유형" 칸에서
    학습 경로상 다음 유형 1문제를 한 단계 쉬운 난이도로 소개한다 (아는 유형이 없으면 칸을 만들지 않는다).
    """
    c = est.level
    rng = random.Random(day_seed(day, shuffle, c))
    solved = set(solved_nums)
    shown_today = set(day_shown)
    recent = {n for n, d in (recent_shown or {}).items() if 0 <= (day - d).days < RECENT_DAYS}
    retry_all = {r.num for r in retry}
    levels = est.levels
    picks: list[Pick] = []
    used_stems: set[str] = set()
    tmap = types or {}
    known_set = frozenset(known)
    allowed = pt.allowed_for(known_set)
    counts = type_counts or {}

    def tys(n: int) -> tuple[str, ...]:
        return tuple(tmap.get(n) or ())

    def known_ok(it: CatalogItem) -> bool:
        return pt.type_ok(tys(it.num), allowed)

    def unknown(it: CatalogItem) -> bool:
        return not tys(it.num)

    # 재도전 (규칙 전용): 레벨 C-1..C+1 의 미해결 고전 문제 중 오답이 큰 순
    retry_pick: RetryCand | None = None
    for r in retry:
        it = catalog.get(r.num)
        if it is None or r.num in solved or not it.lv or abs(it.lv - c) > 1:
            continue
        if shuffle > 0 and r.num in shown_today:
            continue
        retry_pick = r
        break
    if retry_pick is not None:
        it = catalog[retry_pick.num]
        picks.append(Pick(it.num, "retry", reason_for("retry", est, retry_pick.wrong_count), types=tys(it.num)))
        used_stems.add(stem(it.title))

    # 새 유형 (규칙 전용): 경로상 다음 유형 중 후보가 있는 첫 유형 1문제, 한 단계 쉬운 난이도 (없으면 두 단계 쉬운 → 같은 난이도)
    def newtype_pick() -> tuple[CatalogItem, str] | None:
        eff = pt.implied(known_set)
        taken = {p.num for p in picks}
        for tid in pt.next_types(known_set):
            for lv in dict.fromkeys((max(1, c - 1), c - 2, c)):
                if lv < 1:
                    continue
                pool = [it for it in catalog.values()
                        if it.lv == lv and it.num not in solved and it.num not in retry_all and it.num not in taken
                        and tys(it.num)[:1] == (tid,) and all(t == tid or t in eff for t in tys(it.num))
                        and not (shuffle > 0 and it.num in shown_today) and stem(it.title) not in used_stems]
                if not pool:
                    continue
                pool = _apply_quality_floor(_tiered_pool(pool, 1, recent, shown_today if shuffle > 0 else ()), 1)
                got = _draw(rng, pool, quality_scores(pool, WEIGHTS_STRETCH), 1, used_stems)  # 정답률 높은 문제부터
                if got:
                    return got[0], tid
        return None

    if known_set and size - len(picks) >= 2:
        nt = newtype_pick()
        if nt is not None:
            it, tid = nt
            picks.append(Pick(it.num, "newtype", newtype_reason(tid, it.lv, est, known_set), "rule", 0.0, tys(it.num)))
    r_slots = size - len(picks)

    def base_pool(lv: int) -> list[CatalogItem]:
        return [it for it in catalog.values() if it.lv == lv and it.num not in solved and it.num not in retry_all]

    # AI 순위로 먼저 채움 (유형 검증을 한 번 더: 풀어 본 유형 밖이거나 유형을 모르는 문제는 버린다)
    ai_used = 0
    ai_taken: list[Pick] = []
    if ai_picks and r_slots > 0:
        idx = max(0, ai_cursor)
        while idx < len(ai_picks) and len(ai_taken) < r_slots:
            p = ai_picks[idx]
            idx += 1
            it = catalog.get(p.num)
            if (it is None or it.num in solved or it.num in retry_all or it.lv not in levels or not known_ok(it)
                    or (shuffle > 0 and it.num in shown_today) or stem(it.title) in used_stems
                    or any(x.num == it.num for x in ai_taken) or any(x.num == it.num for x in picks)):
                continue
            kind = "fit" if it.lv == c else "stretch"
            ai_taken.append(Pick(it.num, kind, p.reason or reason_for(kind, est, types=tys(it.num), counts=counts), "ai", float(len(ai_taken)), tys(it.num)))
            used_stems.add(stem(it.title))
        ai_used = idx - max(0, ai_cursor) if ai_taken else 0
    picks.extend(ai_taken)

    # 규칙으로 채움
    fit_total = r_slots if c >= MAX_LEVEL else r_slots // 2
    stretch_total = r_slots - fit_total

    def balance(need_fit: int, need_stretch: int, total: int) -> tuple[int, int]:
        """남은 칸 수(total)에 맞춰 수준 맞춤/한 단계 위 칸 수를 조정한다 (AI 가 한쪽만 채워 합이 어긋나는 경우)."""
        while need_fit + need_stretch > total:
            if need_fit >= need_stretch and need_fit > 0:
                need_fit -= 1
            else:
                need_stretch -= 1
        while need_fit + need_stretch < total:
            if c >= MAX_LEVEL or need_fit <= need_stretch:
                need_fit += 1
            else:
                need_stretch += 1
        return need_fit, need_stretch

    def remaining_needs() -> tuple[int, int]:
        have_fit = sum(1 for p in picks if p.kind == "fit")
        have_stretch = sum(1 for p in picks if p.kind == "stretch")
        return balance(max(0, fit_total - have_fit), max(0, stretch_total - have_stretch), size - len(picks))

    taken_nums = {p.num for p in picks}

    def rule_fill(lv: int, need: int, kind: str, weights: tuple[float, float, float], tier: str = "known") -> None:
        if need <= 0 or lv < 1 or lv > MAX_LEVEL:
            return
        sel = known_ok if tier == "known" else unknown
        base = [it for it in base_pool(lv) if it.num not in taken_nums and sel(it)]
        pool = _tiered_pool(base, need, recent, shown_today if shuffle > 0 else ())
        pool = _apply_quality_floor(pool, need)
        scores = quality_scores(pool, weights)
        for it in _draw(rng, pool, scores, need, used_stems):
            taken_nums.add(it.num)
            picks.append(Pick(it.num, kind, reason_for(kind, est, types=tys(it.num), counts=counts), "rule", -scores.get(it.num, 0.0), tys(it.num)))

    def fill_all(tier: str) -> None:
        need_fit, need_stretch = remaining_needs()
        rule_fill(c, need_fit, "fit", WEIGHTS_FIT, tier)
        if c < MAX_LEVEL:
            rule_fill(c + 1, need_stretch, "stretch", WEIGHTS_STRETCH, tier)
        # 한 풀이 모자라면 다른 풀로 채운다 (수준 맞춤 → 한 단계 위)
        rule_fill(c, size - len(picks), "fit", WEIGHTS_FIT, tier)
        if c < MAX_LEVEL:
            rule_fill(c + 1, size - len(picks), "stretch", WEIGHTS_STRETCH, tier)
        # 모자라면 구간을 넓힌다: C-1, 그다음 C+2 (이유 "비슷한 난이도 중…")
        for lv in (c - 1, c + 2):
            short = size - len(picks)
            if short > 0:
                rule_fill(lv, short, "fill", WEIGHTS_FIT, tier)

    fill_all("known")
    if size - len(picks) > 0:
        fill_all("unknown")  # 유형을 아는 후보가 바닥난 뒤에만 "유형 미확인" 문제로 채운다

    picks.sort(key=lambda p: (KIND_ORDER.index(p.kind), p.key, p.num))
    return SetBuild(picks, ai_used, short=len(picks) < 3)


# --- 오늘의 세트 저장 (coach/profile/recommend.json) ----------------------------------------------------


@dataclass
class DaySet:
    date: str  # YYYY-MM-DD
    shuffle: int = 0
    level_c: int = 0
    conf: str = ""
    start: int = 0  # 이 세트를 만들 때의 시작 수준 선택값 (콜드 스타트 선택기가 바뀌었는지 판단)
    items: list[dict] = field(default_factory=list)  # {"n","k","r","src","ty"} (ty: 풀이 유형 id 목록 — 없으면 유형 미확인)
    day_shown: list[int] = field(default_factory=list)
    recent_shown: dict[str, str] = field(default_factory=dict)  # {"번호": "YYYY-MM-DD"}
    ai: dict = field(default_factory=dict)  # {"status","engines","at","picks":[{"n","r"}],"cursor","fail_count"}

    def ai_status(self) -> str:
        s = str(self.ai.get("status") or "none")
        return s if s in AI_STATUSES else "none"

    def ai_picks(self) -> list[AiPick]:
        out = []
        for p in self.ai.get("picks") or []:
            if isinstance(p, dict) and isinstance(p.get("n"), int) and not isinstance(p.get("n"), bool):
                r = p.get("r")
                out.append(AiPick(p["n"], r if isinstance(r, str) and r else None))
        return out

    def recent_dates(self) -> dict[int, date]:
        out: dict[int, date] = {}
        for k, v in self.recent_shown.items():
            try:
                out[int(k)] = date.fromisoformat(v)
            except (TypeError, ValueError):
                continue
        return out

    def to_dict(self) -> dict:
        return {"v": DAY_VERSION, "date": self.date, "shuffle": self.shuffle, "level": {"c": self.level_c, "conf": self.conf, "start": self.start},
                "items": self.items, "day_shown": self.day_shown, "recent_shown": self.recent_shown, "ai": self.ai}


def day_path(settings: Settings) -> Path:
    return growth.profile_dir(settings) / DAY_FILE


def _clean_items(raw: object) -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for it in raw:
        if not isinstance(it, dict) or not isinstance(it.get("n"), int) or isinstance(it.get("n"), bool):
            continue
        kind = it.get("k") if it.get("k") in KIND_ORDER else "fill"
        src = "ai" if it.get("src") == "ai" else "rule"
        row = {"n": it["n"], "k": kind, "r": str(it.get("r") or ""), "src": src}
        ty = pt.clean_ids(it.get("ty"))
        if ty:
            row["ty"] = list(ty)
        out.append(row)
    return out


def load_day(settings: Settings) -> DaySet | None:
    """저장된 오늘의 세트. 없거나 손상이면 None (손상 파일은 .corrupt 로 이동). 예외 없음."""
    path = day_path(settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.warning("추천 기록을 읽지 못해 새로 시작합니다: %s", e)
        _quarantine(path)
        return None
    try:
        if not isinstance(raw, dict) or raw.get("v") not in DAY_VERSIONS:
            raise ValueError("version")
        date.fromisoformat(str(raw["date"]))
        level = raw.get("level") if isinstance(raw.get("level"), dict) else {}
        shown = [n for n in (raw.get("day_shown") or []) if isinstance(n, int) and not isinstance(n, bool)]
        recent = {str(k): str(v) for k, v in (raw.get("recent_shown") or {}).items()} if isinstance(raw.get("recent_shown"), dict) else {}
        ai = raw.get("ai") if isinstance(raw.get("ai"), dict) else {}
        return DaySet(str(raw["date"]), max(0, int(raw.get("shuffle") or 0)), int(level.get("c") or 0), str(level.get("conf") or ""),
                      int(level.get("start") or 0), _clean_items(raw.get("items")), shown, recent, dict(ai))
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        log.warning("추천 기록 형식이 올바르지 않아 새로 시작합니다: %s", e)
        _quarantine(path)
        return None


def _quarantine(path: Path) -> None:
    try:
        os.replace(path, path.with_suffix(path.suffix + ".corrupt"))
    except OSError:
        pass


def save_day(settings: Settings, ds: DaySet) -> bool:
    """tmp + os.replace 원자 쓰기. 루트 폴더 안이면 거부. 예외 없음 (실패는 False)."""
    if not growth._writable(settings):
        return False
    try:
        with growth._LOCK:
            coach._atomic_write(day_path(settings), ds.to_dict())
    except OSError as e:
        log.warning("추천 기록 저장 실패: %s", e)
        return False
    return True


def prune_recent(recent: Mapping[str, str], today: date) -> dict[str, str]:
    """14일이 지난 노출 기록을 걷어낸다."""
    out: dict[str, str] = {}
    for k, v in recent.items():
        try:
            if (today - date.fromisoformat(v)).days <= RECENT_KEEP_DAYS:
                out[k] = v
        except ValueError:
            continue
    return out


def items_of(picks: Iterable[Pick]) -> list[dict]:
    return [{"n": p.num, "k": p.kind, "r": p.reason, "src": p.source, **({"ty": list(p.types)} if p.types else {})} for p in picks]


# --- AI 층 보조 (payload · 파서 · 합산) ------------------------------------------------------------------


# AI 로 보내는 값의 허용 키 (이 밖의 키는 구조적으로 못 들어간다)
PAYLOAD_KEYS = ("level", "known", "weak", "strong", "stats", "pool", "want")
LEVEL_KEYS = ("estimate", "confidence", "recent_solved_by_level")
POOL_KEYS = ("n", "t", "lv", "pr", "pa", "ty")
CATEGORY_KEYS = ("name", "score")
STATS_KEYS = ("avg_wrong_before_pass", "timeout_share", "tagged")


def ranked_pool(catalog: Mapping[int, CatalogItem], lv: int, weights: tuple[float, float, float], skip: Collection[int] = ()) -> list[CatalogItem]:
    """레벨 lv 의 안 푼 문제를 quality 순으로 (풀이 유형 분류 대상 후보 선정용: 상위부터 분류해 나간다)."""
    skip_set = set(skip)
    pool = _apply_quality_floor([it for it in catalog.values() if it.lv == lv and it.num not in skip_set], AI_POOL_MAX // 2)
    scores = quality_scores(pool, weights)
    pool.sort(key=lambda it: (-scores.get(it.num, 0.0), it.num))
    return pool


def ai_pool(
    catalog: Mapping[int, CatalogItem], est: LevelEstimate, *, solved_nums: Collection[int], excluded: Collection[int] = (),
    types: Mapping[int, Sequence[str]] | None = None, known: Collection[str] = (),
) -> list[CatalogItem]:
    """AI 에게 보여줄 후보 풀: 구간 레벨의 안 푼 문제 중 quality 상위 (fit 15 + stretch 15). 푼/재도전 문제는 이미 빠져 있다.

    types 를 주면 (M24.1) 유형을 알고 모두 풀어 본 유형(known, 없으면 입문 유형) 안인 문제만 담는다 — 새 유형은 규칙이 따로 고른다."""
    skip = set(solved_nums) | set(excluded)
    allowed = pt.allowed_for(frozenset(known))
    out: list[CatalogItem] = []
    for lv, w in zip(est.levels, (WEIGHTS_FIT, WEIGHTS_STRETCH)):
        pool = [it for it in catalog.values() if it.lv == lv and it.num not in skip
                and (types is None or pt.type_ok(tuple(types.get(it.num) or ()), allowed))]
        pool = _apply_quality_floor(pool, AI_POOL_MAX // 2)
        scores = quality_scores(pool, w)
        pool.sort(key=lambda it: (-scores.get(it.num, 0.0), it.num))
        out.extend(pool[: AI_POOL_MAX // 2 if len(est.levels) > 1 else AI_POOL_MAX])
    return out


def ai_payload(
    est: LevelEstimate,
    *,
    recent_solved_by_level: Mapping[int, int],
    weak: Sequence[tuple[str, int]],
    strong: Sequence[tuple[str, int]],
    stats: Mapping[str, float | int | None],
    pool: Sequence[CatalogItem],
    want: int = AI_PICK_MAX,
    clean_title=lambda s: s,
    known: Sequence[str] = (),
    types: Mapping[int, Sequence[str]] | None = None,
) -> dict:
    """AI 로 보내는 dict. **이미 집계된 값 객체만** 받고 허용 키로만 만든다 (코드·지문·내가 푼/시도한 문제 번호·제목·폴더명·경로·ID 는 입력 자체가 없다).

    clean_title: 제목 무해화 함수 (ai_prompts.neutralize). 제목은 60자로 자른다.
    known: 일반 칸에 쓸 수 있는 유형 id (풀어 본 유형, 없으면 입문 유형) / types: 후보별 유형 id — 둘 다 분류 체계의 표시 이름으로만 나간다.
    """
    def cats(rows: Sequence[tuple[str, int]]) -> list[dict]:
        return [{"name": str(n)[:30], "score": int(s)} for n, s in list(rows)[:4]]

    return {
        "level": {
            "estimate": est.level,
            "confidence": est.confidence,
            "recent_solved_by_level": {f"D{lv}": int(n) for lv, n in sorted(recent_solved_by_level.items()) if n},
        },
        "known": pt.names_of(known),
        "weak": cats(weak),
        "strong": cats(strong),
        "stats": {k: (round(float(v), 2) if isinstance(v, float) else v) for k, v in stats.items() if k in STATS_KEYS},
        "pool": [
            {"n": it.num, "t": clean_title(it.title)[:AI_REASON_MAX], "lv": it.lv,
             "pr": round(it.pr, 1) if it.pr is not None else None, "pa": it.pa,
             "ty": pt.names_of(tuple((types or {}).get(it.num) or ()))}
            for it in list(pool)[:AI_POOL_MAX]
        ],
        "want": max(1, min(AI_PICK_MAX, int(want))),
    }


_FENCE_RE = re.compile(r"```[a-zA-Z]*|~~~[a-zA-Z]*")
_LINK_RE = re.compile(r"!?\[([^\]\n]*)\]\([^)\n]*\)")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_reason(text: object) -> str | None:
    """AI 이유 문장 정리: 제어문자·개행·링크·URL·백틱 제거, 60자 절단. 빈 값이면 None."""
    if not isinstance(text, str):
        return None
    s = _LINK_RE.sub(lambda m: m.group(1), text)
    s = _URL_RE.sub("", s)
    s = _FENCE_RE.sub("", s).replace("`", "")
    s = _CTRL_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    return s[:AI_REASON_MAX].rstrip()


def parse_ai(text: str, pool_nums: Collection[int]) -> list[AiPick] | None:
    """AI 응답 → 검증된 순위 목록. 첫 `{` ~ 마지막 `}` 를 JSON 으로 읽고(코드 펜스·잡문 허용) 풀에 없는 번호·중복·형식 오류는
    버린다. 최대 8개. **유효 3개 미만이면 None (실패 — 규칙 기반 유지).**"""
    if not isinstance(text, str):
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        raw = json.loads(text[start : end + 1])
    except ValueError:
        return None
    picks = raw.get("picks") if isinstance(raw, dict) else None
    if not isinstance(picks, list):
        return None
    allowed = set(pool_nums)
    seen: set[int] = set()
    out: list[AiPick] = []
    for p in picks:
        if not isinstance(p, dict):
            continue
        n = p.get("n")
        if isinstance(n, bool) or not isinstance(n, int) or n not in allowed or n in seen:
            continue
        seen.add(n)
        out.append(AiPick(n, sanitize_reason(p.get("r"))))
        if len(out) >= AI_PICK_MAX:
            break
    return out if len(out) >= AI_PICK_MIN else None


def merge_ai(results: Sequence[Sequence[AiPick]], quality: Mapping[int, float] | None = None) -> list[AiPick]:
    """엔진별 순위를 득표 `Σ(9 - 순위)` 로 합산 (두 엔진 모두 고른 문제 우선, 동점은 quality). 이유는 앞선 엔진(Codex) 우선, 없으면 다음 엔진."""
    votes: dict[int, int] = defaultdict(int)
    reasons: dict[int, str | None] = {}
    for res in results:
        for rank, p in enumerate(res, 1):
            votes[p.num] += max(0, AI_PICK_MAX + 1 - rank)
            if reasons.get(p.num) is None:
                reasons[p.num] = p.reason
    q = quality or {}
    order = sorted(votes, key=lambda n: (-votes[n], -q.get(n, 0.0), n))
    return [AiPick(n, reasons.get(n)) for n in order[:AI_PICK_MAX]]
