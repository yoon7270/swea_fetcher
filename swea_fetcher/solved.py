"""풀이 잔디 (M20): 하루에 Pass 한 문제 기록 + 집계 + 색 단계 계산. 순수 (Qt·네트워크·AI 호출 없음).

- "Pass 한 문제" = 앱으로 SWEA 제출 Pass(via="swea") + 로컬 검증 통과(via="local", 샘플 출력 일치). 같은 날 같은 문제는 1건. 날짜는 로컬 날짜.
  로컬 통과는 잠정 기록이다: SWEA 가 그 문제를 Pass 가 아닌 결과로 채점하면 그 문제의 로컬 기록을 걷어내고(retract_local),
  마지막 SWEA 채점이 Pass 가 아닌 문제의 로컬 기록은 표시하지 않는다 (샘플만 맞고 SWEA 에서 틀린 문제가 "해결"로 세지지 않게).
- 저장 위치는 `{config_dir}/coach/profile/solved.json` — 성장 기록과 같은 폴더라 [성장 기록 지우기]·[AI 기록 지우기]·`logout --all` 이 함께 지운다.
  루트 폴더 안이면 쓰기를 거부한다 (GitHub 로 올라가지 않게). 코드·지문 원문은 저장하지 않는다 (번호·주제·제목·방식·시각만).
- 400일 넘은 날은 저장할 때 걷어낸다 (1년 표시 + 여유).
- 모든 저장 함수는 예외를 던지지 않고 로그만 남긴다 (부가 기능이 제출·검증 흐름을 깨면 안 됨).
- 백필: 첫 로드 때 기존 기록(growth events 의 submit pass 120일, coach records 의 마지막 Pass)에서 채운다. 로컬 검증은 과거 기록이 없어 불가.
  백필 완료 표식은 `coach/solved_backfilled` — [성장 기록 지우기] 뒤에 같은 기록이 되살아나지 않게 profile/ 밖에 둔다.
- 기기 간 동기화(M23): 켜져 있으면 기록을 `{root}/.swea-fetch/solved/{device_id}.json` 에도 쓰고, load 는 다른 기기 기록과 합쳐 본다 (solved_sync.py).
  이때 "루트 폴더 안이면 쓰기 거부" 규칙은 로컬 solved.json 에만 적용된다 (기기 파일은 의도적으로 루트 안).
- growth 를 import 한다 (경로·시각·락 재사용). service 를 import 하지 않는다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import coach, growth
from .config import Settings

log = logging.getLogger("swea_fetcher.solved")

SOLVED_FILE = "solved.json"
BACKFILL_MARK = "solved_backfilled"
SOLVED_VERSION = 1
KEEP_DAYS = 400
VIA = ("swea", "local")
VIA_LABEL = {"swea": "SWEA", "local": "로컬"}

# 칸 농도: 하루 Pass 수 → 1~4단계. 하루에 5문제 넘게 푸는 사람은 드물어서 GitHub 식 분포 기반보다 고정 임계값이 보람이 크다 (1 / 2 / 3 / 4+)
HEAT_STEPS = (1, 2, 3, 4)
# 기준색(4단계)을 배경 쪽으로 섞는 비율 (1~4단계). 4단계 = 기준색 그대로
HEAT_MIX = (0.35, 0.65, 1.0)  # 1~3단계: 배경 → 기준색. 4단계는 기준색을 배경 반대쪽으로 더 민다 (heat_colors)
HEAT_MIX_DARK = (0.45, 0.72, 1.0)  # 다크: 어두운 바닥에서 1단계가 0단계(surface_alt)와 구분되도록 비율을 올린다 (스펙 §17.10)
HEAT_DEEPEN = 0.7  # 4단계: 라이트 배경이면 검정 쪽, 다크 배경이면 흰색 쪽으로 30%
DEFAULT_HEAT_COLOR = "#2DA44E"  # GitHub 초록 느낌
HEAT_PRESETS = (
    ("초록", "#2DA44E"),
    ("파랑", "#1F6FEB"),
    ("보라", "#8250DF"),
    ("주황", "#E16F24"),
    ("분홍", "#D6336C"),
)


@dataclass(frozen=True)
class SolvedItem:
    num: int
    topic: str
    title: str
    via: str  # "swea" | "local"
    at: str  # 기록 시각 (ISO, 로컬)


# --- 경로 / 입출력 ---------------------------------------------------------------------------


def _path(settings: Settings):
    return growth.profile_dir(settings) / SOLVED_FILE


def _mark_path(settings: Settings):
    return settings.coach_dir / BACKFILL_MARK


def parse_days(text: str) -> dict[str, list[dict]]:
    """JSON 본문 → {"YYYY-MM-DD": [항목 dict]}. 손상되면 빈 dict (손상된 항목만 건너뛴다). 기기 파일(M23)도 같은 스키마."""
    try:
        days = json.loads(text)["days"]
        if not isinstance(days, dict):
            return {}
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        log.warning("풀이 잔디 기록을 읽지 못했습니다: %s", e)
        return {}
    out: dict[str, list[dict]] = {}
    for key, items in days.items():
        try:
            date.fromisoformat(str(key))
        except ValueError:
            continue
        if isinstance(items, list):
            out[str(key)] = [i for i in items if isinstance(i, dict) and isinstance(i.get("num"), int) and i.get("via") in VIA]
    return out


def _read_raw(settings: Settings) -> dict[str, list[dict]]:
    """로컬 파일 → {"YYYY-MM-DD": [항목 dict]}. 없거나 손상되면 빈 dict."""
    try:
        text = _path(settings).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        log.warning("풀이 잔디 기록을 읽지 못했습니다: %s", e)
        return {}
    return parse_days(text)


def read_local(settings: Settings) -> dict[str, list[dict]]:
    """로컬 기록만 (기기 간 동기화 병합 전). solved_sync 가 기기 파일을 만들 때 쓴다."""
    return _read_raw(settings)


def _write(settings: Settings, days: dict[str, list[dict]], today: date) -> bool:
    if not growth._writable(settings):
        return False
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    kept = {k: v for k, v in days.items() if k >= cutoff and v}
    try:
        coach._atomic_write(_path(settings), {"v": SOLVED_VERSION, "days": dict(sorted(kept.items()))})
    except OSError as e:
        log.warning("풀이 잔디 저장 실패: %s", e)
        return False
    from . import solved_sync  # 늦은 import: solved_sync 가 solved 를 import 한다

    solved_sync.sync_device_file(settings, kept, today)  # 켜져 있으면 같은 내용을 풀이 저장소의 기기 파일에도 (M23)
    return True


def _add(days: dict[str, list[dict]], num: int, topic: str, title: str, via: str, at: datetime) -> bool:
    """days 에 1건 추가 (메모리). 같은 날 같은 문제면 합친다 — 이미 있으면 SWEA 를 우선하고 빈 제목·주제만 채운다. 바뀌었으면 True."""
    key = at.date().isoformat()
    items = days.setdefault(key, [])
    for it in items:
        if it["num"] == num:
            changed = False
            if via == "swea" and it["via"] != "swea":
                it["via"], changed = "swea", True
            for field, value in (("topic", topic), ("title", title)):
                if value and not it.get(field):
                    it[field], changed = value, True
            return changed
    items.append({"num": int(num), "topic": str(topic or ""), "title": str(title or ""), "via": via, "at": at.isoformat(timespec="seconds")})
    return True


# --- 기록 ------------------------------------------------------------------------------------


def record(settings: Settings, num: int, topic: str, title: str, via: str, *, at: datetime | None = None) -> bool:
    """Pass 1건을 그날에 기록. 실패해도 예외 없음. via 는 "swea" | "local"."""
    try:
        if via not in VIA:
            return False
        stamp = at or growth.now()
        with growth._LOCK:
            days = _read_raw(settings)
            if not _add(days, int(num), topic, title, via, stamp):
                return True  # 이미 기록됨 (같은 날 같은 문제)
            return _write(settings, days, stamp.date())
    except Exception as e:  # noqa: BLE001 — 부가 기능은 제출·검증 흐름을 깨지 않는다
        log.warning("풀이 잔디 기록 실패: %s", e)
        return False


def retract_local(settings: Settings, num: int) -> bool:
    """그 문제의 로컬 통과 기록(via="local")을 모든 날에서 지운다 — SWEA 가 Pass 가 아닌 결과로 채점했을 때. 지웠으면 True. 실패해도 예외 없음."""
    try:
        with growth._LOCK:
            days = _read_raw(settings)
            changed = False
            for key, items in days.items():
                kept = [i for i in items if not (i["num"] == int(num) and i["via"] == "local")]
                if len(kept) != len(items):
                    days[key], changed = kept, True
            return changed and _write(settings, days, growth.now().date())
    except Exception as e:  # noqa: BLE001 — 부가 기능은 제출 흐름을 깨지 않는다
        log.warning("풀이 잔디 로컬 기록 정리 실패: %s", e)
        return False


def _swea_rejected(settings: Settings) -> set[int]:
    """마지막 SWEA 채점이 Pass 가 아닌 문제 번호 (이 기기의 제출 이벤트 기준)."""
    last: dict[int, str] = {}
    try:
        for ev in growth.read_events(settings):
            if ev.t == "submit" and ev.num:
                last[ev.num] = ev.res
    except Exception as e:  # noqa: BLE001
        log.warning("제출 기록을 읽지 못했습니다: %s", e)
    return {n for n, res in last.items() if res != "pass"}


def load(settings: Settings) -> dict[date, list[SolvedItem]]:
    """{날짜: [항목]} (각 날 안은 기록 시각 순). 읽기 전용. 동기화가 켜져 있으면 다른 기기 기록(작업 트리 파일·원격 캐시)을 합친다 (M23)."""
    from . import solved_sync

    rejected = _swea_rejected(settings)
    out: dict[date, list[SolvedItem]] = {}
    for key, items in solved_sync.merged_days(settings, _read_raw(settings)).items():
        rows = [
            SolvedItem(i["num"], str(i.get("topic") or ""), str(i.get("title") or ""), i["via"], str(i.get("at") or ""))
            for i in items
            if not (i["via"] == "local" and i["num"] in rejected)
        ]
        if rows:
            out[date.fromisoformat(key)] = sorted(rows, key=lambda r: r.at)
    return out


def backfill(settings: Settings, at: datetime | None = None) -> int:
    """기존 기록에서 한 번만 채운다 (표식 파일로 1회). 추가한 문제 수. 실패해도 예외 없음."""
    try:
        if _mark_path(settings).exists() or not growth._writable(settings):
            return 0
        stamp = at or growth.now()
        added = 0
        with growth._LOCK:
            days = _read_raw(settings)
            cutoff = stamp - timedelta(days=growth.EVENT_KEEP_DAYS)
            titles = {r.num: r for r in coach._load_records(settings).values()}
            for ev in growth.read_events(settings):
                if ev.t == "submit" and ev.res == "pass" and ev.at >= cutoff and ev.at <= stamp:
                    rec = titles.get(ev.num)
                    added += _add(days, ev.num, ev.topic or (rec.topic if rec else ""), rec.title if rec else "", "swea", ev.at)
            for rec in titles.values():
                if rec.last_result != "pass" or not rec.last_submit_at:
                    continue
                try:
                    when = datetime.fromisoformat(rec.last_submit_at)
                except ValueError:
                    continue
                if when <= stamp and (stamp - when).days < KEEP_DAYS:
                    added += _add(days, rec.num, rec.topic, rec.title, "swea", when)
            if added and not _write(settings, days, stamp.date()):
                return 0
            mark = _mark_path(settings)
            mark.parent.mkdir(parents=True, exist_ok=True)
            mark.write_text(stamp.isoformat(timespec="seconds"), encoding="utf-8")
        return added
    except Exception as e:  # noqa: BLE001
        log.warning("풀이 잔디 백필 실패: %s", e)
        return 0


# --- 집계 ------------------------------------------------------------------------------------


def counts(days: dict[date, list[SolvedItem]]) -> dict[date, int]:
    return {d: len(v) for d, v in days.items() if v}


def level(n: int) -> int:
    """하루 Pass 수 → 농도 0~4."""
    lv = 0
    for i, step in enumerate(HEAT_STEPS, 1):
        if n >= step:
            lv = i
    return lv


def grid_start(today: date, weeks: int = 53) -> date:
    """격자 맨 왼쪽 열의 일요일 (GitHub 처럼 일요일 시작, 마지막 열이 오늘이 든 주)."""
    this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    return this_sunday - timedelta(weeks=weeks - 1)


def total_last_year(days: dict[date, list[SolvedItem]], today: date, weeks: int = 53) -> int:
    """격자에 보이는 기간(첫 일요일 ~ 오늘)의 Pass 수."""
    start = grid_start(today, weeks)
    return sum(len(v) for d, v in days.items() if start <= d <= today)


# --- 색 --------------------------------------------------------------------------------------


def parse_hex(value: str | None, default: str = DEFAULT_HEAT_COLOR) -> str:
    """"#RRGGBB" 만 받는다 (대문자로 통일). 아니면 default."""
    v = (value or "").strip()
    if len(v) == 7 and v[0] == "#":
        try:
            int(v[1:], 16)
            return v.upper()
        except ValueError:
            pass
    return default


def mix(base: str, bg: str, t: float) -> str:
    """bg 에서 base 쪽으로 t(0~1) 만큼 간 색 ("#RRGGBB")."""
    b, g = parse_hex(base, "#000000"), parse_hex(bg, "#FFFFFF")
    out = []
    for i in (1, 3, 5):
        cb, cg = int(b[i:i + 2], 16), int(g[i:i + 2], 16)
        out.append(round(cg + (cb - cg) * max(0.0, min(1.0, t))))
    return "#{:02X}{:02X}{:02X}".format(*out)


def _luma(color: str) -> float:
    c = parse_hex(color, "#FFFFFF")
    r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b


def heat_colors(base: str | None, bg: str, dark: bool = False) -> list[str]:
    """농도 1~4단계 색 4개: 연하게 → 중간 → 기준색 → 기준색보다 한 단계 더 진하게 (GitHub 잔디처럼 단계가 또렷하게).

    1~3단계는 배경(카드 surface)에서 기준색으로 섞고, 4단계는 배경의 반대쪽(라이트면 검정, 다크면 흰색)으로 민다 —
    어느 팔레트에서든 "많이" 쪽이 배경과 가장 멀다. dark=True 면 다크용 혼합 비율(HEAT_MIX_DARK)을 쓴다.
    """
    b = parse_hex(base)
    far = "#000000" if _luma(bg) >= 128 else "#FFFFFF"
    ratios = HEAT_MIX_DARK if dark else HEAT_MIX
    return [*(mix(b, bg, t) for t in ratios), mix(b, far, HEAT_DEEPEN)]


def rel_luminance(color: str) -> float:
    """WCAG 상대 휘도 (0~1)."""
    c = parse_hex(color, "#000000")

    def ch(i: int) -> float:
        v = int(c[i:i + 2], 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5)


DARK_MIN_LUMA = 0.20  # 다크에서 기준색 상대 휘도 하한 (너무 어두우면 카드와 구분 안 됨)
LIGHT_MAX_LUMA = 0.60  # 라이트에서 상한 (너무 밝으면 흰 카드와 구분 안 됨)


def adjust_for_mode(color: str | None, dark: bool) -> str:
    """고정색을 모드에 맞게 표시용으로 보정한다 (저장값 불변). 다크: 휘도 < 0.20 이면 흰색 쪽으로 5%씩 섞어 0.20 이상,
    라이트: > 0.60 이면 검정 쪽으로 5%씩 섞어 0.60 이하. 이미 범위 안이면 그대로(대문자 정규화만)."""
    c = parse_hex(color)
    if dark:
        t = 0.0
        while rel_luminance(c) < DARK_MIN_LUMA and t < 1.0:
            t = min(1.0, t + 0.05)
            c = mix("#FFFFFF", parse_hex(color), t)
        return c
    t = 0.0
    while rel_luminance(c) > LIGHT_MAX_LUMA and t < 1.0:
        t = min(1.0, t + 0.05)
        c = mix("#000000", parse_hex(color), t)
    return c


HEAT_FOLLOW = "follow"
HEAT_COLOR_KEY = "growth/heat_color"


def heat_base(value: object) -> tuple[str, str | None]:
    """QSettings growth/heat_color 값 → ("follow", None) | ("fixed", "#RRGGBB"). 키 없음·"follow"·쓰레기 값은 follow,
    "#RRGGBB" 면 고정색 (기존 사용자가 직접 고른 색을 존중). 설정 페이지·성장 페이지가 공유한다."""
    v = str(value or "").strip()
    if len(v) == 7 and v[0] == "#":
        try:
            int(v[1:], 16)
            return "fixed", v.upper()
        except ValueError:
            pass
    return HEAT_FOLLOW, None
