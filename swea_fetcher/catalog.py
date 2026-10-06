"""SWEA 공개 문제 목록 카탈로그 (M24-A): 번호 → 제목·난이도(D1~D8)·정답률·참여자.

"오늘의 추천"(recommend.py)이 푼 문제의 난이도를 알고 후보를 고르려면 공개 Problem 목록 전체가 필요하다.
`POST /main/code/problem/problemList.do` 를 pageSize=30 으로 순차 요청해(Python 필터 약 31페이지) 한 번에 받고
`{config_dir}/cache/problem_catalog.json` 에 저장한다 (docs/swea-page-notes.md "M24 공개 문제 목록 실측").

- 갱신은 **익명 세션**으로 한다 (공개 목록은 비로그인에서도 200 → 로그인 가드/실패 카운터를 건드리지 않는다).
- 전부 성공했을 때만 원자적으로 저장한다 (등록순으로 받는 중 중단되면 편향된 부분 카탈로그가 수준 계산을 왜곡).
- 지난 카탈로그보다 결과가 절반 미만으로 줄면 HTML 구조 변경으로 보고 저장하지 않는다 (이전 것 유지).
- 카탈로그는 공개 데이터라 `cache/` 에 둔다. 내 풀이 이력과 얽힌 "SWEA 정답 목록"은 `coach/profile/` 에 따로 둔다
  ([성장 기록 지우기] 가 함께 지운다). 루트(풀이 저장소) 안에는 쓰지 않는다.
- 이 모듈은 Qt 를 모른다. 진행·취소·sleep 은 인자로 받는다 (테스트에서 0 으로 주입).
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import requests
from bs4 import BeautifulSoup

from . import auth, client, coach, growth
from .config import Settings
from .errors import NetworkError, SessionExpired, SweaFetchError
from .lookup import LIST_ID_RE, NUM_RE, PROBLEM_LIST_URL, SEL_CAPTION_NUM, SEL_LIST_LINK

log = logging.getLogger("swea_fetcher.catalog")

# --- 실측으로 정한 상수 (M24-0) ---------------------------------------------------------
CATALOG_LANG = "PYTHON"  # selectCodeLang: PYTHON 이 목록을 줄인다 (31페이지 vs ALL 39페이지)
PAGE_SIZE = 30  # pageSize: 10/20/30 중 최대
ORDER_BY = "FIRST_REG_DATETIME"
PASSED_FILTER = ("passFilterYn", "Y")  # "정답" 필터. None 이면 SWEA 정답 목록 기능을 끈다
PASSED_LANG = "ALL"
MAX_PAGES = 200  # 총 페이지 상한 (무한 루프·오파싱 방지)
MAX_PASSED_PAGES = 10

PACE = 0.5  # 요청 사이 대기(초)
PACE_JITTER = 0.2
BACKOFF = (5, 15)  # HTTP 429/503 재시도 대기(초). 두 번까지
REFRESH_BUDGET = 180.0  # 전체 갱신 시간 상한(초)
TTL = timedelta(days=7)
FAIL_RETRY = timedelta(hours=6)  # 실패 후 자동 재시도 금지 간격
MANUAL_COOLDOWN = timedelta(hours=1)  # 카탈로그가 있을 때 [새로 받기] 간격
PASSED_TTL = timedelta(days=1)
SHRINK_RATIO = 0.5  # 새 결과가 이전의 이 비율 미만이면 구조 변경으로 본다

CATALOG_FILE = "problem_catalog.json"
STATE_FILE = "catalog_state.json"
PASSED_FILE = "swea_passed.json"
_VERSION = 1

# --- 선택자 (HTML 이 바뀌면 여기만 고친다) ------------------------------------------------
SEL_ROWS = "div.problem-list div.widget-box-sub"  # 같은 클래스가 위쪽 "인기" 위젯에도 있어 목록 안만 읽는다
SEL_ROWS_FALLBACK = "div.widget-box-sub"
SEL_BADGE = "span.badge"
SEL_LABEL = "span.code-sub-item"
SEL_VALUE = "span.code-sub-mum"
SEL_PAGER = "ul.pagination"
PAGER_RE = re.compile(r"(\d+)\s*(?:\(current\))?\s*/\s*(\d+)")
LEVEL_RE = re.compile(r"^D([1-8])$")
PASSED_BADGE = "정답"
EMPTY_MARK = "해당 목록이 없습니다"
_LABELS = {"참여자": "pa", "제출": "sb", "정답률": "pr", "추천": "rc", "포인트": "pt"}


# --- 예외 ------------------------------------------------------------------------------------


class CatalogError(SweaFetchError):
    """목록을 받지 못함. code: network | session | rate_limited | parse | shrunk | budget | cancelled | unwritable | cooldown."""

    exit_code = 5
    default_hint = "잠시 뒤 다시 시도하세요"

    def __init__(self, message: str, *, code: str = "network", hint: str | None = None) -> None:
        super().__init__(message, hint=hint)
        self.code = code


class CatalogParseError(CatalogError):
    """목록 HTML 구조가 예상과 다름 (SWEA 페이지 변경 신호)."""

    default_hint = "SWEA 페이지 구조가 바뀐 것 같습니다. 앱을 업데이트하거나 docs/troubleshooting.md 를 확인하세요"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message, code="parse", hint=hint)


# --- 데이터 ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogItem:
    num: int
    id: str
    title: str
    lv: int = 0  # 1..8, 0 = 알 수 없음 (배지 없음/예상 밖 값)
    pr: float | None = None  # 정답률 %
    pa: int | None = None  # 참여자 (대략값: "7K" → 7000)
    sb: int | None = None  # 제출
    rc: int | None = None  # 추천
    pt: int | None = None  # 포인트


@dataclass
class ParsedPage:
    items: list[CatalogItem] = field(default_factory=list)
    passed: frozenset[int] = frozenset()  # "정답" 배지가 붙은 행의 번호 (로그인 세션에서만)
    page: int | None = None
    total: int | None = None


@dataclass
class Catalog:
    items: dict[int, CatalogItem] = field(default_factory=dict)
    fetched_at: datetime | None = None
    lang: str = CATALOG_LANG
    pages: int = 0


@dataclass(frozen=True)
class CatalogStatus:
    """카드가 "준비 중/갱신 필요"를 판단하는 요약 (파일 읽기만으로 만든다)."""

    count: int = 0
    fetched_at: datetime | None = None
    stale: bool = True  # 없거나 7일 초과
    usable: bool = False  # 추천에 쓸 카탈로그가 있다
    last_attempt: datetime | None = None
    last_failed: bool = False
    auto_due: bool = True  # 지금 자동 갱신해도 되는가 (stale 이고 실패 쿨다운이 아님)
    manual_wait: int = 0  # [새로 받기] 까지 남은 초 (카탈로그가 있을 때만 1시간 쿨다운)


# --- 파싱 ------------------------------------------------------------------------------------


def parse_count(text: str) -> int | None:
    """"785" → 785, "42K" → 42000, "1.2K" → 1200, "3M" → 3000000, "1,234" → 1234. 못 읽으면 None."""
    m = re.fullmatch(r"\s*([\d,]+(?:\.\d+)?)\s*([KkMm]?)\s*", text or "")
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    mult = {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()]
    return int(round(value * mult))


def parse_percent(text: str) -> float | None:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%?\s*", text or "")
    return float(m.group(1)) if m else None


def parse_level(text: str) -> int:
    m = LEVEL_RE.match((text or "").strip())
    return int(m.group(1)) if m else 0


def _parse_row(row) -> tuple[CatalogItem, bool] | None:
    """행 1개 → (항목, 정답 배지 여부). 번호 또는 ID 가 없으면 None (버림)."""
    num_el = row.select_one(SEL_CAPTION_NUM)
    m = NUM_RE.match(num_el.get_text(strip=True)) if num_el is not None else None
    link = row.select_one(SEL_LIST_LINK)
    id_m = LIST_ID_RE.search(link.get("onclick") or link.get("href") or "") if link is not None else None
    if not m or not id_m:
        return None
    solved = False
    for span in link.find_all("span"):  # 굵은 "[댓글수]" 와 로그인 세션의 "정답" 배지는 제목이 아님
        if PASSED_BADGE in span.get_text(strip=True) and "badge" in (span.get("class") or []):
            solved = True
        span.decompose()
    title = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
    badge = row.select_one(f"div.widget-toolbar-sub {SEL_BADGE}") or row.select_one(SEL_BADGE)
    values: dict[str, object] = {}
    for label_el, value_el in zip(row.select(SEL_LABEL), row.select(SEL_VALUE)):  # 라벨 텍스트로 매핑 (순서 가정 금지)
        key = _LABELS.get(label_el.get_text(strip=True))
        if key is None:
            continue
        text = value_el.get_text(strip=True)
        values[key] = parse_percent(text) if key == "pr" else parse_count(text)
    item = CatalogItem(
        num=int(m.group(1)),
        id=id_m.group(1),
        title=title,
        lv=parse_level(badge.get_text(strip=True)) if badge is not None else 0,
        pr=values.get("pr"),  # type: ignore[arg-type]
        pa=values.get("pa"),  # type: ignore[arg-type]
        sb=values.get("sb"),  # type: ignore[arg-type]
        rc=values.get("rc"),  # type: ignore[arg-type]
        pt=values.get("pt"),  # type: ignore[arg-type]
    )
    return item, solved


def parse_pager(soup: BeautifulSoup) -> tuple[int, int] | None:
    """"1 (current) / 31" → (1, 31). 페이지 문구가 없으면 None."""
    pager = soup.select_one(SEL_PAGER)
    if pager is None:
        return None
    m = PAGER_RE.search(re.sub(r"\s+", " ", pager.get_text(" ", strip=True)))
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_page(html: str, *, allow_empty: bool = False) -> ParsedPage:
    """목록 응답 HTML → 행·페이지 문구. 행이 0개이거나 페이지 문구가 없으면 CatalogParseError.

    allow_empty: 필터 결과가 없을 수 있는 요청(정답 목록)은 "해당 목록이 없습니다." 를 빈 결과로 받는다.
    """
    soup = BeautifulSoup(html or "", "lxml")
    rows = soup.select(SEL_ROWS) or soup.select(SEL_ROWS_FALLBACK)
    items: list[CatalogItem] = []
    passed: set[int] = set()
    seen: set[int] = set()
    for row in rows:
        parsed = _parse_row(row)
        if parsed is None:
            continue
        item, solved = parsed
        if item.num in seen:
            continue
        seen.add(item.num)
        items.append(item)
        if solved:
            passed.add(item.num)
    pager = parse_pager(soup)
    if not items:
        if allow_empty and EMPTY_MARK in soup.get_text():
            return ParsedPage([], frozenset(), 1, 1)
        raise CatalogParseError("문제 목록에서 행을 읽지 못했습니다 (페이지 구조 변경?)")
    if pager is None:
        raise CatalogParseError("문제 목록의 페이지 문구를 읽지 못했습니다 (페이지 구조 변경?)")
    return ParsedPage(items, frozenset(passed), pager[0], pager[1])


# --- 저장 / 로드 -------------------------------------------------------------------------------


def catalog_path(settings: Settings) -> Path:
    return settings.cache_dir / CATALOG_FILE


def _state_path(settings: Settings) -> Path:
    return settings.cache_dir / STATE_FILE


def passed_path(settings: Settings) -> Path:
    return growth.profile_dir(settings) / PASSED_FILE


def _writable(directory: Path, settings: Settings) -> bool:
    """루트(풀이 저장소) 안이면 쓰기를 거부한다."""
    if coach._inside(directory, settings.root):
        log.warning("문제 목록 저장 위치가 루트 폴더 안이라 기록하지 않습니다: %s", directory)
        return False
    return True


def _write_json(path: Path, data: dict) -> None:
    """tmp + os.replace 원자 쓰기 (카탈로그는 크기가 커서 들여쓰기 없이 압축)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with growth._LOCK:
            tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _quarantine(path: Path) -> None:
    """손상 파일을 .corrupt 로 옮겨 "없음" 취급 (예외 없음)."""
    try:
        os.replace(path, path.with_suffix(path.suffix + ".corrupt"))
    except OSError:
        pass


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        log.warning("%s 를 읽을 수 없어 무시합니다: %s", path.name, e)
        _quarantine(path)
        return None
    if not isinstance(data, dict) or data.get("v") != _VERSION:
        _quarantine(path)
        return None
    return data


