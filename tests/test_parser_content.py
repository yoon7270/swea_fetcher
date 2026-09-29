"""parser.parse_content (M12): 지문 추출·sanitize·이미지 치환. 픽스처와 합성 HTML 만 사용 (네트워크 없음)."""

from __future__ import annotations

import base64
import re

import pytest
from bs4 import BeautifulSoup

from swea_fetcher import parser
from swea_fetcher.parser import parse_content

PNG_1PX = base64.b64encode(
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
).decode()


def _page(body: str, limits: str = "<ul><li>시간 : 1초</li></ul>") -> str:
    return f'<html><body><div class="box3">{limits}</div><div class="box4">{body}</div></body></html>'


# --- 픽스처 3종 -----------------------------------------------------------------


@pytest.mark.parametrize("fixture", ["solver_html", "club_html", "detail_html"])
def test_fixtures_have_single_box3_box4(fixture, request):
    """구현 전제 고정: 픽스처마다 box3/box4 가 정확히 1개씩."""
    soup = BeautifulSoup(request.getfixturevalue(fixture), "lxml")
    assert len(soup.select(parser.SEL_LIMITS)) == 1
    assert len(soup.select(parser.SEL_BODY)) == 1


def test_solver_content(solver_html):
    c = parse_content(solver_html)
    assert c is not None
    assert "256MB" in c.limits_html and "30개 테스트케이스" in c.limits_html
    assert "플레이어는 1번 구역에서 출발" in c.body_html
    assert c.images == {}


def test_detail_content_has_inline_images(detail_html):
    c = parse_content(detail_html)
    assert c is not None
    assert "50개 테스트케이스" in c.limits_html and "256MB" in c.limits_html
    assert "활주로" in c.body_html
    assert len(c.images) == 11
    for token, ref in c.images.items():
        assert token.startswith("swea-img:")
        assert ref.error is None and ref.url is None
        assert ref.data is not None and ref.data.startswith(b"\x89PNG")
        assert f'src="{token}"' in c.body_html
    assert "data:image" not in c.body_html


def test_math_span_keeps_visible_text(solver_html):
    """수식 span 은 화면 텍스트 그대로 (data-math 의 LaTeX 가 아님)."""
    c = parse_content(solver_html)
    text = BeautifulSoup(c.body_html, "lxml").get_text().replace("\xa0", " ")
    assert "4 <= N <= 20" in text
    assert "\\le" not in c.body_html


def test_no_body_returns_none(error_html):
    assert parse_content(error_html) is None
    assert parse_content("<html><body><p>없음</p></body></html>") is None


def test_empty_body_returns_none():
    assert parse_content(_page("<p> </p><script>x()</script>")) is None


def test_limits_missing_is_ok():
    c = parse_content('<div class="box4"><p>본문</p></div>')
    assert c is not None and c.limits_html == "" and "본문" in c.body_html


# --- sanitize -------------------------------------------------------------------


def test_sanitize_removes_dangerous_markup():
    body = (
        "<p>안전 텍스트</p>"
        "<script>alert(1)</script>"
        '<img src="x" onerror="alert(1)">'
        '<iframe src="http://evil/"></iframe>'
        '<p style="font-family: Google Sans; color:red" class="x" onclick="y()">스타일</p>'
        '<a href="javascript:alert(1)">링크텍스트</a>'
        '<svg onload="alert(1)"><circle/></svg>'
        "<!-- 주석 -->"
        '<form action="/x"><input name="a"><button>b</button></form>'
        '<span class="hide">숨김</span>'
        "<blink>깜빡</blink>"
    )
    c = parse_content(_page(body))
    out = c.body_html.lower()
    for bad in ("<script", "onerror", "onclick", "<iframe", "style=", "class=", "href", "javascript", "<svg", "onload", "<!--", "<form", "<input", "<button", "<a ", "<blink", "숨김"):
        assert bad not in out, bad
    assert "안전 텍스트" in c.body_html and "링크텍스트" in c.body_html and "깜빡" in c.body_html


def test_sanitize_keeps_allowed_tags_and_table_span():
    body = '<table><tr><th colspan="2" style="x">h</th></tr><tr><td rowspan="2" data-x="1">a</td><td>b</td></tr></table><sup>2</sup><pre> a  b\n c</pre>'
    c = parse_content(_page(body))
    assert 'colspan="2"' in c.body_html and 'rowspan="2"' in c.body_html
    assert "style" not in c.body_html and "data-x" not in c.body_html
    assert "<sup>2</sup>" in c.body_html
    assert " a  b\n c" in c.body_html  # pre 안 공백 보존


