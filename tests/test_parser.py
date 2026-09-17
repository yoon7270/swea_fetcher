"""parser: contestProbId 추출, 페이지별 제목/번호, 첨부 링크."""

from __future__ import annotations

import logging

import pytest

from swea_fetcher import parser
from swea_fetcher.errors import AttachmentNotFound, InvalidInput, ParseError
from tests.conftest import CONTEST_PROB_ID

ID = CONTEST_PROB_ID
MENU_ID = "AVtnUz06AA3w6KZN"  # 픽스처의 _menuId — contestProbId 와 같은 16자 패턴
DOWN = "/main/common/contestProb/contestProbDown.do"


# =============================================================================
# extract_contest_prob_id
# =============================================================================


@pytest.mark.parametrize(
    "text",
    [
        ID,
        f"  {ID}\n",
        f"https://swexpertacademy.com{DOWN}?downType=in&contestProbId={ID}",
        f"https://swexpertacademy.com{DOWN}?downType=in&contestProbId={ID}&_menuId={MENU_ID}&_menuF=true",
        f"https://swexpertacademy.com/main/code/problem/problemDetail.do?contestProbId={ID}",
        f"contestProbId={ID}",
        f"문제 {ID} 저장",
        f"https://swexpertacademy.com{DOWN}?downType=in&amp;contestProbId={ID}&amp;_menuId={MENU_ID}",  # HTML 엔티티 그대로 복사
    ],
)
def test_extract_ok(text):
    assert parser.extract_contest_prob_id(text) == ID


def test_extract_url_query_wins_over_other_16char_tokens():
    # _menuId 가 앞에 와도 contestProbId 쿼리를 우선한다
    url = f"https://swexpertacademy.com{DOWN}?_menuId={MENU_ID}&downType=in&contestProbId={ID}"
    assert parser.extract_contest_prob_id(url) == ID


@pytest.mark.parametrize("text", ["", "   ", None])
def test_extract_empty(text):
    with pytest.raises(InvalidInput, match="비어"):
        parser.extract_contest_prob_id(text)


@pytest.mark.parametrize(
    "text",
    [
        "12345",  # 문제 번호만
        "AZq-gSmq_RfHBIS",  # 15자
        "AZq-gSmq_RfHBISSX",  # 17자
        "https://swexpertacademy.com/main/code/problem/problemList.do",
        "AZq-gSmq_RfHBI$S",
    ],
)
def test_extract_not_found(text):
    with pytest.raises(InvalidInput, match="찾을 수 없습니다"):
        parser.extract_contest_prob_id(text)


def test_extract_ambiguous_multiple_candidates():
    with pytest.raises(InvalidInput, match="여러 개") as ei:
        parser.extract_contest_prob_id(f"{ID} {MENU_ID}")
    assert ID in str(ei.value) and MENU_ID in str(ei.value)


def test_extract_same_id_twice_is_not_ambiguous():
    assert parser.extract_contest_prob_id(f"{ID} {ID}") == ID


def test_extract_url_with_invalid_contest_prob_id_must_not_fall_back_to_menu_id():
    """contestProbId 쿼리가 명시돼 있는데 값이 잘못됐으면 _menuId 를 답으로 내면 안 된다."""
    url = f"https://swexpertacademy.com{DOWN}?downType=in&contestProbId=BAD&_menuId={MENU_ID}&_menuF=true"
    with pytest.raises(InvalidInput):
        parser.extract_contest_prob_id(url)


# =============================================================================
# parse — solver 페이지 (C)
# =============================================================================


def test_parse_solver_fixture(solver_html):
    info = parser.parse(solver_html, "solver", ID)
    assert info.page_kind == "solver"
    assert info.contest_prob_id == ID
    assert info.num == 25730
    assert info.title == "항아리 게임"
    assert info.input_url == f"https://swexpertacademy.com{DOWN}?downType=in&contestProbId={ID}"
    assert info.output_url == f"https://swexpertacademy.com{DOWN}?downType=out&contestProbId={ID}"
    assert info.input_filename == "input7_sample.txt"
    assert info.output_filename == "output7_sample.txt"


