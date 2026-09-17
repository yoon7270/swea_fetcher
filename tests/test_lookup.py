"""lookup: 번호 → contestProbId 색인 (캐시, 공개 목록 검색, 클럽 상자 스캔)."""

from __future__ import annotations

import json

import pytest

from swea_fetcher import lookup
from swea_fetcher.errors import InvalidInput, LoginFailed, NetworkError
from tests.conftest import CONTEST_PROB_ID, FakeResponse, FakeSession, login_redirect

ID = CONTEST_PROB_ID
ID2 = "AWIeW7FakkUDFAVH"
ID3 = "AVtnUz06AA3w6KZN"


def api_ok(data: dict) -> FakeResponse:
    return FakeResponse(200, json_data={"success": True, "data": data})


def caption_list(*rows: tuple[int, str, str]) -> str:
    """problemList.do 형식: fn_move_page('<ID>') onclick."""
    caps = "".join(
        f"<div class='header-caption'><span class='week_num'>{n}.</span>"
        f"<span class='week_text'><a href='#none' onclick=\"javascript:fn_move_page('{i}');\">{t}</a></span></div>"
        for n, i, t in rows
    )
    return f"<html><body>{caps}</body></html>"


def caption_box(*rows: tuple[int, str, str]) -> str:
    """problemBoxDetail.do 형식: input[name=checkContestProbId]."""
    caps = "".join(
        f"<div class='header-caption'><input type='checkbox' name='checkContestProbId' value='{i}'>"
        f"<span class='week_num'>{n} .</span><span class='week_text'><a href='#'>{t}</a></span></div>"
        for n, i, t in rows
    )
    return f"<html><body>{caps}</body></html>"


EMPTY_LIST = "<html><body><p>결과 없음</p></body></html>"


# =============================================================================
# 캐시
# =============================================================================


def test_index_roundtrip(settings):
    assert lookup.load_index(settings) == {}
    idx = {"25730": {"id": ID, "title": "항아리 게임", "club": "c", "box": "b"}}
    lookup.save_index(settings, idx)
    assert (settings.config_dir / "problem_index.json").is_file()
    assert lookup.load_index(settings) == idx
    assert "항아리" in (settings.config_dir / "problem_index.json").read_text(encoding="utf-8")  # ensure_ascii=False


@pytest.mark.parametrize("content", ["garbage", "[1]", ""])
def test_index_corrupt_is_ignored(settings, content):
    (settings.config_dir / "problem_index.json").write_text(content, encoding="utf-8")
    assert lookup.load_index(settings) == {}


# =============================================================================
# _post_json / 목록 API
# =============================================================================


def test_post_json_sends_json_body_and_headers():
    s = FakeSession([api_ok({"k": 1})])
    assert lookup._post_json(s, lookup.MY_CLUB_LIST_URL, {"a": 1}) == {"k": 1}
    call = s.calls[0]
    assert call["method"] == "POST"
    assert json.loads(call["data"]) == {"a": 1}
    assert call["headers"]["Content-Type"].startswith("application/json")
    assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"


@pytest.mark.parametrize(
    "resp",
    [
        FakeResponse(500, text="err"),
        FakeResponse(200, text="<html>not json</html>"),
        FakeResponse(200, json_data={"success": False, "message": "nope"}),
    ],
)
def test_post_json_errors(resp):
    with pytest.raises(NetworkError):
        lookup._post_json(FakeSession([resp]), lookup.MY_CLUB_LIST_URL, {})


def test_post_json_null_data_is_empty_dict():
    s = FakeSession([FakeResponse(200, json_data={"success": True, "data": None})])
    assert lookup._post_json(s, lookup.MY_CLUB_LIST_URL, {}) == {}


def test_list_my_clubs():
    s = FakeSession([api_ok({"myClubList": [{"solveclubId": "C1", "title": "SSAFY"}, {"solveclubId": "", "title": "x"}, {"solveclubId": "C2"}]})])
    assert lookup.list_my_clubs(s) == [("C1", "SSAFY"), ("C2", "")]


