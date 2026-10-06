"""catalog: 공개 문제 목록 파싱(픽스처) · 순차 갱신 · 원자 저장 · 건전성 · TTL/쿨다운 · 손상 파일 · 삭제 · SWEA 정답 목록 (M24).

네트워크는 FakeSession 으로만 — 실서버에 닿지 않는다. 대기(sleep)·시계는 주입한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from swea_fetcher import catalog
from swea_fetcher.catalog import CatalogError, CatalogParseError
from swea_fetcher.config import Settings
from tests.conftest import DUMMY_ID, DUMMY_PW, FIXTURE_DIR, FakeResponse, FakeSession, load_fixture

NOW = datetime(2026, 10, 6, 9, 0, 0)


def row(num: int, title: str = "문제", lv: int = 3, solved: bool = False) -> str:
    badge = '<span class="badge badge-white">정답</span>' if solved else ""
    return (
        '<div class="widget-box-sub"><div class="widget-header-sub"><div class="header-caption">'
        f'<span class="week_num">{num}.</span><span class="week_text"><a href="#none" onclick="javascript:fn_move_page(\'ID{num:014d}\');">{title} '
        f'<span style="font-weight:700">[3]</span>{badge}</a></span></div>'
        f'<div class="widget-toolbar-sub"><span class="badge badgeC-d{lv}">D{lv}</span></div></div>'
        '<div class="widget-body-sub bd-top"><div class="row pointbox">'
        '<div class="infobox code code-sub"><div class="infobox-data-code"><span class="code-sub-item">참여자</span><span class="code-sub-mum">1.2K</span></div></div>'
        '<div class="infobox code code-sub"><div class="infobox-data-code"><span class="code-sub-item">정답률</span><span class="code-sub-mum">50.00%</span></div></div>'
        "</div></div></div>"
    )


def page(nums: list[int], index: int, total: int, **kw) -> str:
    rows = "".join(row(n, **kw) for n in nums)
    pager = (
        f'<ul class="pagination"><li class="page-item active"><span class="page-link">{index}<span class="sr-only">(current)</span></span></li>'
        f'<li class="page-item divid">/</li><li class="page-item"><a class="page-link" href="#">{total}</a></li></ul>'
    )
    return f'<div class="problem-list"><div class="widget-list">{rows}</div>{pager}</div>'


def form_of(call: dict) -> dict:
    return call["data"]


class Pages:
    """pageIndex → HTML (또는 응답/예외 큐) 를 돌려주는 FakeSession 핸들러."""

    def __init__(self, total: int, per_page: int = 3, start: int = 100):
        self.total, self.per_page, self.start = total, per_page, start
        self.overrides: dict[int, list] = {}

    def __call__(self, method, url, kwargs):
        idx = int(kwargs["data"]["pageIndex"])
        if self.overrides.get(idx):
            return self.overrides[idx].pop(0)
        nums = [self.start + (idx - 1) * self.per_page + i for i in range(self.per_page)]
        return FakeResponse(200, text=page(nums, idx, self.total))


@pytest.fixture
def sleeps() -> list[float]:
    return []


def run_refresh(settings, sess, sleeps, **kw):
    kw.setdefault("now", NOW)
    return catalog.refresh(sess, settings, sleep=sleeps.append, **kw)


def session_for(handler) -> FakeSession:
    s = FakeSession()
    s.handler = handler
    return s


# --- 파싱 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [("785", 785), ("42K", 42000), ("1.2K", 1200), ("3M", 3_000_000), ("1,234", 1234), (" 7k ", 7000), ("-", None), ("", None), ("abc", None)],
)
def test_parse_count(text, expected):
    assert catalog.parse_count(text) == expected


def test_parse_percent_and_level():
    assert catalog.parse_percent("7.49%") == 7.49
    assert catalog.parse_percent("100%") == 100.0
    assert catalog.parse_percent("-") is None
    assert [catalog.parse_level(t) for t in ("D1", "D8", "D9", "Pro", "", "d3")] == [1, 8, 0, 0, 0, 0]


def test_fixture_page_reads_list_rows_only():
    parsed = catalog.parse_page(load_fixture("catalog_page_1.html"))
    nums = [it.num for it in parsed.items]
    assert len(nums) == 10 and len(set(nums)) == 10
    assert 27008 not in nums  # 위쪽 "인기" 위젯 행은 목록이 아니다
    assert (parsed.page, parsed.total) == (1, 31)
    first = parsed.items[0]
    assert (first.num, first.title, first.lv, first.pa, first.sb, first.pr, first.rc, first.pt) == (27006, "대칭 찾기", 4, 636, 303, 27.72, 0, 100)
    assert len(first.id) == 16 and "[" not in first.title
    assert parsed.passed == frozenset()  # 익명 응답에는 정답 배지가 없다


def test_fixture_odd_rows():
    parsed = catalog.parse_page(load_fixture("catalog_page_odd.html"))
    by = {it.num: it for it in parsed.items}
    assert sorted(by) == [1001, 1002, 1003, 1004, 1005, 1006]  # ID 없는 행·번호 없는 행은 버리고 중복은 하나만
    a = by[1001]  # 라벨 순서가 바뀌어도 라벨 텍스트로 읽는다
    assert (a.pr, a.pt, a.rc, a.sb, a.pa, a.lv) == (55.5, 50, 10, 1200, 3_000_000, 2)
    b = by[1002]  # 결측·모르는 라벨
    assert (b.pr, b.pa, b.sb, b.rc, b.lv) == (None, None, 300, None, 4)
    assert by[1003].lv == 0 and by[1004].lv == 0  # 배지 없음 / "Pro"
    assert by[1005].title == "접미사와 배지" and parsed.passed == frozenset({1005})  # [12] 와 정답 배지는 제목이 아니다
    assert by[1006].title == "[S/W 문제해결 기본] 1일차 - View"  # 대괄호로 시작하는 제목은 유지, 굵은 [111] 만 제거
    assert (parsed.page, parsed.total) == (3, 31)


def test_pager_with_current_marker_and_plain():
    from bs4 import BeautifulSoup

    for html, expect in (
        ('<ul class="pagination"><li><span>1<span class="sr-only">(current)</span></span></li><li>/</li><li><a>116</a></li></ul>', (1, 116)),
        ('<ul class="pagination"><li>2 / 9</li></ul>', (2, 9)),
        ('<ul class="pagination"><li>First Previous 1 Next Last</li></ul>', None),
    ):
        assert catalog.parse_pager(BeautifulSoup(html, "lxml")) == expect
    assert catalog.parse_pager(BeautifulSoup("<p>x</p>", "lxml")) is None


def test_parse_page_structure_change_raises():
    with pytest.raises(CatalogParseError):
        catalog.parse_page("<html><body>점검 중입니다</body></html>")  # 0 행
    with pytest.raises(CatalogParseError):
        catalog.parse_page('<div class="problem-list">' + row(1) + "</div>")  # 페이지 문구 없음
    with pytest.raises(CatalogParseError):
        catalog.parse_page('<div class="problem-list"></div><ul class="pagination"><li>1 / 3</li></ul>')


def test_parse_page_allow_empty_only_with_marker():
    html = '<div class="problem-list">해당 목록이 없습니다.</div><ul class="pagination"><li>First Previous 1 Next Last</li></ul>'
    parsed = catalog.parse_page(html, allow_empty=True)
    assert parsed.items == [] and parsed.total == 1
    with pytest.raises(CatalogParseError):
        catalog.parse_page(html)  # 일반 목록에서는 빈 결과가 구조 변경 신호


def test_fixtures_contain_no_personal_data():
    """픽스처는 행 조각만 — 세션·계정·이메일·헤더(GNB) 흔적이 없어야 한다 (커밋 전 grep 대체)."""
    banned = ("JSESSIONID", "SESSION=", "@", "span.name", 'class="name"', "loginPage", "로그아웃", "마이페이지", DUMMY_ID, "pwd", "<form", "<script", "<header")
    for path in sorted(FIXTURE_DIR.glob("catalog_*.html")):
        text = path.read_text(encoding="utf-8")
        for word in banned:
            assert word not in text, f"{path.name} 에 {word!r}"


# --- 갱신 -----------------------------------------------------------------------------


def test_refresh_walks_pages_sequentially_and_saves(settings, sleeps):
    handler = Pages(total=3)
    sess = session_for(handler)
    progress: list[tuple[int, int]] = []
    cat = catalog.refresh(sess, settings, lambda d, t: progress.append((d, t)), sleep=sleeps.append, now=NOW)
    assert [form_of(c)["pageIndex"] for c in sess.calls] == ["1", "2", "3"]
    first = form_of(sess.calls[0])
    assert (first["pageSize"], first["selectCodeLang"], first["orderBy"]) == ("30", "PYTHON", "FIRST_REG_DATETIME")
    assert all(c["method"] == "POST" and c["url"] == catalog.PROBLEM_LIST_URL for c in sess.calls)
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert len(sleeps) == 2 and all(0.3 <= s <= 0.7 for s in sleeps)  # 요청 사이 0.5 ± 0.2 초
    assert len(cat.items) == 9 and cat.pages == 3
    loaded = catalog.load(settings)
    assert loaded is not None and sorted(loaded.items) == sorted(cat.items) and loaded.fetched_at == NOW
    assert catalog.catalog_path(settings).parent == settings.cache_dir
    assert not list(settings.cache_dir.glob("*.tmp"))


def test_refresh_dedupes_numbers_shifted_between_pages(settings, sleeps):
    handler = Pages(total=2)
    handler.overrides[2] = [FakeResponse(200, text=page([102, 103, 104], 2, 2))]  # 1페이지의 102 가 밀려 다시 나옴
    sess = session_for(handler)
    cat = run_refresh(settings, sess, sleeps)
    assert sorted(cat.items) == [100, 101, 102, 103, 104]


def test_refresh_http_error_saves_nothing_and_records_failure(settings, sleeps):
    handler = Pages(total=3)
    handler.overrides[2] = [FakeResponse(500, text="")]
    with pytest.raises(CatalogError) as ei:
        run_refresh(settings, session_for(handler), sleeps)
    assert ei.value.code == "network"
    assert catalog.load(settings) is None and not catalog.catalog_path(settings).exists()
    st = catalog.status(settings, NOW)
    assert st.last_failed and st.last_attempt == NOW and not st.usable


def test_refresh_failure_keeps_previous_catalog(settings, sleeps):
    run_refresh(settings, session_for(Pages(total=2)), sleeps)
    before = catalog.catalog_path(settings).read_text(encoding="utf-8")
    handler = Pages(total=2)
    handler.overrides[2] = [FakeResponse(500, text="")]
    with pytest.raises(CatalogError):
        run_refresh(settings, session_for(handler), sleeps, now=NOW + timedelta(days=8))
    assert catalog.catalog_path(settings).read_text(encoding="utf-8") == before


def test_refresh_429_backoff_5_then_15(settings, sleeps):
    handler = Pages(total=2)
    handler.overrides[2] = [FakeResponse(429, text=""), FakeResponse(503, text=""), FakeResponse(200, text=page([200, 201], 2, 2))]
    cat = run_refresh(settings, session_for(handler), sleeps)
    assert 5 in sleeps and 15 in sleeps and len(cat.items) == 5


def test_refresh_429_gives_up_after_two_retries(settings, sleeps):
    handler = Pages(total=2)
    handler.overrides[2] = [FakeResponse(429, text="")] * 3
    with pytest.raises(CatalogError) as ei:
        run_refresh(settings, session_for(handler), sleeps)
    assert ei.value.code == "rate_limited"
    assert [s for s in sleeps if s >= 5] == [5, 15]
    assert catalog.load(settings) is None


def test_refresh_budget_exceeded(settings, sleeps):
    ticks = iter(range(0, 10_000, 100))  # 호출마다 100초씩 흐르는 시계
    with pytest.raises(CatalogError) as ei:
        catalog.refresh(session_for(Pages(total=5)), settings, sleep=sleeps.append, clock=lambda: next(ticks), now=NOW)
    assert ei.value.code == "budget"
    assert catalog.load(settings) is None


def test_refresh_cancel_saves_nothing(settings, sleeps):
    sess = session_for(Pages(total=5))
    flags = iter([False, True])
    with pytest.raises(CatalogError) as ei:
        run_refresh(settings, sess, sleeps, is_cancelled=lambda: next(flags, True))
    assert ei.value.code == "cancelled" and len(sess.calls) == 1
    assert catalog.load(settings) is None


def test_refresh_zero_rows_is_parse_error(settings, sleeps):
    sess = session_for(lambda *_: FakeResponse(200, text="<html><body>점검</body></html>"))
    with pytest.raises(CatalogParseError):
        run_refresh(settings, sess, sleeps)
    assert catalog.load(settings) is None


def test_refresh_shrink_below_half_is_rejected(settings, sleeps):
    run_refresh(settings, session_for(Pages(total=4)), sleeps)  # 12개
    with pytest.raises(CatalogError) as ei:
        run_refresh(settings, session_for(Pages(total=1, per_page=5)), sleeps, now=NOW + timedelta(days=8))  # 5개 < 6
    assert ei.value.code == "shrunk"
    assert len(catalog.load(settings).items) == 12  # 이전 것 유지


def test_refresh_exactly_half_is_accepted(settings, sleeps):
    run_refresh(settings, session_for(Pages(total=4)), sleeps)  # 12개
    cat = run_refresh(settings, session_for(Pages(total=2)), sleeps, now=NOW + timedelta(days=8))  # 6개 = 50%
    assert len(cat.items) == 6


def test_refresh_absurd_total_pages(settings, sleeps):
    sess = session_for(lambda *_: FakeResponse(200, text=page([1, 2], 1, catalog.MAX_PAGES + 1)))
    with pytest.raises(CatalogParseError):
        run_refresh(settings, sess, sleeps)
    assert len(sess.calls) == 1


def test_refresh_network_error_is_catalog_error(settings, sleeps):
    import requests

    sess = FakeSession([requests.ConnectionError("down")] * 3)
    with pytest.raises(CatalogError) as ei:
        run_refresh(settings, sess, sleeps)
    assert ei.value.code == "network"


def test_refresh_session_expired(settings, sleeps):
    from tests.conftest import login_redirect

    with pytest.raises(CatalogError) as ei:
        run_refresh(settings, FakeSession([login_redirect()]), sleeps)
    assert ei.value.code == "session"


def test_refresh_refuses_to_write_inside_root(tmp_path, sleeps):
    root = tmp_path / "root"
    root.mkdir()
    s = Settings(root=root, user_id=DUMMY_ID, password=DUMMY_PW, config_dir=root / "cfg")
    sess = session_for(Pages(total=1))
    with pytest.raises(CatalogError) as ei:
        catalog.refresh(sess, s, sleep=sleeps.append, now=NOW)
    assert ei.value.code == "unwritable" and sess.calls == []
    assert not (root / "cfg").exists()


def test_anonymous_session_has_no_cookies_or_credentials():
    s = catalog.anonymous_session()
    assert len(s.cookies) == 0 and "Authorization" not in s.headers and "User-Agent" in s.headers


# --- 상태 · TTL · 쿨다운 ------------------------------------------------------------------


def test_status_without_catalog(settings):
    st = catalog.status(settings, NOW)
    assert (st.count, st.usable, st.stale, st.auto_due, st.manual_wait) == (0, False, True, True, 0)


def test_status_ttl_boundary(settings, sleeps):
    run_refresh(settings, session_for(Pages(total=1)), sleeps)
    assert catalog.status(settings, NOW + timedelta(days=7)).stale is False  # 정확히 7일은 아직
    assert catalog.status(settings, NOW + timedelta(days=7, seconds=1)).stale is True
    st = catalog.status(settings, NOW + timedelta(days=1))
    assert st.usable and not st.stale and not st.auto_due and st.count == 3


def test_failed_refresh_blocks_auto_retry_for_6_hours(settings, sleeps):
    with pytest.raises(CatalogError):
        run_refresh(settings, session_for(lambda *_: FakeResponse(500, text="")), sleeps)
    assert catalog.status(settings, NOW + timedelta(hours=5, minutes=59)).auto_due is False
    assert catalog.status(settings, NOW + timedelta(hours=6)).auto_due is True
    assert catalog.status(settings, NOW + timedelta(minutes=1)).manual_wait == 0  # 카탈로그가 없으면 수동 재시도는 쿨다운 없음


def test_manual_cooldown_only_when_catalog_exists(settings, sleeps):
    run_refresh(settings, session_for(Pages(total=1)), sleeps)
    st = catalog.status(settings, NOW + timedelta(minutes=10))
    assert 49 * 60 <= st.manual_wait <= 51 * 60
    assert catalog.status(settings, NOW + timedelta(hours=1, seconds=1)).manual_wait == 0


# --- 손상 · 삭제 ------------------------------------------------------------------------


def test_corrupt_catalog_is_quarantined(settings):
    path = catalog.catalog_path(settings)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert catalog.load(settings) is None
    assert not path.exists() and path.with_suffix(".json.corrupt").exists()
    assert catalog.status(settings, NOW).usable is False  # 예외 없음


def test_wrong_version_and_bad_items_are_ignored(settings):
    path = catalog.catalog_path(settings)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"v": 99, "items": {}}), encoding="utf-8")
    assert catalog.load(settings) is None
    path.write_text(json.dumps({"v": 1, "fetched_at": NOW.isoformat(), "items": {"1": {"id": "A" * 16, "t": "ok", "lv": 3}, "x": {}, "2": "bad", "3": {"lv": 3}}}), encoding="utf-8")
    cat = catalog.load(settings)
    assert cat is not None and list(cat.items) == [1] and cat.items[1].lv == 3


def test_clear_removes_catalog_and_state(settings, sleeps):
    run_refresh(settings, session_for(Pages(total=1)), sleeps)
    assert catalog.clear(settings.config_dir) == 2
    assert catalog.load(settings) is None and catalog.clear(settings.config_dir) == 0


# --- SWEA 정답 목록 -------------------------------------------------------------------------


def test_fetch_passed_uses_filter_and_stores_personal_file(settings, sleeps):
    sess = session_for(lambda *_: FakeResponse(200, text=load_fixture("catalog_passed.html")))
    nums = catalog.fetch_passed(sess, settings, None, sleep=sleeps.append, now=NOW)
    assert nums == {1954: 2, 1859: 2}
    form = form_of(sess.calls[0])
    assert form["passFilterYn"] == "Y" and form["selectCodeLang"] == "ALL"
    path = catalog.passed_path(settings)
    assert path.parent.name == "profile" and path.parent.parent.name == "coach"  # 카탈로그(cache/)와 다른 파일
    assert catalog.load_passed(settings) == ({1954: 2, 1859: 2}, NOW)
    assert catalog.passed_stale(settings, NOW + timedelta(hours=23)) is False
    assert catalog.passed_stale(settings, NOW + timedelta(days=1, seconds=1)) is True


def test_fetch_passed_ignores_rows_without_pass_badge(settings, sleeps):
    """서버가 필터를 무시하고 전체 목록을 주더라도 "정답" 배지가 없는 행은 푼 문제로 치지 않는다."""
    sess = session_for(lambda *_: FakeResponse(200, text=page([1, 2, 3], 1, 1)))
    assert catalog.fetch_passed(sess, settings, None, sleep=sleeps.append, now=NOW) == {}


def test_fetch_passed_empty_result_is_valid(settings, sleeps):
    html = '<div class="problem-list">해당 목록이 없습니다.</div><ul class="pagination"><li>First Previous 1 Next Last</li></ul>'
    sess = session_for(lambda *_: FakeResponse(200, text=html))
    assert catalog.fetch_passed(sess, settings, None, sleep=sleeps.append, now=NOW) == {}
    assert catalog.load_passed(settings)[1] == NOW


def test_fetch_passed_failure_raises_without_retry_loop(settings, sleeps):
    sess = session_for(lambda *_: FakeResponse(500, text=""))
    with pytest.raises(CatalogError):
        catalog.fetch_passed(sess, settings, None, sleep=sleeps.append, now=NOW)
    assert len(sess.calls) == 1
    assert catalog.load_passed(settings) == ({}, None)


def test_load_passed_corrupt_is_empty(settings):
    p = catalog.passed_path(settings)
    p.parent.mkdir(parents=True)
    p.write_text("[]", encoding="utf-8")
    assert catalog.load_passed(settings) == ({}, None)


def test_passed_file_removed_by_growth_clear(settings):
    from swea_fetcher import growth

    catalog.save_passed(settings, {5: 2}, NOW)
    assert catalog.passed_path(settings).exists()
    growth.clear(settings.config_dir)
    assert not catalog.passed_path(settings).exists()