def _solver_page(title_html: str, attachments: str = "") -> str:
    return f"<html><body><h3 class='problem_title'>{title_html}</h3>{attachments}</body></html>"


def _attach(down_type: str, filename: str, absolute: bool = True, extra: str = "") -> str:
    base = "https://swexpertacademy.com" if absolute else ""
    return (
        f"<div class='down_area'><a href='{base}{DOWN}?downType={down_type}&contestProbId={ID}{extra}'>"
        f"<span>{filename}</span><i><span class='hide'>다운로드</span></i></a></div>"
    )


BOTH = _attach("in", "input.txt") + _attach("out", "output.txt")


def test_parse_solver_title_without_box_index():
    info = parser.parse(_solver_page("1234. A+B", BOTH), "solver", ID)
    assert (info.num, info.title) == (1234, "A+B")


def test_parse_solver_title_with_extra_whitespace_and_newlines():
    info = parser.parse(_solver_page("\n  25730.   [07]\n 항아리   게임 \n", BOTH), "solver", ID)
    assert (info.num, info.title) == (25730, "항아리 게임")


def test_parse_solver_title_with_dot_inside_title():
    info = parser.parse(_solver_page("5000. 1. 2. 3.", BOTH), "solver", ID)
    assert (info.num, info.title) == (5000, "1. 2. 3.")


def test_parse_solver_missing_title_element():
    with pytest.raises(ParseError, match="h3.problem_title"):
        parser.parse(f"<html><body>{BOTH}</body></html>", "solver", ID)


def test_parse_solver_title_without_number():
    with pytest.raises(ParseError, match="번호"):
        parser.parse(_solver_page("[07] 항아리 게임", BOTH), "solver", ID)


# =============================================================================
# parse — club 페이지 (B)
# =============================================================================


def test_parse_club_fixture(club_html):
    info = parser.parse(club_html, "club", ID)
    assert info.page_kind == "club"
    assert info.num is None
    assert info.title == "항아리 게임"  # [07] 순번과 badge(D1) 제외
    assert "D1" not in info.title
    assert info.input_url.startswith("https://swexpertacademy.com" + DOWN)
    assert "downType=in" in info.input_url and "downType=out" in info.output_url
    assert "&amp;" not in info.input_url  # HTML 엔티티가 풀려 있어야 함
    assert info.input_filename == "input7_sample.txt"
    assert info.output_filename == "output7_sample.txt"


def test_parse_club_title_without_index_prefix():
    html = f"<html><body><p class='problem_title'><i></i> 그냥 제목 <span class='badge'>D2</span></p>{BOTH}</body></html>"
    info = parser.parse(html, "club", ID)
    assert info.title == "그냥 제목"


def test_parse_club_missing_title():
    with pytest.raises(ParseError, match="p.problem_title"):
        parser.parse(f"<html><body>{BOTH}</body></html>", "club", ID)


# =============================================================================
# parse — detail 페이지 (A) — p.problem_title 만 (목록 위젯 폴백은 M5 에서 삭제)
# =============================================================================


def test_parse_detail_ignores_list_widgets():
    """목록 페이지 위젯(span.week_num)만 있으면 번호를 추정하지 않는다 → (None, "") 로 --num 안내."""
    html = (
        "<html><body><div class='header-caption'>"
        "<span class='week_num'>27008.</span>"
        "<span class='week_text'><a href='#none'>A+B</a></span>"
        f"</div>{BOTH}</body></html>"
    )
    info = parser.parse(html, "detail", ID)
    assert (info.num, info.title, info.page_kind) == (None, "", "detail")


def test_parse_detail_without_title_widgets_does_not_raise():
    info = parser.parse(f"<html><body>{BOTH}</body></html>", "detail", ID)
    assert info.num is None and info.title == ""