def test_list_boxes_paginates_until_end_page():
    s = FakeSession(
        [
            api_ok({"problemBoxList": [{"probBoxId": "B1", "title": "t1"}], "endPage": 2}),
            api_ok({"problemBoxList": [{"probBoxId": "B2", "title": "t2"}], "endPage": 2}),
        ]
    )
    assert lookup.list_boxes(s, "C1") == [("B1", "t1"), ("B2", "t2")]
    assert [json.loads(c["data"])["pageIndex"] for c in s.calls] == [1, 2]
    assert json.loads(s.calls[0]["data"])["solveclubId"] == "C1"


def test_list_boxes_missing_end_page_means_single_page():
    s = FakeSession([api_ok({"problemBoxList": [{"probBoxId": "B1"}]})])
    assert lookup.list_boxes(s, "C1") == [("B1", "")]
    assert len(s.calls) == 1


def test_list_boxes_respects_max_pages():
    s = FakeSession()
    s.handler = lambda m, u, kw: api_ok({"problemBoxList": [], "endPage": 10_000})
    lookup.list_boxes(s, "C1")
    assert len(s.calls) == lookup.MAX_BOX_PAGES


def test_list_box_problems_parses_captions():
    s = FakeSession([FakeResponse(200, text=caption_box((25730, ID, "항아리 게임"), (24973, ID2, "다른 문제")))])
    out = lookup.list_box_problems(s, "C1", "B1")
    assert out == [(25730, ID, "항아리 게임"), (24973, ID2, "다른 문제")]
    assert s.calls[0]["method"] == "GET" and s.calls[0]["params"] == {"solveclubId": "C1", "probBoxId": "B1"}


def test_list_box_problems_skips_incomplete_captions():
    html = (
        "<html><body>"
        "<div class='header-caption'><span class='week_num'>1 .</span></div>"  # ID 없음
        f"<div class='header-caption'><input name='checkContestProbId' value='{ID}'><span class='week_num'>abc</span></div>"  # 번호 없음
        f"<div class='header-caption'><input name='checkContestProbId' value='{ID2}'><span class='week_num'>7 .</span></div>"  # 제목 없음
        "</body></html>"
    )
    assert lookup.list_box_problems(FakeSession([FakeResponse(200, text=html)]), "C", "B") == [(7, ID2, "")]


def test_list_box_problems_non_200():
    with pytest.raises(NetworkError):
        lookup.list_box_problems(FakeSession([FakeResponse(500, text="")]), "C", "B")


# =============================================================================
# search_problem_lists
# =============================================================================


def test_search_public_list_exact_match_only():
    # 부분 일치로 40140 도 같이 오지만 정확히 4014 인 행만 인정
    s = FakeSession([FakeResponse(200, text=caption_list((40140, ID3, "다른"), (4014, ID2, "활주로 건설")))])
    assert lookup.search_problem_lists(s, 4014) == (ID2, "활주로 건설", "Problem")
    assert s.calls[0]["data"] == {"problemTitle": "4014"}
    assert len(s.calls) == 1


def test_search_falls_back_to_user_problem_list():
    s = FakeSession([FakeResponse(200, text=EMPTY_LIST), FakeResponse(200, text=caption_list((16268, ID, "유저 문제")))])
    assert lookup.search_problem_lists(s, 16268) == (ID, "유저 문제", "User Problem")
    assert [c["url"] for c in s.calls] == [lookup.PROBLEM_LIST_URL, lookup.USER_PROBLEM_LIST_URL]


def test_search_not_found_in_either():
    s = FakeSession([FakeResponse(200, text=EMPTY_LIST), FakeResponse(200, text=EMPTY_LIST)])
    assert lookup.search_problem_lists(s, 1) is None


def test_search_skips_non_200_and_continues():
    s = FakeSession([FakeResponse(500, text=""), FakeResponse(200, text=caption_list((5, ID, "t")))])
    assert lookup.search_problem_lists(s, 5) == (ID, "t", "User Problem")


def test_search_row_without_link_id_is_skipped():
    html = "<html><body><div class='header-caption'><span class='week_num'>5.</span><span class='week_text'><a href='#'>t</a></span></div></body></html>"
    s = FakeSession([FakeResponse(200, text=html), FakeResponse(200, text=EMPTY_LIST)])
    assert lookup.search_problem_lists(s, 5) is None


# =============================================================================
# find_by_number
# =============================================================================