def _parse_iso(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _num_or_none(value: object, kind: type) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return kind(value)


def load(settings: Settings) -> Catalog | None:
    """저장된 카탈로그. 없거나 손상·버전 불일치(.corrupt 로 이동)면 None. 예외 없음."""
    data = _read_json(catalog_path(settings))
    if data is None:
        return None
    raw = data.get("items")
    if not isinstance(raw, dict):
        _quarantine(catalog_path(settings))
        return None
    items: dict[int, CatalogItem] = {}
    for key, v in raw.items():
        try:
            num = int(key)
            if not isinstance(v, dict) or not isinstance(v.get("id"), str):
                continue
            lv = v.get("lv")
            items[num] = CatalogItem(
                num=num,
                id=v["id"],
                title=str(v.get("t") or ""),
                lv=lv if isinstance(lv, int) and 0 <= lv <= 8 else 0,
                pr=_num_or_none(v.get("pr"), float),  # type: ignore[arg-type]
                pa=_num_or_none(v.get("pa"), int),  # type: ignore[arg-type]
                sb=_num_or_none(v.get("sb"), int),  # type: ignore[arg-type]
                rc=_num_or_none(v.get("rc"), int),  # type: ignore[arg-type]
                pt=_num_or_none(v.get("pt"), int),  # type: ignore[arg-type]
            )
        except (TypeError, ValueError):
            continue
    if not items:
        return None
    return Catalog(items, _parse_iso(data.get("fetched_at")), str(data.get("lang") or CATALOG_LANG), int(data.get("pages") or 0))


def _encode(cat: Catalog) -> dict:
    return {
        "v": _VERSION,
        "fetched_at": cat.fetched_at.isoformat(timespec="seconds") if cat.fetched_at else "",
        "lang": cat.lang,
        "complete": True,
        "pages": cat.pages,
        "items": {
            str(n): {"id": it.id, "t": it.title, "lv": it.lv, "pr": it.pr, "pa": it.pa, "sb": it.sb, "rc": it.rc, "pt": it.pt}
            for n, it in sorted(cat.items.items())
        },
    }


def _read_state(settings: Settings) -> dict:
    data = _read_json(_state_path(settings))
    return data or {}


def _record_attempt(settings: Settings, now: datetime, ok: bool) -> None:
    """갱신 시도 기록 (실패 후 6시간 자동 재시도 금지·수동 1시간 쿨다운 판단용). 실패는 삼킨다."""
    try:
        if _writable(settings.cache_dir, settings):
            _write_json(_state_path(settings), {"v": _VERSION, "last_attempt": now.isoformat(timespec="seconds"), "last_ok": ok})
    except OSError as e:
        log.warning("문제 목록 상태를 기록하지 못했습니다: %s", e)


def status(settings: Settings, now: datetime | None = None) -> CatalogStatus:
    """파일만 읽어 상태를 만든다 (네트워크 없음, 가벼움)."""
    now = growth._now(now)
    cat = load(settings)
    state = _read_state(settings)
    last_attempt = _parse_iso(state.get("last_attempt"))
    last_failed = bool(last_attempt) and state.get("last_ok") is False
    usable = cat is not None
    fetched = cat.fetched_at if cat else None
    stale = (not usable) or fetched is None or now - fetched > TTL
    auto_due = stale and not (last_failed and last_attempt is not None and now - last_attempt < FAIL_RETRY)
    wait = 0
    if usable and last_attempt is not None and now - last_attempt < MANUAL_COOLDOWN:
        wait = int((MANUAL_COOLDOWN - (now - last_attempt)).total_seconds()) + 1
    return CatalogStatus(
        count=len(cat.items) if cat else 0,
        fetched_at=fetched,
        stale=stale,
        usable=usable,
        last_attempt=last_attempt,
        last_failed=last_failed,
        auto_due=auto_due,
        manual_wait=wait,
    )


def clear(config_dir: Path) -> int:
    """카탈로그와 시도 기록 삭제 (`logout --all`). 지운 파일 수. content_cache.clear 보다 먼저 부를 것 (빈 cache/ 폴더 정리)."""
    cache = Path(config_dir) / "cache"
    n = 0
    for name in (CATALOG_FILE, STATE_FILE):
        for suffix in ("", ".tmp", ".corrupt"):
            p = cache / (name + suffix)
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    return n


# --- 갱신 (네트워크) ----------------------------------------------------------------------------


def anonymous_session() -> requests.Session:
    """쿠키 없는 세션. 공개 목록은 비로그인에서도 200 이라 로그인 가드/실패 카운터를 건드리지 않는다."""
    session = requests.Session()
    session.headers.update({"User-Agent": auth.USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})
    return session


def _form(page: int, lang: str, extra: dict | None = None) -> dict:
    data = {"orderBy": ORDER_BY, "pageSize": str(PAGE_SIZE), "pageIndex": str(page), "selectCodeLang": lang}
    if extra:
        data.update(extra)
    return data


def _fetch_html(session: requests.Session, form: dict, sleep: Callable[[float], None]) -> str:
    """요청 1건. 429/503 은 5초 → 15초 대기 후 최대 2회 재시도. 오류는 CatalogError 로 단일화."""
    for attempt in range(len(BACKOFF) + 1):
        try:
            r = client._request(session, "POST", PROBLEM_LIST_URL, data=form)
        except SessionExpired as e:
            raise CatalogError("세션이 만료되었습니다", code="session") from e
        except NetworkError as e:
            raise CatalogError(str(e), code="network") from e
        if r.status_code in (429, 503):
            if attempt < len(BACKOFF):
                log.info("문제 목록 요청이 HTTP %s — %d초 뒤 재시도", r.status_code, BACKOFF[attempt])
                sleep(BACKOFF[attempt])
                continue
            raise CatalogError(f"SWEA 가 요청을 제한하고 있습니다 (HTTP {r.status_code})", code="rate_limited",
                               hint="잠시(수 분) 뒤 다시 시도하세요")
        if r.status_code != 200:
            raise CatalogError(f"문제 목록 요청 실패: HTTP {r.status_code}", code="network")
        return r.text
    raise CatalogError("문제 목록 요청 실패", code="network")  # 도달 불가 (방어)


def refresh(
    session: requests.Session,
    settings: Settings,
    progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: datetime | None = None,
) -> Catalog:
    """공개 목록 전체를 순차로 받아 저장한다. 전부 성공해야 저장하며 실패는 CatalogError (이전 카탈로그 유지).

    페이지 사이에 PACE ± PACE_JITTER 초를 쉬고, REFRESH_BUDGET 초를 넘기면 중단한다. 병렬 요청 없음.
    """
    now = growth._now(now)
    if not _writable(settings.cache_dir, settings):
        raise CatalogError("문제 목록 저장 위치가 루트 폴더 안입니다", code="unwritable",
                           hint="설정의 루트 폴더와 ~/.swea-fetch 위치를 확인하세요")
    cancelled = is_cancelled or (lambda: False)
    started = clock()
    items: dict[int, CatalogItem] = {}
    total: int | None = None
    page = 1
    try:
        while True:
            if cancelled():
                raise CatalogError("취소했습니다", code="cancelled")
            if clock() - started > REFRESH_BUDGET:
                raise CatalogError("문제 목록을 받는 시간이 너무 오래 걸려 중단했습니다", code="budget")
            parsed = parse_page(_fetch_html(session, _form(page, CATALOG_LANG), sleep))
            if total is None:
                total = parsed.total or 1
                if total > MAX_PAGES:
                    raise CatalogParseError(f"문제 목록의 총 페이지 수가 비정상입니다: {total}")
            for it in parsed.items:
                items.setdefault(it.num, it)  # 등록순 중 새 문제로 페이지가 밀려 겹친 행은 먼저 본 것을 유지
            if progress:
                progress(page, total)
            if page >= total:
                break
            page += 1
            sleep(max(0.0, PACE + random.uniform(-PACE_JITTER, PACE_JITTER)))
        prev = load(settings)
        if not items:
            raise CatalogParseError("문제 목록이 비어 있습니다")
        if prev is not None and len(items) < len(prev.items) * SHRINK_RATIO:
            raise CatalogError(f"새 문제 목록이 이전보다 훨씬 작습니다 ({len(items)} < {len(prev.items)}) — 구조 변경으로 보고 저장하지 않았습니다",
                               code="shrunk", hint="이전 목록을 계속 사용합니다. 반복되면 docs/troubleshooting.md 를 확인하세요")
        cat = Catalog(items, now, CATALOG_LANG, total or 0)
        _write_json(catalog_path(settings), _encode(cat))
    except CatalogError:
        _record_attempt(settings, now, ok=False)
        raise
    except OSError as e:
        _record_attempt(settings, now, ok=False)
        raise CatalogError(f"문제 목록을 저장하지 못했습니다: {e}", code="unwritable") from e
    _record_attempt(settings, now, ok=True)
    return cat


# --- SWEA 정답 목록 (개인 데이터, coach/profile/) -----------------------------------------------------


def fetch_passed(
    session: requests.Session,
    settings: Settings,
    catalog: Catalog | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
) -> dict[int, int]:
    """로그인 세션으로 "내가 정답한 문제" 목록을 받아 `profile/swea_passed.json` 에 저장하고 {번호: 레벨} 을 돌려준다.

    서버가 필터를 무시하면 전체 목록이 오므로 "정답" 배지가 붙은 행만 인정한다. 실패는 CatalogError (재시도 없음).
    """
    if PASSED_FILTER is None:
        return {}
    now = growth._now(now)
    cancelled = is_cancelled or (lambda: False)
    nums: dict[int, int] = {}
    page = 1
    while page <= MAX_PASSED_PAGES:
        if cancelled():
            raise CatalogError("취소했습니다", code="cancelled")
        parsed = parse_page(_fetch_html(session, _form(page, PASSED_LANG, {PASSED_FILTER[0]: PASSED_FILTER[1]}), sleep), allow_empty=True)
        levels = {it.num: it.lv for it in parsed.items}
        if catalog is not None:  # 카탈로그가 더 정확하면 (목록 배지가 같은 값이라 보통 동일) 보정
            levels = {n: (catalog.items[n].lv if n in catalog.items else lv) for n, lv in levels.items()}
        for n in parsed.passed:
            nums[n] = levels.get(n, 0)
        if page >= (parsed.total or 1):
            break
        page += 1
        sleep(max(0.0, PACE + random.uniform(-PACE_JITTER, PACE_JITTER)))
    save_passed(settings, nums, now)
    return nums


def save_passed(settings: Settings, nums: dict[int, int], now: datetime | None = None) -> None:
    now = growth._now(now)
    if not _writable(growth.profile_dir(settings), settings):
        return
    try:
        _write_json(passed_path(settings), {"v": _VERSION, "fetched_at": now.isoformat(timespec="seconds"),
                                            "nums": {str(n): lv for n, lv in sorted(nums.items())}})
    except OSError as e:
        log.warning("SWEA 정답 목록을 저장하지 못했습니다: %s", e)


def load_passed(settings: Settings) -> tuple[dict[int, int], datetime | None]:
    """({번호: 레벨}, 받은 시각). 없거나 손상이면 ({}, None). 예외 없음."""
    data = _read_json(passed_path(settings))
    if data is None or not isinstance(data.get("nums"), dict):
        return {}, None
    out: dict[int, int] = {}
    for k, v in data["nums"].items():
        try:
            out[int(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out, _parse_iso(data.get("fetched_at"))


def passed_stale(settings: Settings, now: datetime | None = None) -> bool:
    """정답 목록을 다시 받을 때가 되었는가 (없거나 1일 초과)."""
    _, at = load_passed(settings)
    return at is None or growth._now(now) - at > PASSED_TTL