def test_parse_unknown_page_kind():
    with pytest.raises(ParseError, match="page_kind"):
        parser.parse("<html></html>", "weird", ID)


# =============================================================================
# 첨부
# =============================================================================


def test_relative_href_is_made_absolute():
    html = _solver_page("1. x", _attach("in", "i.txt", absolute=False) + _attach("out", "o.txt", absolute=False))
    info = parser.parse(html, "solver", ID)
    assert info.input_url.startswith("https://swexpertacademy.com/")
    assert info.output_url.startswith("https://swexpertacademy.com/")


def test_down_type_is_case_insensitive():
    html = _solver_page("1. x", _attach("IN", "i.txt") + _attach("Out", "o.txt"))
    info = parser.parse(html, "solver", ID)
    assert info.input_filename == "i.txt" and info.output_filename == "o.txt"


def test_missing_output_attachment(solver_html):
    html = _solver_page("1. x", _attach("in", "input7_sample.txt"))
    with pytest.raises(AttachmentNotFound) as ei:
        parser.parse(html, "solver", ID)
    assert ei.value.found == ["input7_sample.txt"]
    assert "out" in str(ei.value)


def test_missing_input_attachment():
    html = _solver_page("1. x", _attach("out", "o.txt"))
    with pytest.raises(AttachmentNotFound) as ei:
        parser.parse(html, "solver", ID)
    assert ei.value.found == ["o.txt"]
    assert "in" in str(ei.value)


def test_no_down_area_at_all():
    with pytest.raises(AttachmentNotFound) as ei:
        parser.parse(_solver_page("1. x"), "solver", ID)
    assert ei.value.found == []
    assert "in" in str(ei.value) and "out" in str(ei.value)


def test_error_page_is_reported_as_missing_attachments(error_html):
    """오류 페이지가 parse 까지 오면 첨부 없음으로 끝난다 (ProblemNotFound 판정은 client 몫)."""
    with pytest.raises(AttachmentNotFound):
        parser.parse(error_html, "detail", ID)


def test_attachment_with_unknown_down_type_is_ignored():
    html = _solver_page("1. x", _attach("in", "i.txt") + _attach("out", "o.txt") + _attach("etc", "e.txt"))
    info = parser.parse(html, "solver", ID)
    assert info.input_filename == "i.txt" and info.output_filename == "o.txt"


def test_attachment_without_down_type_is_ignored():
    html = _solver_page(
        "1. x",
        f"<div class='down_area'><a href='{DOWN}?contestProbId={ID}'><span>x.txt</span></a></div>" + _attach("out", "o.txt"),
    )
    with pytest.raises(AttachmentNotFound) as ei:
        parser.parse(html, "solver", ID)
    assert ei.value.found == ["o.txt"]


def test_duplicate_attachment_uses_first_and_warns(caplog):
    html = _solver_page("1. x", _attach("in", "first.txt") + _attach("in", "second.txt") + _attach("out", "o.txt"))
    with caplog.at_level(logging.WARNING, logger="swea_fetcher.parser"):
        info = parser.parse(html, "solver", ID)
    assert info.input_filename == "first.txt"
    assert any("여러 개" in r.getMessage() for r in caplog.records)


def test_attachment_link_outside_down_area_is_ignored():
    html = _solver_page("1. x", f"<a href='{DOWN}?downType=in&contestProbId={ID}'>i.txt</a>" + _attach("out", "o.txt"))
    with pytest.raises(AttachmentNotFound):
        parser.parse(html, "solver", ID)


def test_attachment_filename_falls_back_to_link_text_without_span():
    html = _solver_page(
        "1. x",
        f"<div class='down_area'><a href='{DOWN}?downType=in&contestProbId={ID}'>plain_in.txt</a></div>" + _attach("out", "o.txt"),
    )
    info = parser.parse(html, "solver", ID)
    assert info.input_filename == "plain_in.txt"