def test_empty_paragraphs_removed_and_br_collapsed():
    c = parse_content(_page("<p>가</p><p> </p><p>&nbsp;</p><p>나<br><br><br><br>다</p>"))
    assert c.body_html.count("<p>") == 2
    assert c.body_html.count("<br/>") == 2


def test_output_only_contains_allowed_tags(detail_html):
    c = parse_content(detail_html)
    tags = set(re.findall(r"<([a-zA-Z0-9]+)", c.body_html + c.limits_html))
    assert tags <= parser._ALLOWED_TAGS


# --- 이미지 ---------------------------------------------------------------------


def test_relative_url_becomes_absolute_ref_without_data():
    c = parse_content(_page('<img src="/upload/a.png" alt="그림"><img src="pics/b.png">'))
    a, b = c.images["swea-img:0"], c.images["swea-img:1"]
    assert a.url == "https://swexpertacademy.com/upload/a.png" and a.data is None and a.error is None and a.alt == "그림"
    assert b.url == "https://swexpertacademy.com/pics/b.png"
    assert b.alt == "이미지 2"


def test_protocol_relative_swea_host_allowed():
    c = parse_content(_page('<img src="//www.swexpertacademy.com/x.png">'))
    assert c.images["swea-img:0"].url == "https://www.swexpertacademy.com/x.png"


@pytest.mark.parametrize("src", ["http://evil.example.com/t.gif", "//evil.example.com/t.gif", "https://swexpertacademy.com.evil.io/a.png"])
def test_external_host_image_is_error_and_has_no_url(src):
    c = parse_content(_page(f'<img src="{src}">'))
    ref = c.images["swea-img:0"]
    assert ref.url is None and ref.data is None and ref.error == "외부 이미지 생략"


@pytest.mark.parametrize("src", ["file:///C:/secret.png", "javascript:alert(1)", "ftp://x/y.png", "", "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="])
def test_bad_scheme_or_type_image_is_error(src):
    c = parse_content(_page(f'<img src="{src}">'))
    ref = c.images["swea-img:0"]
    assert ref.error and ref.data is None and ref.url is None


def test_broken_base64_is_error_not_exception():
    c = parse_content(_page('<img src="data:image/png;base64,@@@not-base64@@@"><p>본문</p>'))
    assert c.images["swea-img:0"].error == "이미지 디코드 실패"
    assert "본문" in c.body_html


def test_data_uri_decoded():
    c = parse_content(_page(f'<img src="data:image/png;base64,{PNG_1PX}">'))
    assert c.images["swea-img:0"].data.startswith(b"\x89PNG")


def test_image_size_limit(monkeypatch):
    monkeypatch.setattr(parser, "IMG_MAX_BYTES", 10)
    c = parse_content(_page(f'<img src="data:image/png;base64,{PNG_1PX}">'))
    assert "5MB" in c.images["swea-img:0"].error


def test_image_count_limit(monkeypatch):
    monkeypatch.setattr(parser, "IMG_MAX_COUNT", 2)
    c = parse_content(_page(f'<img src="data:image/png;base64,{PNG_1PX}">' * 3))
    assert [bool(c.images[f"swea-img:{i}"].error) for i in range(3)] == [False, False, True]


def test_image_total_size_limit(monkeypatch):
    monkeypatch.setattr(parser, "IMG_MAX_TOTAL", 30)
    c = parse_content(_page(f'<img src="data:image/png;base64,{PNG_1PX}">' * 2))
    assert c.images["swea-img:0"].error is None and "합계" in c.images["swea-img:1"].error


def test_remote_image_count_limit(monkeypatch):
    monkeypatch.setattr(parser, "REMOTE_IMG_MAX", 2)
    c = parse_content(_page("".join(f'<img src="/i{i}.png">' for i in range(3))))
    assert [c.images[f"swea-img:{i}"].error is None for i in range(3)] == [True, True, False]


def test_parse_content_makes_no_network_call(detail_html, monkeypatch):
    import requests

    def blocked(*_a, **_k):
        raise AssertionError("parse_content 는 네트워크를 쓰지 않습니다")

    monkeypatch.setattr(requests.Session, "request", blocked)
    assert parse_content(detail_html) is not None
