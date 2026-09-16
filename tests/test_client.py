"""client: 도메인 화이트리스트, 재시도, 세션 만료 재로그인, 문제 페이지 폴백, 첨부 다운로드."""

from __future__ import annotations

import pytest
import requests

from swea_fetcher import client
from swea_fetcher.errors import LoginFailed, NetworkError, ProblemNotFound, SessionExpired
from tests.conftest import CONTEST_PROB_ID, FakeResponse, FakeSession, login_redirect

ID = CONTEST_PROB_ID
SOLVER_OK = "<html><h3 class=\"problem_title\">25730. 항아리 게임</h3></html>"
DETAIL_OK = "<html><span class='week_num'>1.</span></html>"
ERROR_PAGE = "<html><head><title>::: Error :::</title></head><body>죄송합니다</body></html>"


@pytest.fixture
def no_login(monkeypatch):
    """auth.login 을 호출 기록만 남기는 스텁으로 바꾼다."""
    calls: list = []
    monkeypatch.setattr(client.auth, "login", lambda session, settings: calls.append((session, settings)))
    return calls


# =============================================================================
# _check_host / _request
# =============================================================================


@pytest.mark.parametrize(
    "url",
    [
        "https://swexpertacademy.com/main/x",
        "https://www.swexpertacademy.com/main/x",
        "HTTPS://SWEXPERTACADEMY.COM/main/x",
    ],
)
def test_check_host_allows(url):
    client._check_host(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/main/x",
        "https://swexpertacademy.com.evil.com/x",
        "https://evil.com/?u=swexpertacademy.com",
        "/main/relative/only",
        "",
    ],
)
def test_check_host_rejects(url):
    with pytest.raises(NetworkError, match="도메인"):
        client._check_host(url)


def test_request_forces_utf8_and_defaults():
    s = FakeSession([FakeResponse(200, text="ok")])
    r = client._request(s, "GET", client.DETAIL_URL)
    assert r.encoding == "utf-8"
    call = s.calls[0]
    assert call["allow_redirects"] is False
    assert call["timeout"] == client.TIMEOUT


def test_request_caller_kwargs_override_defaults():
    s = FakeSession([FakeResponse(200, text="ok")])
    client._request(s, "GET", client.DETAIL_URL, timeout=3)
    assert s.calls[0]["timeout"] == 3


def test_request_rejects_foreign_host_before_sending():
    s = FakeSession()
    with pytest.raises(NetworkError):
        client._request(s, "GET", "https://evil.com/")
    assert s.calls == []


def test_request_retries_on_connection_error_then_succeeds():
    s = FakeSession([requests.ConnectionError("a"), requests.Timeout("b"), FakeResponse(200, text="ok")])
    r = client._request(s, "GET", client.DETAIL_URL)
    assert r.text == "ok"
    assert len(s.calls) == 3


def test_request_gives_up_after_retries():
    s = FakeSession([requests.ConnectionError("a")] * 3)
    with pytest.raises(NetworkError, match="네트워크"):
        client._request(s, "GET", client.DETAIL_URL)
    assert len(s.calls) == len(client.RETRY_DELAYS) + 1


def test_request_other_request_exception_is_not_retried():
    s = FakeSession([requests.TooManyRedirects("loop")])
    with pytest.raises(NetworkError, match="요청 실패"):
        client._request(s, "GET", client.DETAIL_URL)
    assert len(s.calls) == 1


def test_request_http_error_status_is_returned_not_raised():
    s = FakeSession([FakeResponse(500, text="boom")])
    r = client._request(s, "GET", client.DETAIL_URL)
    assert r.status_code == 500
    assert len(s.calls) == 1


def test_request_login_redirect_raises_session_expired():
    s = FakeSession([login_redirect()])
    with pytest.raises(SessionExpired):
        client._request(s, "GET", client.DETAIL_URL)


def test_request_other_redirect_is_returned():
    s = FakeSession([FakeResponse(302, headers={"Location": "https://swexpertacademy.com/main/"})])
    r = client._request(s, "GET", client.DETAIL_URL)
    assert r.status_code == 302


# =============================================================================
# _with_relogin
# =============================================================================