def test_attachment_filename_skips_hidden_label_only():
    html = _solver_page(
        "1. x",
        f"<div class='down_area'><a href='{DOWN}?downType=in&contestProbId={ID}'><i><span class='hide'>다운로드</span></i></a></div>"
        + _attach("out", "o.txt"),
    )
    info = parser.parse(html, "solver", ID)
    assert info.input_filename != "다운로드"


def test_problem_info_is_immutable(solver_html):
    info = parser.parse(solver_html, "solver", ID)
    with pytest.raises(Exception):
        info.num = 1  # type: ignore[misc]


# =============================================================================
# M2 추가: URL 검증 강화, detail 페이지, require_attachments
# =============================================================================


@pytest.mark.parametrize(
    "bad",
    [
        f"https://swexpertacademy.com{DOWN}?downType=in&contestProbId=BAD&_menuId={MENU_ID}&_menuF=true",
        f"https://swexpertacademy.com{DOWN}?downType=in&contestProbId=&_menuId={MENU_ID}",
        f"contestProbId={ID[:10]}",
    ],
)
def test_extract_explicit_but_invalid_contest_prob_id(bad):
    with pytest.raises(InvalidInput, match="올바르지 않습니다"):
        parser.extract_contest_prob_id(bad)


@pytest.mark.parametrize(
    "url",
    [
        "https://swexpertacademy.com/main/solvingProblem/solvingProblem.do",
        "https://swexpertacademy.com/main/talk/solvingClub/problemView.do",
    ],
)
def test_extract_post_page_url_gives_specific_hint(url):
    with pytest.raises(InvalidInput, match="문제 번호"):
        parser.extract_contest_prob_id(url)


def test_parse_detail_fixture(detail_html):
    info = parser.parse(detail_html, "detail", "AWIeW7FakkUDFAVH")
    assert info.page_kind == "detail"
    assert info.num == 4014
    assert info.title == "[모의 SW 역량테스트] 활주로 건설"
    assert info.input_filename == "sample_input.txt"
    assert info.output_filename == "sample_output.txt"
    assert "downType=in" in info.input_url and "downType=out" in info.output_url
    assert "&amp;" not in info.input_url


def test_parse_detail_prefers_problem_title_over_week_widgets():
    html = (
        "<html><body><p class='problem_title'>4014. 활주로 건설 <span class='badge'>D4</span></p>"
        "<span class='week_num'>9999.</span><span class='week_text'>other</span>"
        f"{BOTH}</body></html>"
    )
    info = parser.parse(html, "detail", ID)
    assert (info.num, info.title) == (4014, "활주로 건설")


def test_parse_detail_problem_title_without_number_returns_none():
    html = (
        "<html><body><p class='problem_title'>[07] 항아리 게임</p>"
        "<span class='week_num'>27008.</span><span class='week_text'>A+B</span>"
        f"{BOTH}</body></html>"
    )
    info = parser.parse(html, "detail", ID)
    assert (info.num, info.title) == (None, "")


def test_parse_without_required_attachments():
    info = parser.parse(_solver_page("1234. A+B"), "solver", ID, require_attachments=False)
    assert (info.num, info.title) == (1234, "A+B")
    assert info.input_url is None and info.output_url is None
    assert info.input_filename is None and info.output_filename is None


def test_parse_without_required_attachments_still_returns_present_ones():
    info = parser.parse(_solver_page("1. x", _attach("in", "i.txt")), "solver", ID, require_attachments=False)
    assert info.input_filename == "i.txt" and info.output_url is None


def test_parse_require_attachments_false_still_needs_title():
    with pytest.raises(ParseError):
        parser.parse("<html></html>", "solver", ID, require_attachments=False)


def test_attachment_filename_hidden_label_only_is_empty():
    html = _solver_page(
        "1. x",
        f"<div class='down_area'><a href='{DOWN}?downType=in&contestProbId={ID}'><i><span class='hide'>다운로드</span></i></a></div>"
        + _attach("out", "o.txt"),
    )
    assert parser.parse(html, "solver", ID).input_filename == ""
