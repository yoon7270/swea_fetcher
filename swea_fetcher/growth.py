"""성장 기록 (M19): 이벤트 로그, 주간 통계·판정, 스냅샷, 팁, 코멘트 payload. 순수 (Qt·네트워크·AI 호출 없음).

- 저장 위치는 `{config_dir}/coach/profile/` (events.jsonl, weeks/{월요일}.json, state.json). 루트 폴더 안이면 쓰기를 거부한다.
  코드·지문·제목·응답 원문은 어디에도 저장하지 않는다 (문제 번호·주제 폴더명은 로컬 표시용, AI 로는 보내지 않는다).
- 모든 저장 함수는 예외를 던지지 않고 로그만 남긴다 (부가 기능이 제출·코치 흐름을 깨면 안 됨).
- 시각은 `now` 인자로 주입할 수 있다. 인자가 없으면 `growth.now()` (테스트가 monkeypatch 하는 지점).
- 좋아졌는지의 판정은 이 모듈의 규칙(THRESH)이 하고, AI 는 그 결과를 해설만 한다.
- service 를 import 하지 않는다 (순환 방지). 동의·엔진 호출 같은 오케스트레이션은 service.generate_growth 가 한다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from . import coach, growth_tags
from .config import COACH_DIR_NAME, Settings
from .growth_tags import Parsed, Tag

log = logging.getLogger("swea_fetcher.growth")

PROFILE_DIR_NAME = "profile"
EVENTS_FILE = "events.jsonl"
WEEKS_DIR = "weeks"
STATE_FILE = "state.json"
EVENT_VERSION = 1
SNAPSHOT_VERSION = 1

EVENT_KEEP_DAYS = 120
EVENT_MAX_BYTES = 2 * 1024 * 1024
EVENT_MAX_LINES = 5000
SNAPSHOT_KEEP = 52
BUILD_WEEKS = 12  # 이 기간보다 오래된 주는 스냅샷을 새로 만들지 않는다
PREV_MAX_DAYS = 35  # 비교 기준 주는 5주 이내
LOW_DATA_EVENTS = 3  # 이벤트가 이보다 적은 주는 AI 코멘트 생략
COMMENT_MAX_AGE_DAYS = 14
COMMENT_MAX_ATTEMPTS = 2
COMMENT_MAX_CHARS = 1200
CHART_WEEKS = 8
TIP_COOLDOWN_DAYS = 7
TIP_WINDOW_DAYS = 35

# 판정 임계값 (초기 추정치 — 실사용 뒤 이 한 곳만 조정한다). 임계 "정확히" 는 포함.
THRESH = {
    "first_try_delta": 0.15,  # 첫 시도 Pass 비율 변화폭
    "avg_wrong_delta": 0.5,  # Pass 전 평균 오답 변화폭
    "timeout_delta": 0.10,  # 시간초과 비중 변화폭
    "solved_delta": 2,  # 푼 문제 수 증가
    "category_delta": 0.25,  # 약점·강점 비율 변화폭
    "min_passes": 3,  # first_try / avg_wrong 비교 표본 (두 주 모두)
    "min_submits": 5,  # timeout_share 비교 표본 (두 주 모두)
    "min_tagged": 3,  # 카테고리 비교 표본 (두 주 모두)
    "weak_prev_min": 2,  # 약점 비교: 이전 주 점수 하한
    "cur_min": 2,  # 약점 악화·강점 성장: 이번 주 점수 하한
    "persistent_weeks": 3,
    "persistent_min": 2,
}
_EPS = 1e-9
MAX_IMPROVED, MAX_WATCH, MAX_PERSISTENT = 3, 2, 2

COMMENT_STATUSES = ("pending", "ok", "failed", "skipped_low_data", "skipped_backlog")

_LOCK = threading.RLock()  # 두 엔진 스레드·워커가 같은 파일에 쓴다
_WEEK_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")



def _i_ga(word: str) -> str:
    """주격 조사: 마지막 글자에 받침이 있으면 "이", 없으면 "가" (한글이 아니면 "이(가)")."""
    ch = word.rstrip("'\" )")[-1:] if word else ""
    if not ("가" <= ch <= "힣"):
        return "이(가)"
    return "이" if (ord(ch) - 0xAC00) % 28 else "가"

def now() -> datetime:
    """현재 시각 (테스트가 monkeypatch 하는 지점)."""
    return datetime.now()


def _now(value: datetime | None) -> datetime:
    return value or now()


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


# --- 경로 / 저장 ----------------------------------------------------------------------------


def profile_dir(settings: Settings) -> Path:
    return settings.coach_dir / PROFILE_DIR_NAME


def _writable(settings: Settings) -> bool:
    if coach._inside(profile_dir(settings), settings.root):
        log.warning("성장 기록 위치가 루트 폴더 안이라 기록하지 않습니다: %s", profile_dir(settings))
        return False
    return True


def _events_path(settings: Settings) -> Path:
    return profile_dir(settings) / EVENTS_FILE


def _weeks_dir(settings: Settings) -> Path:
    return profile_dir(settings) / WEEKS_DIR


def _state_path(settings: Settings) -> Path:
    return profile_dir(settings) / STATE_FILE


# --- 주 경계 --------------------------------------------------------------------------------


def week_start(d: date | datetime) -> date:
    """그 날이 속한 주의 월요일 (로컬 날짜). 월요일 00:00 이 새 주의 시작."""
    day = d.date() if isinstance(d, datetime) else d
    return day - timedelta(days=day.weekday())


def week_end(start: date) -> date:
    return start + timedelta(days=6)


def _valid_week_name(name: str) -> date | None:
    """파일명(YYYY-MM-DD) 검증 + 실제 월요일인지. 아니면 None (경로 조작 방지)."""
    if not _WEEK_FILE_RE.match(name):
        return None
    try:
        d = date.fromisoformat(name)
    except ValueError:
        return None
    return d if d.weekday() == 0 else None


# --- 이벤트 ---------------------------------------------------------------------------------


@dataclass
class Event:
    t: str  # "submit" | "coach"
    at: datetime
    num: int = 0
    topic: str = ""
    res: str = ""  # submit: pass | wrong | timeout | runtime_error
    wb: int = 0  # submit: 이번 제출 직전의 오답 누적
    k: str = ""  # coach: review | hint | solution
    lv: int = 0  # coach: 힌트 단계 (그 외 0)
    eng: str = ""
    ok: bool = False  # coach: 태그 파싱 성공
    tags: tuple[Tag, ...] = ()


def _append_line(settings: Settings, record: dict) -> bool:
    if not _writable(settings):
        return False
    path = _events_path(settings)
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            _trim_events(path)
    except OSError as e:
        log.warning("성장 기록 저장 실패: %s", e)
        return False
    return True


def _trim_events(path: Path) -> None:
    """파일이 2MB 또는 5,000줄을 넘으면 120일 지난 이벤트를 걷어낸다 (tmp + os.replace)."""
    size = path.stat().st_size
    if size < 256 * 1024:  # 줄 수를 세기엔 작다 (한 줄 ~200B → 5,000줄 ≈ 1MB)
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if size <= EVENT_MAX_BYTES and len(lines) <= EVENT_MAX_LINES:
        return
    cutoff = now() - timedelta(days=EVENT_KEEP_DAYS)
    kept = []
    for ln in lines:
        ev = _parse_event_line(ln)
        if ev is not None and ev.at >= cutoff:  # 손상된 줄도 이때 함께 정리된다
            kept.append(ln)
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(ln + "\n" for ln in kept), encoding="utf-8")
    os.replace(tmp, path)


def record_submit(settings: Settings, num: int, topic: str, res: str, wb: int = 0, *, at: datetime | None = None) -> bool:
    """SWEA 채점이 끝난 제출 1건. wb = 이번 제출 직전의 오답 누적. 실패해도 예외 없음."""
    try:
        return _append_line(
            settings,
            {"v": EVENT_VERSION, "t": "submit", "at": _iso(_now(at)), "num": int(num), "topic": str(topic or ""), "res": str(res), "wb": max(0, int(wb))},
        )
    except Exception as e:  # noqa: BLE001 — 부가 기능은 제출 흐름을 깨지 않는다
        log.warning("성장 기록 실패: %s", e)
        return False


def record_coach(
    settings: Settings,
    num: int,
    topic: str,
    kind: str,
    level: int,
    engine_key: str,
    parsed: Parsed | None,
    *,
    at: datetime | None = None,
) -> bool:
    """AI 코치 응답 1건 (새로 받은 것만 — 캐시 적중은 호출하지 않는다). parsed 가 None 이면 ok=false, 태그 없음."""
    try:
        record = {
            "v": EVENT_VERSION, "t": "coach", "at": _iso(_now(at)), "num": int(num), "topic": str(topic or ""),
            "k": str(kind), "lv": int(level) if kind == "hint" else 0, "eng": str(engine_key), "ok": parsed is not None,
            "tg": [t.to_dict() for t in parsed.tags] if parsed is not None else [],
        }
        return _append_line(settings, record)
    except Exception as e:  # noqa: BLE001
        log.warning("성장 기록 실패: %s", e)
        return False


def _parse_event_line(line: str) -> Event | None:
    """한 줄 → Event. 손상되었거나 알 수 없는 v/t 면 None."""
    try:
        raw = json.loads(line)
        if not isinstance(raw, dict) or raw.get("v") != EVENT_VERSION:
            return None
        at = datetime.fromisoformat(str(raw["at"]))
        if raw.get("t") == "submit":
            res = str(raw.get("res") or "")
            if res not in ("pass", "wrong", "timeout", "runtime_error"):
                return None
            return Event("submit", at, int(raw.get("num") or 0), str(raw.get("topic") or ""), res=res, wb=max(0, int(raw.get("wb") or 0)))
        if raw.get("t") == "coach":
            kind = str(raw.get("k") or "")
            if kind not in ("review", "hint", "solution"):
                return None
            tags = []
            for item in raw.get("tg") or []:
                if isinstance(item, dict) and growth_tags.name_of(str(item.get("c"))) and item.get("k") in ("weak", "strong"):
                    tags.append(Tag(str(item["c"]), str(item["k"]), max(1, min(3, int(item.get("s") or 1)))))
            return Event(
                "coach", at, int(raw.get("num") or 0), str(raw.get("topic") or ""), k=kind, lv=int(raw.get("lv") or 0),
                eng=str(raw.get("eng") or ""), ok=bool(raw.get("ok")), tags=tuple(tags),
            )
    except (ValueError, TypeError, KeyError, OverflowError):
        return None
    return None


def read_events(settings: Settings) -> list[Event]:
    """이벤트 전부 (파일 순서). 손상된 줄은 건너뛴다 (파일 전체를 버리지 않음)."""
    path = _events_path(settings)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    except OSError as e:
        log.warning("성장 기록을 읽지 못했습니다: %s", e)
        return []
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        ev = _parse_event_line(line)
        if ev is None:
            log.debug("성장 기록 %d번째 줄 무시", n)
            continue
        out.append(ev)
    return out


# --- 주 통계 --------------------------------------------------------------------------------


@dataclass
class CoachGroup:
    """같은 (문제, 종류, 단계) 코치 이벤트를 1건으로 합친 것 (재요청·두 엔진 중복 집계 방지)."""

    num: int
    k: str
    lv: int
    at: datetime  # 그룹 안의 가장 늦은 시각
    ok: bool = False  # 하나라도 파싱에 성공했으면
    tags: dict[tuple[str, str], int] = field(default_factory=dict)  # (c, k) → 강도 최댓값


def group_coach(events: list[Event]) -> list[CoachGroup]:
    groups: dict[tuple[int, str, int], CoachGroup] = {}
    for ev in events:
        if ev.t != "coach":
            continue
        g = groups.setdefault((ev.num, ev.k, ev.lv), CoachGroup(ev.num, ev.k, ev.lv, ev.at))
        g.at = max(g.at, ev.at)
        if ev.ok:
            g.ok = True
            for tag in ev.tags:
                key = (tag.c, tag.k)
                g.tags[key] = max(g.tags.get(key, 0), tag.s)
    return sorted(groups.values(), key=lambda g: g.at)


@dataclass
class WeekStats:
    submits: int = 0
    passes: int = 0
    solved: int = 0  # Pass 한 서로 다른 문제 수
    wrong: int = 0  # Pass 가 아닌 제출 (오답·시간초과·런타임 에러)
    timeouts: int = 0
    runtime_errors: int = 0
    first_try: int = 0  # 직전 오답 없이 Pass
    avg_wrong_before_pass: float | None = None
    hints: int = 0
    reviews: int = 0
    solutions: int = 0
    tagged: int = 0  # 태그 파싱에 성공한 응답(그룹) 수
    weak: dict[str, int] = field(default_factory=dict)
    strong: dict[str, int] = field(default_factory=dict)
    events: int = 0  # submit + 그룹화된 coach 수 (표본 판단용)

    @property
    def first_try_rate(self) -> float | None:
        return self.first_try / self.passes if self.passes else None

    @property
    def timeout_share(self) -> float | None:
        return self.timeouts / self.submits if self.submits else None

    def weak_rate(self, cid: str) -> float | None:
        return self.weak.get(cid, 0) / self.tagged if self.tagged else None

    def strong_rate(self, cid: str) -> float | None:
        return self.strong.get(cid, 0) / self.tagged if self.tagged else None

    def to_dict(self) -> dict:
        return {
            "submits": self.submits, "passes": self.passes, "solved": self.solved, "wrong": self.wrong, "timeouts": self.timeouts,
            "runtime_errors": self.runtime_errors, "first_try": self.first_try, "avg_wrong_before_pass": self.avg_wrong_before_pass,
            "hints": self.hints, "reviews": self.reviews, "solutions": self.solutions, "tagged": self.tagged,
            "weak": dict(self.weak), "strong": dict(self.strong), "events": self.events,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "WeekStats":
        def num(key: str) -> int:
            return max(0, int(raw.get(key) or 0))

        def cats(key: str) -> dict[str, int]:
            v = raw.get(key)
            return {str(c): max(0, int(n)) for c, n in v.items() if growth_tags.name_of(str(c))} if isinstance(v, dict) else {}

        avg = raw.get("avg_wrong_before_pass")
        return cls(
            num("submits"), num("passes"), num("solved"), num("wrong"), num("timeouts"), num("runtime_errors"), num("first_try"),
            float(avg) if isinstance(avg, (int, float)) and not isinstance(avg, bool) else None,
            num("hints"), num("reviews"), num("solutions"), num("tagged"), cats("weak"), cats("strong"), num("events"),
        )


def compute_stats(events: list[Event]) -> WeekStats:
    """한 주(또는 임의 구간)의 이벤트 → 통계. coach 이벤트는 (문제, 종류, 단계) 그룹으로 합친다 (G4)."""
    st = WeekStats()
    solved: set[int] = set()
    wb_sum = 0
    for ev in events:
        if ev.t != "submit":
            continue
        st.submits += 1
        if ev.res == "pass":
            st.passes += 1
            solved.add(ev.num)
            wb_sum += ev.wb
            if ev.wb == 0:
                st.first_try += 1
        else:
            st.wrong += 1
            if ev.res == "timeout":
                st.timeouts += 1
            elif ev.res == "runtime_error":
                st.runtime_errors += 1
    st.solved = len(solved)
    st.avg_wrong_before_pass = wb_sum / st.passes if st.passes else None
    groups = group_coach(events)
    for g in groups:
        if g.k == "hint":
            st.hints += 1
        elif g.k == "review":
            st.reviews += 1
        else:
            st.solutions += 1
        if g.ok:
            st.tagged += 1
            for (cid, kind), s in g.tags.items():
                target = st.weak if kind == "weak" else st.strong
                target[cid] = target.get(cid, 0) + s
    st.events = st.submits + len(groups)
    return st


# --- 판정 -----------------------------------------------------------------------------------


@dataclass
class Judgment:
    kind: str  # improved | watch | strength | activity | persistent
    key: str  # first_try_rate | avg_wrong_before_pass | timeout_share | solved | weak:{id} | strong:{id}
    cur: float
    prev: float | None
    text: str
    score: float = 0.0  # 정규화 변화량 (정렬용, 저장하지 않음)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "key": self.key, "cur": self.cur, "prev": self.prev, "text": self.text}

    @classmethod
    def from_dict(cls, raw: dict) -> "Judgment":
        prev = raw.get("prev")
        return cls(str(raw["kind"]), str(raw["key"]), float(raw["cur"]), float(prev) if prev is not None else None, str(raw["text"]))


GOOD_KINDS = ("improved", "strength", "activity")


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _ge(delta: float, thr: float) -> bool:
    return delta >= thr - _EPS


def pick_prev(start: date, history: dict[date, WeekStats]) -> date | None:
    """비교 기준 주: 이번 주 이전 스냅샷 중 가장 최근 것, 단 5주 이내 (이벤트 없는 주는 건너뛴다)."""
    older = [w for w in history if w < start and (start - w).days <= PREV_MAX_DAYS]
    return max(older) if older else None


def evaluate(start: date, cur: WeekStats, history: dict[date, WeekStats]) -> tuple[date | None, list[Judgment]]:
    """이번 주 통계를 기준 주와 비교해 (기준 주, 판정 목록). 표본 조건 미달 항목은 조용히 생략한다."""
    t = THRESH
    out: list[Judgment] = []
    prev_start = pick_prev(start, history)
    if prev_start is not None:
        prev = history[prev_start]
        # 첫 시도 Pass 비율
        if cur.passes >= t["min_passes"] and prev.passes >= t["min_passes"]:
            c, p = cur.first_try_rate, prev.first_try_rate
            d = c - p
            if _ge(d, t["first_try_delta"]):
                out.append(Judgment("improved", "first_try_rate", c, p, f"첫 시도 Pass 비율이 {_pct(p)} → {_pct(c)} 로 올랐어요", d / t["first_try_delta"]))
            elif _ge(-d, t["first_try_delta"]):
                out.append(Judgment("watch", "first_try_rate", c, p, f"첫 시도 Pass 비율이 {_pct(p)} → {_pct(c)} 로 낮아졌어요", -d / t["first_try_delta"]))
            # Pass 전 평균 오답
            c, p = cur.avg_wrong_before_pass, prev.avg_wrong_before_pass
            d = c - p
            if _ge(-d, t["avg_wrong_delta"]):
                out.append(Judgment("improved", "avg_wrong_before_pass", c, p, f"Pass 하기 전 평균 오답이 {p:.1f}회 → {c:.1f}회 로 줄었어요", -d / t["avg_wrong_delta"]))
            elif _ge(d, t["avg_wrong_delta"]):
                out.append(Judgment("watch", "avg_wrong_before_pass", c, p, f"Pass 하기 전 평균 오답이 {p:.1f}회 → {c:.1f}회 로 늘었어요", d / t["avg_wrong_delta"]))
        # 시간초과 비중
        if cur.submits >= t["min_submits"] and prev.submits >= t["min_submits"]:
            c, p = cur.timeout_share, prev.timeout_share
            d = c - p
            if _ge(-d, t["timeout_delta"]):
                out.append(Judgment("improved", "timeout_share", c, p, f"시간초과 비중이 {_pct(p)} → {_pct(c)} 로 줄었어요", -d / t["timeout_delta"]))
            elif _ge(d, t["timeout_delta"]):
                out.append(Judgment("watch", "timeout_share", c, p, f"시간초과 비중이 {_pct(p)} → {_pct(c)} 로 늘었어요", d / t["timeout_delta"]))
        # 푼 문제 수 (꾸준함)
        if cur.solved - prev.solved >= t["solved_delta"]:
            out.append(Judgment("activity", "solved", cur.solved, prev.solved, f"푼 문제가 {prev.solved}개 → {cur.solved}개 로 늘었어요 (꾸준함)", (cur.solved - prev.solved) / t["solved_delta"]))
        # 약점·강점 카테고리
        if cur.tagged >= t["min_tagged"] and prev.tagged >= t["min_tagged"]:
            for cid in growth_tags.CATEGORY_IDS:
                name = growth_tags.name_of(cid)
                wp, wc = prev.weak.get(cid, 0), cur.weak.get(cid, 0)
                if wp >= t["weak_prev_min"]:
                    d = cur.weak_rate(cid) - prev.weak_rate(cid)
                    if _ge(-d, t["category_delta"]):
                        out.append(Judgment("improved", f"weak:{cid}", cur.weak_rate(cid), prev.weak_rate(cid),
                                            f"'{name}' 지적 강도가 응답당 {prev.weak_rate(cid):.1f} → {cur.weak_rate(cid):.1f} 로 줄었어요 (약점 완화)", -d / t["category_delta"]))
                    elif _ge(d, t["category_delta"]) and wc >= t["cur_min"]:
                        out.append(Judgment("watch", f"weak:{cid}", cur.weak_rate(cid), prev.weak_rate(cid),
                                            f"'{name}' 지적 강도가 응답당 {prev.weak_rate(cid):.1f} → {cur.weak_rate(cid):.1f} 로 늘었어요", d / t["category_delta"]))
                sp, sc = prev.strong.get(cid, 0), cur.strong.get(cid, 0)
                if sc >= t["cur_min"]:
                    d = cur.strong_rate(cid) - prev.strong_rate(cid)
                    if sp == 0:
                        out.append(Judgment("strength", f"strong:{cid}", cur.strong_rate(cid), 0.0, f"새 강점 '{name}'{_i_ga(name)} 눈에 띄어요 (강점 성장)", cur.strong_rate(cid) / t["category_delta"]))
                    elif _ge(d, t["category_delta"]):
                        out.append(Judgment("strength", f"strong:{cid}", cur.strong_rate(cid), prev.strong_rate(cid),
                                            f"'{name}' 칭찬 강도가 응답당 {prev.strong_rate(cid):.1f} → {cur.strong_rate(cid):.1f} 로 늘었어요 (강점 성장)", d / t["category_delta"]))
    # 반복 약점: 달력상 연속한 주(스냅샷 + 이번 주)에서 점수 >= 2 가 3주 이상
    for cid in growth_tags.CATEGORY_IDS:
        if cur.weak.get(cid, 0) < t["persistent_min"]:
            continue
        run, d = 1, start - timedelta(days=7)
        while d in history and history[d].weak.get(cid, 0) >= t["persistent_min"]:
            run += 1
            d -= timedelta(days=7)
        if run >= t["persistent_weeks"]:
            out.append(Judgment("persistent", f"weak:{cid}", run, None, f"'{growth_tags.name_of(cid)}'{_i_ga(growth_tags.name_of(cid))} {run}주 연속 지적되고 있어요 (꾸준히 지적되는 약점)", float(run)))
    return prev_start, _limit(out)


def _limit(judgments: list[Judgment]) -> list[Judgment]:
    """좋아진 점 상위 3, 지켜볼 점 상위 2, 반복 약점 상위 2 (변화량 정규화 점수 내림차순)."""
    def top(kinds: tuple[str, ...], n: int) -> list[Judgment]:
        return sorted((j for j in judgments if j.kind in kinds), key=lambda j: -j.score)[:n]

    return top(GOOD_KINDS, MAX_IMPROVED) + top(("watch",), MAX_WATCH) + top(("persistent",), MAX_PERSISTENT)


FIRST_RECORD_TEXT = "첫 기록이에요. 다음 주부터 변화를 비교해 드려요"


def headline(judgments: list[Judgment], stats: WeekStats, baseline: bool) -> str:
    """리포트 머리글 한 줄. 부정적 어조 금지."""
    if not baseline:
        return FIRST_RECORD_TEXT
    good = [j for j in judgments if j.kind in GOOD_KINDS]
    if not good:
        return f"이번 주는 뚜렷한 변화가 없어요 (꾸준히 {stats.solved}문제 해결)"
    return f"좋아진 점이 {len(good)}가지 있어요"


# --- 스냅샷 ---------------------------------------------------------------------------------


@dataclass
class Snapshot:
    week_start: date
    generated_at: str
    stats: WeekStats
    prev_week: date | None = None
    judgments: list[Judgment] = field(default_factory=list)
    seen_at: str | None = None
    comment: dict | None = None  # {"text", "engine", "at"}
    comment_status: str = "pending"
    comment_attempts: int = 0

    @property
    def week_end(self) -> date:
        return week_end(self.week_start)

    def to_dict(self) -> dict:
        return {
            "v": SNAPSHOT_VERSION, "taxonomy": growth_tags.TAXONOMY_VERSION, "week_start": self.week_start.isoformat(),
            "week_end": self.week_end.isoformat(), "generated_at": self.generated_at, "seen_at": self.seen_at,
            "stats": self.stats.to_dict(), "prev_week": self.prev_week.isoformat() if self.prev_week else None,
            "judgments": [j.to_dict() for j in self.judgments], "comment": self.comment,
            "comment_status": self.comment_status, "comment_attempts": self.comment_attempts,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Snapshot":
        if raw.get("v") != SNAPSHOT_VERSION:
            raise ValueError("알 수 없는 스냅샷 버전")
        comment = raw.get("comment")
        if comment is not None and not (isinstance(comment, dict) and isinstance(comment.get("text"), str)):
            comment = None
        status = raw.get("comment_status")
        prev = raw.get("prev_week")
        return cls(
            date.fromisoformat(raw["week_start"]), str(raw.get("generated_at") or ""), WeekStats.from_dict(raw["stats"]),
            date.fromisoformat(prev) if prev else None, [Judgment.from_dict(j) for j in raw.get("judgments") or []],
            raw.get("seen_at") if isinstance(raw.get("seen_at"), str) else None, comment,
            status if status in COMMENT_STATUSES else "pending", max(0, int(raw.get("comment_attempts") or 0)),
        )


def _week_path(settings: Settings, start: date) -> Path | None:
    """스냅샷 파일 경로. 월요일 날짜가 아니면 None (경로 조작 방지)."""
    if _valid_week_name(start.isoformat()) is None:
        return None
    return _weeks_dir(settings) / f"{start.isoformat()}.json"


def load_snapshots(settings: Settings) -> dict[date, Snapshot]:
    """스냅샷 전부 (주 시작일 → Snapshot). 손상 파일은 .corrupt 로 이름을 바꾸고 무시한다."""
    d = _weeks_dir(settings)
    out: dict[date, Snapshot] = {}
    try:
        files = sorted(d.glob("*.json"))
    except OSError:
        return out
    for path in files:
        start = _valid_week_name(path.stem)
        if start is None:
            continue
        try:
            snap = Snapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if snap.week_start != start:
                raise ValueError("파일명과 주 시작일이 다릅니다")
            out[start] = snap
        except OSError as e:
            log.warning("성장 리포트를 읽지 못했습니다 (%s): %s", path.name, e)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            log.warning("성장 리포트가 손상되어 백업 후 무시합니다 (%s): %s", path.name, e)
            try:
                os.replace(path, path.with_name(path.name + ".corrupt"))
            except OSError:
                pass
    return out


def save_snapshot(settings: Settings, snap: Snapshot) -> bool:
    if not _writable(settings):
        return False
    path = _week_path(settings, snap.week_start)
    if path is None:
        return False
    try:
        with _LOCK:
            coach._atomic_write(path, snap.to_dict())
    except OSError as e:
        log.warning("성장 리포트 저장 실패: %s", e)
        return False
    return True


def _prune_snapshots(settings: Settings, snaps: dict[date, Snapshot]) -> None:
    for start in sorted(snaps)[: max(0, len(snaps) - SNAPSHOT_KEEP)]:
        path = _week_path(settings, start)
        try:
            if path is not None:
                path.unlink()
        except OSError:
            pass
        snaps.pop(start, None)


def _events_by_week(events: list[Event]) -> dict[date, list[Event]]:
    out: dict[date, list[Event]] = {}
    for ev in events:
        out.setdefault(week_start(ev.at), []).append(ev)
    return out


def missing_weeks(settings: Settings, at: datetime | None = None) -> list[date]:
    """확정 가능한데(지난 주, 12주 이내) 이벤트가 있고 스냅샷이 없는 주 (오래된 순)."""
    this_monday = week_start(_now(at))
    lo = this_monday - timedelta(days=7 * BUILD_WEEKS)
    have = load_snapshots(settings)
    return sorted(w for w in _events_by_week(read_events(settings)) if lo <= w < this_monday and w not in have)


def build_missing_snapshots(settings: Settings, at: datetime | None = None) -> list[date]:
    """확정 가능한 주 중 스냅샷이 없는 주를 오래된 순으로 만든다 (멱등: 기존 스냅샷은 그대로). 새로 만든 주 시작일 목록.

    코멘트 초기 상태: 이벤트 3건 미만 skipped_low_data, 밀린 주가 여러 개면 가장 최근 것만 pending 이고 나머지는 skipped_backlog.
    """
    stamp = _now(at)
    try:
        with _LOCK:
            if not _writable(settings):
                return []
            by_week = _events_by_week(read_events(settings))
            snaps = load_snapshots(settings)
            this_monday = week_start(stamp)
            lo = this_monday - timedelta(days=7 * BUILD_WEEKS)
            todo = sorted(w for w in by_week if lo <= w < this_monday and w not in snaps)
            history = {w: s.stats for w, s in snaps.items()}
            built: list[date] = []
            for i, w in enumerate(todo):
                stats = compute_stats(by_week[w])
                prev, judgments = evaluate(w, stats, history)
                if stats.events < LOW_DATA_EVENTS:
                    status = "skipped_low_data"
                else:
                    status = "pending" if i == len(todo) - 1 else "skipped_backlog"
                snap = Snapshot(w, _iso(stamp), stats, prev, judgments, comment_status=status)
                if save_snapshot(settings, snap):
                    snaps[w] = snap
                    history[w] = stats
                    built.append(w)
            if built:
                _prune_snapshots(settings, snaps)
            return built
    except Exception as e:  # noqa: BLE001
        log.warning("성장 리포트 생성 실패: %s", e)
        return []


def update_snapshot(settings: Settings, start: date, **changes) -> Snapshot | None:
    """확정된 스냅샷에서 바뀔 수 있는 필드(seen_at, comment*)만 갱신한다 (통계·판정은 불변, G8)."""
    allowed = {"seen_at", "comment", "comment_status", "comment_attempts"}
    if set(changes) - allowed:
        raise ValueError("스냅샷에서 바꿀 수 없는 필드입니다")
    with _LOCK:
        snap = load_snapshots(settings).get(start)
        if snap is None:
            return None
        for k, v in changes.items():
            setattr(snap, k, v)
        return snap if save_snapshot(settings, snap) else None


def mark_seen(settings: Settings, start: date, at: datetime | None = None) -> None:
    snap = load_snapshots(settings).get(start)
    if snap is not None and snap.seen_at is None:
        update_snapshot(settings, start, seen_at=_iso(_now(at)))


def unseen_count(settings: Settings) -> int:
    return sum(1 for s in load_snapshots(settings).values() if s.seen_at is None)


# --- 주간 코멘트 대상 -------------------------------------------------------------------------


def comment_candidate(snaps: dict[date, Snapshot], at: datetime, force_week: date | None = None) -> Snapshot | None:
    """AI 코멘트 대상 스냅샷. force_week 가 있으면 그 주 (나이·횟수 제한 무시, 표본 조건은 유지).

    자동: 가장 최근 스냅샷이 pending 이거나 (failed 이고 시도 < 2), 그 주의 마지막 날이 14일 이내.
    """
    if force_week is not None:
        snap = snaps.get(force_week)
        return snap if snap is not None and snap.stats.events >= LOW_DATA_EVENTS else None
    if not snaps:
        return None
    snap = snaps[max(snaps)]
    if snap.comment_status == "pending" or (snap.comment_status == "failed" and snap.comment_attempts < COMMENT_MAX_ATTEMPTS):
        if (at.date() - snap.week_end).days <= COMMENT_MAX_AGE_DAYS:
            return snap
    return None


def is_due(settings: Settings, at: datetime | None = None, *, comment: bool = True) -> bool:
    """만들 스냅샷 또는 자동 코멘트 후보가 있는가 (파일 확인만 — 틱용)."""
    stamp = _now(at)
    if missing_weeks(settings, stamp):
        return True
    return comment and comment_candidate(load_snapshots(settings), stamp) is not None


# --- 코멘트 payload · 후처리 ------------------------------------------------------------------


def _stats_payload(st: WeekStats) -> dict:
    """AI 로 보내도 되는 집계 숫자만 (허용 키 화이트리스트)."""
    return {
        "submits": st.submits, "passes": st.passes, "solved_problems": st.solved, "wrong_submits": st.wrong, "timeouts": st.timeouts,
        "runtime_errors": st.runtime_errors, "first_try_passes": st.first_try,
        "first_try_rate_percent": None if st.first_try_rate is None else round(st.first_try_rate * 100),
        "avg_wrong_before_pass": None if st.avg_wrong_before_pass is None else round(st.avg_wrong_before_pass, 1),
        "hints_used": st.hints, "code_reviews": st.reviews, "solution_views": st.solutions, "classified_answers": st.tagged,
    }


def _category_payload(scores: dict[str, int], st: WeekStats, weak: bool) -> list[dict]:
    rows = []
    for cid, score in sorted(scores.items(), key=lambda kv: -kv[1]):
        name = growth_tags.name_of(cid)
        if name and score > 0:
            rate = st.weak_rate(cid) if weak else st.strong_rate(cid)
            rows.append({"name": name, "score": score, "rate_percent": None if rate is None else round(rate * 100)})
    return rows[:5]


def comment_payload(snap: Snapshot, prev: Snapshot | None) -> dict:
    """주간 프롬프트에 넣는 dict. 허용 키로만 구성한다 — 코드·지문·문제 번호/제목·주제명·경로·ID 는 구조적으로 들어갈 수 없다."""
    by_kind: dict[str, list[str]] = {"improved": [], "strength": [], "activity": [], "watch": [], "persistent": []}
    for j in snap.judgments:
        by_kind.setdefault(j.kind, []).append(j.text)
    return {
        "period": f"{snap.week_start.isoformat()} ~ {snap.week_end.isoformat()}",
        "baseline": prev is not None,
        "current": _stats_payload(snap.stats),
        "previous": _stats_payload(prev.stats) if prev is not None else None,
        "weak_categories": _category_payload(snap.stats.weak, snap.stats, True),
        "strong_categories": _category_payload(snap.stats.strong, snap.stats, False),
        **by_kind,
    }


_FENCE_BLOCK_RE = re.compile(r"^[ \t]{0,3}(```|~~~).*?(?:^[ \t]{0,3}\1[ \t]*$|\Z)", re.S | re.M)
_LINK_RE = re.compile(r"!?\[([^\]\n]*)\]\([^)\n]*\)")
_URL_RE = re.compile(r"https?://\S+", re.I)


def clean_comment(text: str) -> str:
    """AI 코멘트 후처리: profile 블록·코드 펜스·링크 제거, 1,200자 절단. 결과가 비면 ""."""
    body, _ = growth_tags.extract(text or "", "weekly")
    body = _FENCE_BLOCK_RE.sub("", body)
    body = _LINK_RE.sub(lambda m: m.group(1), body)
    body = _URL_RE.sub("", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body[:COMMENT_MAX_CHARS].rstrip()


# --- 팁 (같은 약점 3번 연속) --------------------------------------------------------------------


def _load_state(settings: Settings) -> dict:
    try:
        raw = json.loads(_state_path(settings).read_text(encoding="utf-8"))
        tips = raw.get("tip_shown") if isinstance(raw, dict) else None
        return {"v": 1, "tip_shown": {str(k): str(v) for k, v in tips.items()} if isinstance(tips, dict) else {}}
    except (OSError, ValueError, AttributeError):
        return {"v": 1, "tip_shown": {}}  # 없거나 손상되면 빈 상태로 시작


def tip_text(cid: str) -> str | None:
    name, tip = growth_tags.name_of(cid), growth_tags.tip_of(cid)
    if name is None or tip is None:
        return None
    return f"성장 팁 · 최근 3번 연속 '{name}'{_i_ga(name)} 지적됐어요. {tip}"


def pending_tip(settings: Settings, at: datetime | None = None) -> str | None:
    """최근 5주 이내 ok 응답의 마지막 3개가 모두 같은 약점(강도 >= 2)을 포함하면 팁 문구 (7일 쿨다운, 반환 즉시 기록)."""
    stamp = _now(at)
    try:
        cutoff = stamp - timedelta(days=TIP_WINDOW_DAYS)
        groups = [g for g in group_coach([e for e in read_events(settings) if e.t == "coach" and e.at >= cutoff]) if g.ok]
        if len(groups) < 3:
            return None
        last = groups[-3:]
        state = _load_state(settings)
        for cid in growth_tags.CATEGORY_IDS:
            if not all(g.tags.get((cid, "weak"), 0) >= 2 for g in last):
                continue
            shown = state["tip_shown"].get(cid)
            try:
                if shown and stamp - datetime.fromisoformat(shown) < timedelta(days=TIP_COOLDOWN_DAYS):
                    continue
            except ValueError:
                pass
            text = tip_text(cid)
            if text is None:
                continue
            state["tip_shown"][cid] = _iso(stamp)
            if _writable(settings):
                try:
                    with _LOCK:
                        coach._atomic_write(_state_path(settings), state)
                except OSError as e:
                    log.warning("성장 팁 상태 저장 실패: %s", e)
            return text
    except Exception as e:  # noqa: BLE001
        log.warning("성장 팁 판정 실패: %s", e)
    return None


# --- 화면용 조회 (읽기 전용) --------------------------------------------------------------------


@dataclass
class WeekSummary:
    week_start: date
    week_end: date
    solved: int
    good_count: int  # 좋아진 점 수
    unseen: bool
    in_progress: bool
    comment_status: str = ""


@dataclass
class GrowthOverview:
    has_events: bool
    this_week: WeekSummary  # 진행 중인 이번 주
    weeks: list[WeekSummary]  # 확정 리포트 (최신순, 최대 52)
    series: list[tuple[date, int]]  # 최근 8주 Pass 문제 수 (이번 주 포함, 오래된 순)
    unseen: int


@dataclass
class GrowthReport:
    week_start: date
    week_end: date
    in_progress: bool
    confirmed: bool  # 저장된 스냅샷이 있는가
    stats: WeekStats
    prev_week: date | None
    prev_stats: WeekStats | None
    judgments: list[Judgment]
    headline: str
    comment: dict | None
    comment_status: str
    comment_attempts: int
    seen: bool
    chart_weeks: list[date]  # 선택 주에서 끝나는 8주 (오래된 순)
    chart_stats: list[WeekStats | None]  # 이벤트 없는 주는 None

    @property
    def baseline(self) -> bool:
        return self.prev_stats is not None

    def judgments_of(self, *kinds: str) -> list[Judgment]:
        return [j for j in self.judgments if j.kind in kinds]


def overview(settings: Settings, at: datetime | None = None) -> GrowthOverview:
    stamp = _now(at)
    events = read_events(settings)
    snaps = load_snapshots(settings)
    this_monday = week_start(stamp)
    by_week = _events_by_week(events)
    live = compute_stats(by_week.get(this_monday, []))
    _prev, live_judgments = evaluate(this_monday, live, {w: s.stats for w, s in snaps.items()})
    this_week = WeekSummary(this_monday, week_end(this_monday), live.solved, len([j for j in live_judgments if j.kind in GOOD_KINDS]), False, True)
    weeks = [
        WeekSummary(s.week_start, s.week_end, s.stats.solved, len([j for j in s.judgments if j.kind in GOOD_KINDS]), s.seen_at is None, False, s.comment_status)
        for s in sorted(snaps.values(), key=lambda s: s.week_start, reverse=True)
    ]
    series = []
    for i in range(CHART_WEEKS - 1, -1, -1):
        w = this_monday - timedelta(days=7 * i)
        series.append((w, live.solved if w == this_monday else (snaps[w].stats.solved if w in snaps else compute_stats(by_week.get(w, [])).solved)))
    return GrowthOverview(bool(events) or bool(snaps), this_week, weeks, series, sum(1 for w in weeks if w.unseen))


def report(settings: Settings, start: date, at: datetime | None = None) -> GrowthReport:
    """한 주의 리포트. 확정 스냅샷이 있으면 그것(불변), 이번 주(진행 중)나 스냅샷이 없는 주는 이벤트에서 즉석 계산."""
    stamp = _now(at)
    start = week_start(start)
    snaps = load_snapshots(settings)
    by_week = _events_by_week(read_events(settings))
    history = {w: s.stats for w, s in snaps.items()}
    this_monday = week_start(stamp)
    snap = snaps.get(start)
    if snap is not None:
        stats, prev_week, judgments = snap.stats, snap.prev_week, snap.judgments
        comment, status, attempts, seen = snap.comment, snap.comment_status, snap.comment_attempts, snap.seen_at is not None
    else:
        stats = compute_stats(by_week.get(start, []))
        prev_week, judgments = evaluate(start, stats, history)
        comment, status, attempts, seen = None, "pending", 0, True
    prev_stats = history.get(prev_week) if prev_week else None
    baseline = prev_stats is not None
    chart_weeks = [start - timedelta(days=7 * i) for i in range(CHART_WEEKS - 1, -1, -1)]
    chart_stats: list[WeekStats | None] = []
    for w in chart_weeks:
        if w == start:
            chart_stats.append(stats)
        elif w in history:
            chart_stats.append(history[w])
        elif w in by_week and w <= this_monday:
            chart_stats.append(compute_stats(by_week[w]))
        else:
            chart_stats.append(None)
    return GrowthReport(
        start, week_end(start), start >= this_monday, snap is not None, stats, prev_week, prev_stats, judgments,
        headline(judgments, stats, baseline), comment, status, attempts, seen, chart_weeks, chart_stats,
    )


# --- 화면용 행 (지표·카테고리) -------------------------------------------------------------------


@dataclass
class MetricRow:
    key: str
    label: str
    value: str
    change: str  # "▲ 좋아짐 · 지난 기록 대비 +20%p" 등 (글자 병기)
    direction: str  # better | worse | same | na
    series: list[float | None]
    invert: bool = False  # 낮을수록 좋은 지표


@dataclass
class CategoryRow:
    cid: str
    name: str
    score: int
    rate: float | None
    value: str
    change: str
    direction: str
    series: list[float | None]


_DIR_TEXT = {"better": "▲ 좋아짐", "worse": "▼ 지켜볼 점"}


def _change_text(direction: str, detail: str) -> str:
    head = _DIR_TEXT.get(direction)
    return f"{head} · {detail}" if head else detail


def _signed(x: float, unit: str, digits: int = 0) -> str:
    return f"{x:+.{digits}f}{unit}"


def metric_rows(rep: GrowthReport) -> list[MetricRow]:
    """성장 탭 "이번 주 숫자" 5행. 좋아짐/지켜볼 점은 판정과 같은 임계·표본 조건으로만 표시한다."""
    cur, prev, t = rep.stats, rep.prev_stats, THRESH
    stats = rep.chart_stats

    def series(fn) -> list[float | None]:
        return [None if s is None else fn(s) for s in stats]

    def compare(c, p, unit, digits, scale, thr, lower_better, enough) -> tuple[str, str]:
        if prev is None or c is None or p is None:
            return "na", "비교 불가"
        d = (c - p) * scale
        if not enough:
            return "na", f"지난 기록 대비 {_signed(d, unit, digits)} (표본이 적어 판정 안 함)" if abs(d) > _EPS else "변화 없음"
        good = _ge(-d if lower_better else d, thr * scale)
        bad = _ge(d if lower_better else -d, thr * scale)
        direction = "better" if good else "worse" if bad else "same"
        detail = "변화 없음" if abs(d) < _EPS else f"지난 기록 대비 {_signed(d, unit, digits)}"
        return direction, _change_text(direction, detail)

    rows: list[MetricRow] = []
    d, txt = compare(cur.solved, prev.solved if prev else None, "문제", 0, 1, t["solved_delta"], False, True)
    if d == "worse":  # 푼 문제 수 감소는 "지켜볼 점" 으로 세지 않는다 (판정표에 없음)
        d, txt = "same", txt.replace(_DIR_TEXT["worse"] + " · ", "")
    rows.append(MetricRow("solved", "Pass 문제", f"{cur.solved}문제", txt, d, series(lambda s: float(s.solved))))
    ft = cur.first_try_rate
    enough = prev is not None and cur.passes >= t["min_passes"] and prev.passes >= t["min_passes"]
    d, txt = compare(ft, prev.first_try_rate if prev else None, "%p", 0, 100, t["first_try_delta"], False, enough)
    rows.append(MetricRow("first_try_rate", "첫 시도 Pass 비율", "-" if ft is None else _pct(ft), txt, d, series(lambda s: s.first_try_rate)))
    aw = cur.avg_wrong_before_pass
    d, txt = compare(aw, prev.avg_wrong_before_pass if prev else None, "회", 1, 1, t["avg_wrong_delta"], True, enough)
    rows.append(MetricRow("avg_wrong_before_pass", "Pass 전 평균 오답", "-" if aw is None else f"{aw:.1f}회", txt, d, series(lambda s: s.avg_wrong_before_pass), True))
    ts = cur.timeout_share
    enough = prev is not None and cur.submits >= t["min_submits"] and prev.submits >= t["min_submits"]
    d, txt = compare(ts, prev.timeout_share if prev else None, "%p", 0, 100, t["timeout_delta"], True, enough)
    rows.append(MetricRow("timeout_share", "시간초과 비중", "-" if ts is None else _pct(ts), txt, d, series(lambda s: s.timeout_share), True))
    used = cur.hints + cur.solutions
    if prev is None:
        assist = "비교 불가"
    else:
        diff = used - (prev.hints + prev.solutions)
        assist = "변화 없음" if diff == 0 else f"지난 기록 대비 {diff:+d}회"
    rows.append(MetricRow("assist", "힌트·정답 풀이 사용", f"힌트 {cur.hints} · 정답 풀이 {cur.solutions}", assist, "na", series(lambda s: float(s.hints + s.solutions)), True))
    return rows


def category_rows(rep: GrowthReport, weak: bool, limit: int = 5) -> list[CategoryRow]:
    """약점(weak=True) 또는 강점 행. 이번 주 점수가 큰 순, 최대 limit 개. 알 수 없는 id 는 숨긴다."""
    cur, prev, t = rep.stats, rep.prev_stats, THRESH
    scores = cur.weak if weak else cur.strong
    good_key = f"{'weak' if weak else 'strong'}:"
    judged = {j.key: j for j in rep.judgments if j.key.startswith(good_key)}
    rows = []
    for cid, score in sorted(scores.items(), key=lambda kv: (-kv[1], growth_tags.CATEGORY_IDS.index(kv[0]))):
        name = growth_tags.name_of(cid)
        if not name or score <= 0:
            continue
        rate = cur.weak_rate(cid) if weak else cur.strong_rate(cid)
        prate = (prev.weak_rate(cid) if weak else prev.strong_rate(cid)) if prev is not None else None
        judgment = judged.get(f"{good_key}{cid}")
        if prev is None or rate is None or prate is None:
            direction, change = "na", "비교 불가"
        else:
            delta = rate - prate  # 응답당 평균 강도의 변화
            direction = "same"
            if judgment is not None:
                direction = "better" if judgment.kind in GOOD_KINDS else "worse"
            detail = "변화 없음" if abs(delta) < _EPS else f"지난 기록 대비 {_signed(delta, '', 2)}"
            change = _change_text(direction, detail)
        series = [None if s is None else (s.weak_rate(cid) if weak else s.strong_rate(cid)) for s in rep.chart_stats]
        rows.append(CategoryRow(cid, name, score, rate, f"점수 {score} · 분류 {cur.tagged}건 중", change, direction, series))
    return rows[:limit]


# --- 삭제 -----------------------------------------------------------------------------------


def clear(config_dir: Path) -> int:
    """`coach/profile/` 만 삭제 ([성장 기록 지우기]). 지운 파일 수."""
    d = Path(config_dir) / COACH_DIR_NAME / PROFILE_DIR_NAME
    if not d.is_dir():
        return 0
    n = sum(1 for p in d.rglob("*") if p.is_file())
    shutil.rmtree(d, ignore_errors=True)
    return n