def test_with_relogin_passthrough(settings, no_login):
    assert client._with_relogin(FakeSession(), settings, lambda: "v") == "v"
    assert no_login == []


def test_with_relogin_retries_once_after_login(settings, no_login):
    s = FakeSession()
    s.cookies.set("SESSION", "stale")
    n = {"i": 0}

    def fn():
        n["i"] += 1
        if n["i"] == 1:
            raise SessionExpired("x")
        return "second"

    assert client._with_relogin(s, settings, fn) == "second"
    assert n["i"] == 2
    assert len(no_login) == 1
    assert s.cookies.get("SESSION") is None  # 재로그인 전에 쿠키 초기화


def test_with_relogin_fails_if_still_expired(settings, no_login):
    def fn():
        raise SessionExpired("x")

    with pytest.raises(LoginFailed, match="재로그인"):
        client._with_relogin(FakeSession(), settings, fn)
    assert len(no_login) == 1


def test_with_relogin_propagates_login_error(settings, monkeypatch):
    def bad_login(session, settings):
        raise LoginFailed("nope")

    monkeypatch.setattr(client.auth, "login", bad_login)

    def fn():
        raise SessionExpired("x")

    with pytest.raises(LoginFailed, match="nope"):
        client._with_relogin(FakeSession(), settings, fn)


# =============================================================================
# fetch_problem_page
# =============================================================================


def test_fetch_solver_success(settings, no_login):
    s = FakeSession([FakeResponse(200, text=SOLVER_OK)])
    html, kind = client.fetch_problem_page(s, settings, ID)
    assert (html, kind) == (SOLVER_OK, "solver")
    call = s.calls[0]
    assert call["method"] == "POST" and call["url"] == client.SOLVER_URL
    assert call["data"]["contestProbId"] == ID
    assert call["data"]["categoryType"] == "BOX"
    assert call["data"]["isPostMethod"] == "Y"
    assert "Referer" in call["headers"]
    assert len(s.calls) == 1


def test_fetch_falls_back_to_detail_on_error_page(settings, no_login):
    s = FakeSession([FakeResponse(200, text=ERROR_PAGE), FakeResponse(200, text=DETAIL_OK)])
    html, kind = client.fetch_problem_page(s, settings, ID)
    assert (html, kind) == (DETAIL_OK, "detail")
    assert s.calls[1]["method"] == "GET"
    assert s.calls[1]["url"] == client.DETAIL_URL
    assert s.calls[1]["params"] == {"contestProbId": ID}


def test_fetch_falls_back_when_solver_lacks_title_marker(settings, no_login):
    s = FakeSession([FakeResponse(200, text="<html>no title here</html>"), FakeResponse(200, text=DETAIL_OK)])
    _, kind = client.fetch_problem_page(s, settings, ID)
    assert kind == "detail"


def test_fetch_falls_back_when_solver_non_200(settings, no_login):
    s = FakeSession([FakeResponse(405, text=SOLVER_OK), FakeResponse(200, text=DETAIL_OK)])
    _, kind = client.fetch_problem_page(s, settings, ID)
    assert kind == "detail"


def test_fetch_solver_error_page_with_marker_is_not_trusted(settings, no_login):
    """오류 페이지에 우연히 problem_title 문자열이 있어도 solver 로 인정하지 않는다."""
    fake = ERROR_PAGE.replace("<body>", '<body><style>.problem_title{}</style><h3 class="problem_title">x</h3>')
    s = FakeSession([FakeResponse(200, text=fake), FakeResponse(200, text=DETAIL_OK)])
    _, kind = client.fetch_problem_page(s, settings, ID)
    assert kind == "detail"


def test_fetch_both_error_pages_raises_not_found(settings, no_login, error_html):
    s = FakeSession([FakeResponse(200, text=error_html), FakeResponse(200, text=error_html)])
    with pytest.raises(ProblemNotFound) as ei:
        client.fetch_problem_page(s, settings, ID)
    assert ID in str(ei.value)


def test_fetch_detail_non_200_raises_not_found(settings, no_login):
    s = FakeSession([FakeResponse(200, text=ERROR_PAGE), FakeResponse(404, text="nf")])
    with pytest.raises(ProblemNotFound):
        client.fetch_problem_page(s, settings, ID)


