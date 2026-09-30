"""AI 코치 기록 저장소 (M17): 문제별 학습 기록(records.json), AI 응답 캐시(answers/), 복습 일정. 순수 (Qt·네트워크 없음).

- 위치는 `{config_dir}/coach/`. 풀이 저장소(루트) 안이면 쓰기를 거부한다 — 풀이 이력·AI 응답이 GitHub 로 올라가지 않게.
- 쓰기는 tmp + os.replace. 모든 저장 함수는 예외를 던지지 않고 로그만 남긴다 (부가 기능이 제출 흐름을 깨면 안 됨).
- 날짜는 `now`/`today` 인자로 주입할 수 있다 (테스트).
- 이 모듈은 service 를 import 하지 않는다 (순환 방지). 지문 fetch 같은 오케스트레이션은 service.ask_coach 가 한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import COACH_DIR_NAME, Settings

log = logging.getLogger("swea_fetcher.coach")

RECORDS_FILE = "records.json"
ANSWERS_DIR = "answers"
MAX_PROBLEMS = 500
MAX_ANSWER_FILES = 50
MAX_HINTS = 3
_VERSION = 1  # records.json
_ANSWERS_VERSION = 2  # answers/{num}.json: 엔진별 슬롯 (M18)
ENGINE_KEYS = ("codex", "claude")


@dataclass
class ProblemRecord:
    """문제 1건의 학습 기록. 스냅샷으로 GUI 에 전달된다."""

    num: int
    topic: str = ""
    title: str = ""
    wrong_count: int = 0  # 마지막 Pass 또는 정답 풀이 열람 이후의 오답 누적
    last_result: str = ""  # pass | wrong | timeout | runtime_error
    last_summary: str = ""
    last_submit_at: str = ""
    offer_dismissed: bool = False  # 이번 오답 연속 구간에서 제안을 거절했는가
    solution_viewed_at: str | None = None
    review_due: str | None = None  # "YYYY-MM-DD" (로컬 날짜)
    review_done_at: str | None = None


@dataclass(frozen=True)
class ReviewItem:
    num: int
    topic: str
    title: str
    due: date
    overdue_days: int  # 도래했으면 >= 0, 아직이면 음수 (-2 = 2일 뒤)

    @property
    def is_due(self) -> bool:
        return self.overdue_days >= 0


@dataclass
class EngineSlot:
    """엔진 1개분 응답 캐시."""

    hints: list[dict] = field(default_factory=list)  # [{"level", "markdown", "at"}]
    review: dict | None = None
    solution: dict | None = None


@dataclass
class AnswerCache:
    """문제 1건의 AI 응답 캐시 (엔진별 슬롯). hints/review 는 코드 해시가 다르면 모든 슬롯에서 폐기, solution 은 유지."""

    num: int
    code_sha256: str = ""
    engines: dict[str, EngineSlot] = field(default_factory=dict)

    def slot(self, key: str) -> EngineSlot:
        """엔진 슬롯 (없으면 생성)."""
        return self.engines.setdefault(key, EngineSlot())


# --- 경로 / 입출력 ------------------------------------------------------------------------


def coach_dir(settings: Settings) -> Path:
    return settings.coach_dir


def _inside(path: Path, base: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except (ValueError, OSError):
        return False


def _writable(settings: Settings) -> bool:
    if _inside(settings.coach_dir, settings.root):
        log.warning("AI 코치 기록 위치가 루트 폴더 안이라 기록하지 않습니다: %s", settings.coach_dir)
        return False
    return True


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _records_path(settings: Settings) -> Path:
    return settings.coach_dir / RECORDS_FILE


def _load_records(settings: Settings) -> dict[str, ProblemRecord]:
    """records.json 읽기. 없으면 빈 dict, 손상되면 .corrupt 로 백업하고 빈 dict (복습 일정이 조용히 사라지지 않게)."""
    path = _records_path(settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        problems = raw["problems"]
        known = {f.name for f in fields(ProblemRecord)}
        return {str(k): ProblemRecord(**{a: b for a, b in v.items() if a in known}) for k, v in problems.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        log.warning("AI 코치 기록이 손상되어 백업 후 새로 시작합니다 (%s): %s", path.name, e)
        try:
            os.replace(path, path.with_name(path.name + ".corrupt"))
        except OSError:
            pass
        return {}


def _save_records(settings: Settings, records: dict[str, ProblemRecord]) -> bool:
    if not _writable(settings):
        return False
    _prune_records(records)
    try:
        _atomic_write(_records_path(settings), {"version": _VERSION, "problems": {k: asdict(v) for k, v in records.items()}})
    except OSError as e:
        log.warning("AI 코치 기록 저장 실패: %s", e)
        return False
    return True


def _prune_records(records: dict[str, ProblemRecord]) -> None:
    """500건 초과 시 진행 중이 아닌(오답 0·복습 없음) 기록을 오래된 순으로 삭제."""
    over = len(records) - MAX_PROBLEMS
    if over <= 0:
        return
    idle = sorted((r for r in records.values() if r.wrong_count == 0 and r.review_due is None), key=lambda r: r.last_submit_at)
    for r in idle[:over]:
        records.pop(str(r.num), None)


def _iso(now: datetime | None) -> str:
    return (now or datetime.now()).isoformat(timespec="seconds")


def _today(today: date | None) -> date:
    return today or date.today()


# --- 기록 이벤트 --------------------------------------------------------------------------


def classify(passed: bool, summary: str = "", run_error: str = "", timed_out: bool = False) -> str:
    """제출 결과 → pass | timeout | runtime_error | wrong."""
    if passed:
        return "pass"
    if timed_out:
        return "timeout"
    if run_error:
        return "runtime_error"
    return "wrong"


def get_record(settings: Settings, num: int) -> ProblemRecord | None:
    return _load_records(settings).get(str(int(num)))


def record_submit(
    settings: Settings,
    num: int,
    topic: str,
    title: str,
    result,
    *,
    now: datetime | None = None,
    today: date | None = None,
) -> ProblemRecord | None:
    """SWEA 채점 결과 1건을 기록한다 (SubmitResult 필요 필드: passed, summary, run_error, timed_out).

    오답이면 wrong_count += 1. Pass 면 wrong_count = 0, 도래한 복습이 있으면 완료 처리 (도래 전 Pass 는 복습으로 치지 않음).
    실패해도 예외를 던지지 않는다 (None).
    """
    try:
        records = _load_records(settings)
        rec = records.get(str(int(num))) or ProblemRecord(int(num))
        rec.topic, rec.title = topic or rec.topic, title or rec.title
        rec.last_result = classify(result.passed, result.summary, result.run_error, result.timed_out)
        rec.last_summary = str(result.summary or "")[:200]
        rec.last_submit_at = _iso(now)
        if result.passed:
            rec.wrong_count = 0
            rec.offer_dismissed = False
            if rec.review_due and _today(today) >= date.fromisoformat(rec.review_due):
                rec.review_done_at = _iso(now)
                rec.review_due = None
        else:
            rec.wrong_count += 1
        records[str(rec.num)] = rec
        _save_records(settings, records)
        return rec
    except Exception as e:  # noqa: BLE001 — 부가 기능은 제출 흐름을 깨지 않는다
        log.warning("AI 코치 기록 실패: %s", e)
        return None


def mark_solution_viewed(
    settings: Settings, num: int, review_days: int, *, now: datetime | None = None, today: date | None = None
) -> ProblemRecord | None:
    """정답 풀이를 화면에 표시한 뒤: 오답 누적 리셋, 복습 예약 (이미 미래 일정이면 유지)."""
    try:
        records = _load_records(settings)
        rec = records.get(str(int(num))) or ProblemRecord(int(num))
        t = _today(today)
        rec.solution_viewed_at = _iso(now)
        rec.wrong_count = 0
        rec.offer_dismissed = False
        if not rec.review_due or date.fromisoformat(rec.review_due) <= t:
            rec.review_due = (t + timedelta(days=max(1, int(review_days)))).isoformat()
        records[str(rec.num)] = rec
        _save_records(settings, records)
        return rec
    except Exception as e:  # noqa: BLE001
        log.warning("AI 코치 기록 실패: %s", e)
        return None


def dismiss_offer(settings: Settings, num: int) -> ProblemRecord | None:
    """[다음에]: 이번 오답 연속 구간의 제안 배너를 끈다 (다음 Pass/열람 전까지)."""
    return _update(settings, num, lambda r: setattr(r, "offer_dismissed", True))


def dismiss_review(settings: Settings, num: int) -> ProblemRecord | None:
    """복습 카드의 [✕]: 예약을 지운다 (알림 영구 반복 방지)."""
    return _update(settings, num, lambda r: setattr(r, "review_due", None))


def _update(settings: Settings, num: int, fn) -> ProblemRecord | None:
    try:
        records = _load_records(settings)
        rec = records.get(str(int(num)))
        if rec is None:
            return None
        fn(rec)
        _save_records(settings, records)
        return rec
    except Exception as e:  # noqa: BLE001
        log.warning("AI 코치 기록 실패: %s", e)
        return None


# --- 조회 ---------------------------------------------------------------------------------


def should_offer(rec: ProblemRecord | None, threshold: int) -> bool:
    """정답 풀이 제안 배너: 오답 누적이 기준 이상이고 거절하지 않았을 때."""
    return rec is not None and rec.wrong_count >= threshold and not rec.offer_dismissed


def show_solution_button(rec: ProblemRecord | None, threshold: int) -> bool:
    """[정답 풀이 보기] 버튼 노출: 오답 누적이 기준 이상일 때만 (기준 미만이면 숨김)."""
    return rec is not None and rec.wrong_count >= threshold


def review_items(settings: Settings, today: date | None = None) -> list[ReviewItem]:
    """복습 예약이 있는 문제 (도래일 오름차순 = 가장 오래 밀린 것부터, 같으면 번호순)."""
    t = _today(today)
    items = []
    for rec in _load_records(settings).values():
        if not rec.review_due:
            continue
        try:
            due = date.fromisoformat(rec.review_due)
        except ValueError:
            continue
        items.append(ReviewItem(rec.num, rec.topic, rec.title, due, (t - due).days))
    items.sort(key=lambda i: (i.due, i.num))
    return items


def due_count(settings: Settings, today: date | None = None) -> int:
    return sum(1 for i in review_items(settings, today) if i.is_due)


# --- AI 응답 캐시 -------------------------------------------------------------------------


def code_hash(code: str) -> str:
    """풀이 코드(개행 정규화) 해시."""
    return hashlib.sha256(code.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()


def _answer_path(settings: Settings, num: int) -> Path:
    return settings.coach_dir / ANSWERS_DIR / f"{int(num)}.json"


def _slot_from_raw(raw) -> EngineSlot:
    if not isinstance(raw, dict):
        return EngineSlot()
    return EngineSlot(
        [h for h in (raw.get("hints") or []) if isinstance(h, dict) and "markdown" in h][:MAX_HINTS],
        raw.get("review") if isinstance(raw.get("review"), dict) else None,
        raw.get("solution") if isinstance(raw.get("solution"), dict) else None,
    )


def _engine_key_of(label) -> str | None:
    """v1 엔트리의 표시 이름("Codex" / "Claude Code") → 엔진 키. 매핑 불가면 None."""
    text = str(label or "").lower()
    if "codex" in text or "gpt" in text:
        return "codex"
    if "claude" in text:
        return "claude"
    return None


def _migrate_v1(raw: dict) -> dict[str, EngineSlot]:
    """v1(엔진 무관 hints/review/solution + 엔트리별 engine 라벨) → 엔진별 슬롯. 메모리상 변환만 한다 (파일은 다음 저장 때 v2)."""
    slots: dict[str, EngineSlot] = {}
    for name in ("review", "solution"):
        entry = raw.get(name)
        if not isinstance(entry, dict):
            continue
        key = _engine_key_of(entry.get("engine"))
        if key is None:
            log.debug("v1 캐시 %s 의 엔진을 알 수 없어 버립니다", name)
            continue
        setattr(slots.setdefault(key, EngineSlot()), name, entry)
    hints = [h for h in (raw.get("hints") or []) if isinstance(h, dict) and "markdown" in h]
    first = _engine_key_of(hints[0].get("engine")) if hints else None
    if first is not None:
        kept = []
        for h in hints:
            if _engine_key_of(h.get("engine")) != first:
                continue  # 엔진을 바꿔 가며 받은 힌트는 단계 연속성이 깨지므로 버린다
            if h.get("level") != len(kept) + 1:
                break  # 1..k 연속 구간까지만
            kept.append(h)
        if kept:
            slots.setdefault(first, EngineSlot()).hints = kept[:MAX_HINTS]
    elif hints:
        log.debug("v1 캐시 힌트의 엔진을 알 수 없어 버립니다")
    return slots


def load_answers(settings: Settings, num: int, code: str) -> AnswerCache:
    """응답 캐시 읽기. 없거나 손상되면 빈 캐시. 코드가 바뀌었으면 모든 슬롯의 hints/review 는 버린다 (solution 은 유지).

    v1 파일은 메모리에서만 v2 로 변환한다 (로드 시 쓰기 금지).
    """
    digest = code_hash(code)
    path = _answer_path(settings, num)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if int(raw.get("version") or 1) >= 2:
            engines = {str(k): _slot_from_raw(v) for k, v in (raw.get("engines") or {}).items() if k in ENGINE_KEYS}
        else:
            engines = _migrate_v1(raw)
        cache = AnswerCache(int(raw["num"]), str(raw.get("code_sha256") or ""), engines)
    except FileNotFoundError:
        return AnswerCache(int(num), digest)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        log.warning("AI 응답 캐시가 손상되어 무시합니다 (%s): %s", path.name, e)
        return AnswerCache(int(num), digest)
    if cache.code_sha256 != digest:
        for slot in cache.engines.values():
            slot.hints, slot.review = [], None
        cache.code_sha256 = digest
    return cache


def save_answers(settings: Settings, cache: AnswerCache) -> bool:
    """응답 캐시 기록 (v2, 최근 50문제, mtime LRU). 거부·실패면 False, 예외 없음."""
    if not _writable(settings):
        return False
    path = _answer_path(settings, cache.num)
    try:
        engines = {k: {"hints": v.hints[:MAX_HINTS], "review": v.review, "solution": v.solution} for k, v in cache.engines.items()}
        _atomic_write(path, {"version": _ANSWERS_VERSION, "num": cache.num, "code_sha256": cache.code_sha256, "engines": engines})
        _prune_answers(path.parent)
    except OSError as e:
        log.warning("AI 응답 캐시 기록 실패: %s", e)
        return False
    return True


def _prune_answers(d: Path, keep: int | None = None) -> None:
    keep = MAX_ANSWER_FILES if keep is None else keep
    files = []
    for p in d.glob("*.json"):
        try:
            files.append((p.stat().st_mtime, p))
        except OSError:
            continue
    files.sort(key=lambda t: t[0], reverse=True)
    for _mt, p in files[keep:]:
        try:
            p.unlink()
        except OSError:
            pass


def clear(config_dir: Path) -> int:
    """coach 디렉터리 전체 삭제 (`logout --all`, [AI 기록 지우기]). 지운 파일 수 반환."""
    d = Path(config_dir) / COACH_DIR_NAME
    if not d.is_dir():
        return 0
    n = sum(1 for p in d.rglob("*") if p.is_file())
    shutil.rmtree(d, ignore_errors=True)
    return n