def test_find_by_number_cache_hit_makes_no_request(settings):
    lookup.save_index(settings, {"25730": {"id": ID, "title": "t", "club": "", "box": ""}})
    s = FakeSession()
    assert lookup.find_by_number(s, settings, 25730) == ID
    assert s.calls == []


def test_find_by_number_refresh_ignores_cache(settings):
    lookup.save_index(settings, {"4014": {"id": "STALE", "title": "t", "club": "", "box": ""}})
    s = FakeSession([FakeResponse(200, text=caption_list((4014, ID2, "활주로 건설")))])
    assert lookup.find_by_number(s, settings, 4014, refresh=True) == ID2
    assert lookup.load_index(settings)["4014"]["id"] == ID2


def test_find_by_number_public_list_hit_is_cached(settings):
    s = FakeSession([FakeResponse(200, text=caption_list((4014, ID2, "활주로 건설")))])
    assert lookup.find_by_number(s, settings, 4014) == ID2
    idx = lookup.load_index(settings)
    assert idx["4014"] == {"id": ID2, "title": "활주로 건설", "club": "", "box": "Problem"}


def test_find_by_number_scans_club_boxes_and_caches_all(settings):
    s = FakeSession(
        [
            FakeResponse(200, text=EMPTY_LIST),  # Problem
            FakeResponse(200, text=EMPTY_LIST),  # User Problem
            api_ok({"myClubList": [{"solveclubId": "C1", "title": "SSAFY"}]}),
            api_ok({"problemBoxList": [{"probBoxId": "B1", "title": "09.10 모의"}, {"probBoxId": "B2", "title": "09.03 모의"}], "endPage": 1}),
            FakeResponse(200, text=caption_box((1, ID3, "first"))),  # B1: 없음
            FakeResponse(200, text=caption_box((25730, ID, "항아리 게임"), (24973, ID2, "other"))),  # B2: 있음
        ]
    )
    assert lookup.find_by_number(s, settings, 25730) == ID
    idx = lookup.load_index(settings)
    assert {k: idx["25730"][k] for k in ("id", "title", "club", "box")} == {"id": ID, "title": "항아리 게임", "club": "SSAFY", "box": "09.03 모의"}
    assert idx["25730"]["box_id"] and idx["25730"]["club_id"]  # M8: 제출 category 용
    assert idx["1"]["id"] == ID3 and idx["24973"]["id"] == ID2  # 훑은 것은 모두 캐시
    assert len(s.calls) == 6  # 찾은 뒤 더 훑지 않음


def test_find_by_number_not_found_anywhere(settings):
    s = FakeSession(
        [
            FakeResponse(200, text=EMPTY_LIST),
            FakeResponse(200, text=EMPTY_LIST),
            api_ok({"myClubList": [{"solveclubId": "C1", "title": "SSAFY"}]}),
            api_ok({"problemBoxList": [{"probBoxId": "B1", "title": "b"}], "endPage": 1}),
            FakeResponse(200, text=caption_box((1, ID3, "first"))),
        ]
    )
    with pytest.raises(InvalidInput, match="99999"):
        lookup.find_by_number(s, settings, 99999)
    assert lookup.load_index(settings)["1"]["id"] == ID3  # 실패해도 훑은 것은 캐시


def test_find_by_number_no_clubs(settings):
    s = FakeSession([FakeResponse(200, text=EMPTY_LIST), FakeResponse(200, text=EMPTY_LIST), api_ok({"myClubList": []})])
    with pytest.raises(InvalidInput):
        lookup.find_by_number(s, settings, 5)


def test_find_by_number_relogins_once_on_session_expiry(settings, monkeypatch):
    from swea_fetcher import client

    logins: list = []
    monkeypatch.setattr(client.auth, "login", lambda sess, st: logins.append(1))
    s = FakeSession([login_redirect(), FakeResponse(200, text=caption_list((4014, ID2, "t")))])
    assert lookup.find_by_number(s, settings, 4014) == ID2
    assert len(logins) == 1


def test_find_by_number_session_still_expired(settings, monkeypatch):
    from swea_fetcher import client

    monkeypatch.setattr(client.auth, "login", lambda sess, st: None)
    s = FakeSession([login_redirect(), login_redirect()])
    with pytest.raises(LoginFailed):
        lookup.find_by_number(s, settings, 4014)