def test_fetch_relogins_once_on_session_expiry(settings, no_login):
    s = FakeSession([login_redirect(), FakeResponse(200, text=SOLVER_OK)])
    _, kind = client.fetch_problem_page(s, settings, ID)
    assert kind == "solver"
    assert len(no_login) == 1
    assert [c["method"] for c in s.calls] == ["POST", "POST"]


def test_fetch_session_still_expired_after_relogin(settings, no_login):
    s = FakeSession([login_redirect(), login_redirect()])
    with pytest.raises(LoginFailed):
        client.fetch_problem_page(s, settings, ID)
    assert len(no_login) == 1


def test_fetch_network_error_propagates(settings, no_login):
    s = FakeSession([requests.ConnectionError("x")] * 3)
    with pytest.raises(NetworkError):
        client.fetch_problem_page(s, settings, ID)


def test_fetch_uses_real_error_fixture_for_detail_fallback(settings, no_login, error_html, solver_html):
    s = FakeSession([FakeResponse(200, text=error_html), FakeResponse(200, text=solver_html)])
    _, kind = client.fetch_problem_page(s, settings, ID)
    assert kind == "detail"


# =============================================================================
# download
# =============================================================================


ABS_IN = f"https://swexpertacademy.com/main/common/contestProb/contestProbDown.do?downType=in&contestProbId={ID}"


def test_download_bytes():
    s = FakeSession([FakeResponse(200, content=b"3\n1 2\n", headers={"Content-Type": "application/octet-stream"})])
    assert client.download(s, ABS_IN) == b"3\n1 2\n"
    assert s.calls[0]["headers"]["Referer"] == client.SOLVER_URL
    assert s.calls[0]["url"] == ABS_IN


def test_download_relative_url_is_joined_to_base():
    s = FakeSession([FakeResponse(200, content=b"x")])
    client.download(s, "/main/common/contestProb/contestProbDown.do?downType=in&contestProbId=" + ID)
    assert s.calls[0]["url"].startswith("https://swexpertacademy.com/main/common/")


def test_download_rejects_foreign_host():
    s = FakeSession()
    with pytest.raises(NetworkError, match="도메인"):
        client.download(s, "https://evil.com/file.txt")
    assert s.calls == []


def test_download_binary_starting_with_whitespace_is_ok():
    s = FakeSession([FakeResponse(200, content=b"  \n1 2\n", headers={"Content-Type": "text/plain"})])
    assert client.download(s, ABS_IN) == b"  \n1 2\n"


def test_download_html_content_type_is_session_expired():
    s = FakeSession([FakeResponse(200, content=b"login", headers={"Content-Type": "text/html;charset=UTF-8"})])
    with pytest.raises(SessionExpired):
        client.download(s, ABS_IN)


def test_download_html_body_without_content_type_is_session_expired():
    s = FakeSession([FakeResponse(200, content=b"\n <html>login</html>")])
    with pytest.raises(SessionExpired):
        client.download(s, ABS_IN)


def test_download_non_200_is_network_error():
    s = FakeSession([FakeResponse(404, content=b"")])
    with pytest.raises(NetworkError, match="404"):
        client.download(s, ABS_IN)


def test_download_302_to_login_is_session_expired():
    s = FakeSession([login_redirect()])
    with pytest.raises(SessionExpired):
        client.download(s, ABS_IN)


def test_download_with_settings_relogins_once(settings, no_login):
    s = FakeSession([login_redirect(), FakeResponse(200, content=b"data")])
    assert client.download(s, ABS_IN, settings) == b"data"
    assert len(no_login) == 1
    assert len(s.calls) == 2


def test_download_with_settings_fails_after_relogin(settings, no_login):
    s = FakeSession([FakeResponse(200, content=b"<html>", headers={"Content-Type": "text/html"})] * 2)
    with pytest.raises(LoginFailed):
        client.download(s, ABS_IN, settings)
    assert len(no_login) == 1


def test_download_empty_body_is_returned_as_is():
    s = FakeSession([FakeResponse(200, content=b"", headers={"Content-Type": "application/octet-stream"})])
    assert client.download(s, ABS_IN) == b""
