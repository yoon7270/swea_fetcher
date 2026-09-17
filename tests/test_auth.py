"""auth: 세션 캐시, 실패 카운터, 로그인, get_session. 네트워크는 FakeSession 으로 대체."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import requests

from swea_fetcher import auth
from swea_fetcher.errors import LoginFailed, LoginLocked, MfaRequired, NetworkError
from tests.conftest import DUMMY_ID, DUMMY_PW, FakeResponse, FakeSession, login_redirect


def ok_login(message: str = "") -> FakeResponse:
    return FakeResponse(200, json_data={"success": True, "message": message, "returnPath": "/"})


def fail_login(message: str) -> FakeResponse:
    return FakeResponse(200, json_data={"success": False, "message": message})


def login_page() -> FakeResponse:
    r = FakeResponse(200, text="<html>login</html>")
    return r


# =============================================================================
# 세션 캐시
# =============================================================================


def test_save_and_load_session_roundtrip(settings):
    s1 = FakeSession()
    s1.cookies.set("SESSION", "abc123", domain="swexpertacademy.com")
    auth.save_session(s1, settings)
    assert settings.session_file.is_file()
    assert json.loads(settings.session_file.read_text(encoding="utf-8")) == {"SESSION": "abc123"}

    s2 = FakeSession()
    assert auth.load_session(s2, settings) is True
    assert s2.cookies.get("SESSION") == "abc123"


def test_save_session_creates_config_dir(settings, tmp_path):
    from dataclasses import replace

    s = replace(settings, config_dir=tmp_path / "new" / "deep")
    auth.save_session(FakeSession(), s)
    assert s.session_file.is_file()


def test_load_session_missing_file(settings):
    assert auth.load_session(FakeSession(), settings) is False


def test_load_session_empty_cookies_returns_false(settings):
    settings.session_file.write_text("{}", encoding="utf-8")
    assert auth.load_session(FakeSession(), settings) is False


@pytest.mark.parametrize("content", ["not json", "[1,2]", '"str"', ""])
def test_load_session_corrupt_file_is_ignored(settings, content, caplog):
    settings.session_file.write_text(content, encoding="utf-8")
    s = FakeSession()
    with caplog.at_level(logging.WARNING, logger="swea_fetcher.auth"):
        assert auth.load_session(s, settings) is False
    assert len(s.cookies) == 0


def test_clear_session(settings):
    settings.session_file.write_text("{}", encoding="utf-8")
    auth.clear_session(settings)
    assert not settings.session_file.exists()
    auth.clear_session(settings)  # 없을 때도 예외 없음


def test_save_session_does_not_log_cookie_values(settings, caplog):
    s = FakeSession()
    s.cookies.set("SESSION", "supersecretcookie")
    with caplog.at_level(logging.DEBUG, logger="swea_fetcher.auth"):
        auth.save_session(s, settings)
    assert "supersecretcookie" not in caplog.text


# =============================================================================
# 실패 카운터
# =============================================================================


def test_failure_counter_roundtrip(tmp_path):
    p = tmp_path / "a" / "login_state.json"
    assert auth._read_failures(p) == 0
    auth._write_failures(p, 2)
    assert auth._read_failures(p) == 2


@pytest.mark.parametrize("content", ["garbage", "[]", "{}", '{"consecutive_failures": "x"}'])
def test_failure_counter_corrupt(tmp_path, content):
    p = tmp_path / "login_state.json"
    p.write_text(content, encoding="utf-8")
    assert auth._read_failures(p) == 0


# =============================================================================
# is_logged_in
# =============================================================================


def test_is_logged_in_200():
    s = FakeSession([FakeResponse(200, text="<html>me</html>")])
    assert auth.is_logged_in(s) is True
    assert s.calls[0]["allow_redirects"] is False
    assert s.calls[0]["url"] == auth.SESSION_CHECK_URL


def test_is_logged_in_redirect_to_login_page():
    s = FakeSession([login_redirect()])
    assert auth.is_logged_in(s) is False


def test_is_logged_in_redirect_elsewhere_means_logged_out():  # M8: 어떤 리다이렉트든 세션 없음 → 재로그인
    s = FakeSession([FakeResponse(302, headers={"Location": "https://swexpertacademy.com/main/"})])
    assert auth.is_logged_in(s) is False


def test_is_logged_in_500_is_network_error():
    s = FakeSession([FakeResponse(500, text="oops")])
    with pytest.raises(NetworkError):
        auth.is_logged_in(s)


def test_is_logged_in_connection_error():
    s = FakeSession([requests.ConnectionError("down")])
    with pytest.raises(NetworkError):
        auth.is_logged_in(s)


# =============================================================================
# login
# =============================================================================


def test_login_success_posts_form_and_saves_session(settings):
    s = FakeSession([login_page(), ok_login()])
    s.cookies.set("SESSION", "tok")
    auth.login(s, settings)

    get_call, post_call = s.calls
    assert get_call["method"] == "GET" and get_call["url"] == auth.LOGIN_PAGE_URL
    assert post_call["method"] == "POST" and post_call["url"] == auth.LOGIN_URL
    assert post_call["data"] == {"id": DUMMY_ID, "pwd": DUMMY_PW, "lang": "ko_KR", "clientTimezone": "Asia/Seoul"}
    assert post_call["headers"]["Referer"] == auth.LOGIN_PAGE_URL
    assert post_call["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert post_call["allow_redirects"] is False
    assert "timeout" in post_call

    assert json.loads(settings.session_file.read_text(encoding="utf-8")) == {"SESSION": "tok"}
    assert auth._read_failures(settings.login_state_file) == 0


def test_login_success_resets_failure_counter(settings):
    auth._write_failures(settings.login_state_file, 2)
    s = FakeSession([login_page(), ok_login()])
    auth.login(s, settings)
    assert auth._read_failures(settings.login_state_file) == 0


def test_login_temp_pwd_is_success(settings):
    s = FakeSession([login_page(), ok_login("tempPwd")])
    auth.login(s, settings)
    assert settings.session_file.is_file()


def test_login_mfa(settings):
    s = FakeSession([login_page(), ok_login("mfa")])
    with pytest.raises(MfaRequired) as ei:
        auth.login(s, settings)
    assert ei.value.code == "mfa"
    assert not settings.session_file.exists()
    assert auth._read_failures(settings.login_state_file) == 0  # 자격 오류가 아님


@pytest.mark.parametrize(
    "code, expect_in_msg",
    [
        ("LoginIdFail", "존재하지 않는 ID"),
        ("LoginIdPwdFail", "1회"),
        ("LoginPwdErrorCount", "잠겼습니다"),
        ("DormancyAccount", "휴면"),
        ("BlockedId", "BlockedId"),  # 매핑에 없는 코드는 코드 그대로 노출
    ],
)
def test_login_failure_codes(settings, code, expect_in_msg):
    s = FakeSession([login_page(), fail_login(code)])
    with pytest.raises(LoginFailed) as ei:
        auth.login(s, settings)
    assert ei.value.code == code
    assert expect_in_msg in str(ei.value)
    assert auth._read_failures(settings.login_state_file) == 1
    assert not settings.session_file.exists()


def test_login_failure_increments_counter(settings):
    auth._write_failures(settings.login_state_file, 1)
    s = FakeSession([login_page(), fail_login("LoginIdPwdFail")])
    with pytest.raises(LoginFailed) as ei:
        auth.login(s, settings)
    assert auth._read_failures(settings.login_state_file) == 2
    assert "2회" in str(ei.value)


def test_login_failure_with_empty_message_code(settings):
    s = FakeSession([login_page(), FakeResponse(200, json_data={"success": False})])
    with pytest.raises(LoginFailed) as ei:
        auth.login(s, settings)
    assert ei.value.code == "unknown"


def test_login_locked_after_three_failures_makes_no_request(settings):
    auth._write_failures(settings.login_state_file, 3)
    s = FakeSession()
    with pytest.raises(LoginLocked) as ei:
        auth.login(s, settings)
    assert s.calls == []
    assert str(settings.login_state_file) in str(ei.value)


def test_login_locked_check_precedes_process_guard(settings):
    auth._write_failures(settings.login_state_file, 5)
    with pytest.raises(LoginLocked):
        auth.login(FakeSession(), settings)
    # 잠금으로 막힌 시도는 프로세스 가드를 소비하지 않는다
    assert auth._login_attempted is False


def test_login_only_once_per_process(settings):
    s = FakeSession([login_page(), fail_login("LoginIdPwdFail")])
    with pytest.raises(LoginFailed):
        auth.login(s, settings)
    s2 = FakeSession()
    with pytest.raises(LoginFailed, match="이미"):
        auth.login(s2, settings)
    assert s2.calls == []
    assert auth._read_failures(settings.login_state_file) == 1  # 두 번째는 카운트하지 않음


def test_login_guard_is_set_even_after_success(settings):
    s = FakeSession([login_page(), ok_login()])
    auth.login(s, settings)
    with pytest.raises(LoginFailed, match="이미"):
        auth.login(FakeSession(), settings)


def test_login_empty_body(settings):
    s = FakeSession([login_page(), FakeResponse(200, text="   ")])
    with pytest.raises(LoginFailed, match="비어"):
        auth.login(s, settings)
    assert auth._read_failures(settings.login_state_file) == 0


def test_login_non_json_body(settings, login_html):
    s = FakeSession([login_page(), FakeResponse(200, text=login_html)])
    with pytest.raises(LoginFailed, match="해석"):
        auth.login(s, settings)


def test_login_network_error_on_get(settings):
    s = FakeSession([requests.ConnectionError("down")])
    with pytest.raises(NetworkError):
        auth.login(s, settings)
    assert auth._read_failures(settings.login_state_file) == 0


def test_login_network_error_on_post(settings):
    s = FakeSession([login_page(), requests.Timeout("slow")])
    with pytest.raises(NetworkError):
        auth.login(s, settings)


def test_login_never_logs_password(settings, caplog):
    s = FakeSession([login_page(), fail_login("LoginIdPwdFail")])
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(LoginFailed) as ei:
            auth.login(s, settings)
    assert DUMMY_PW not in caplog.text
    assert DUMMY_PW not in str(ei.value)


# =============================================================================
# get_session
# =============================================================================


def _patch_session_factory(monkeypatch, fake: FakeSession):
    monkeypatch.setattr(auth.requests, "Session", lambda: fake)


def test_get_session_reuses_valid_cache(settings, monkeypatch):
    settings.session_file.write_text(json.dumps({"SESSION": "cached"}), encoding="utf-8")
    fake = FakeSession([FakeResponse(200, text="me")])  # is_logged_in
    _patch_session_factory(monkeypatch, fake)

    s = auth.get_session(settings)
    assert s is fake
    assert fake.cookies.get("SESSION") == "cached"
    assert [c["url"] for c in fake.calls] == [auth.SESSION_CHECK_URL]
    assert fake.headers["User-Agent"] == auth.USER_AGENT
    assert "Accept-Language" in fake.headers
    assert auth._login_attempted is False


def test_get_session_logs_in_when_no_cache(settings, monkeypatch):
    fake = FakeSession([login_page(), ok_login()])
    _patch_session_factory(monkeypatch, fake)
    auth.get_session(settings)
    assert [c["url"] for c in fake.calls] == [auth.LOGIN_PAGE_URL, auth.LOGIN_URL]


def test_get_session_relogs_in_when_cache_expired(settings, monkeypatch):
    settings.session_file.write_text(json.dumps({"SESSION": "stale"}), encoding="utf-8")
    fake = FakeSession([login_redirect(), login_page(), ok_login()])
    _patch_session_factory(monkeypatch, fake)

    def on_login_post(method, url, kw):
        # 로그인 POST 시점에는 오래된 쿠키가 지워져 있어야 한다
        if url == auth.LOGIN_URL:
            assert fake.cookies.get("SESSION") != "stale"
        return fake.responses.pop(0)

    fake.handler = on_login_post
    auth.get_session(settings)
    assert [c["url"] for c in fake.calls] == [auth.SESSION_CHECK_URL, auth.LOGIN_PAGE_URL, auth.LOGIN_URL]


def test_get_session_propagates_login_failure(settings, monkeypatch):
    fake = FakeSession([login_page(), fail_login("LoginIdFail")])
    _patch_session_factory(monkeypatch, fake)
    with pytest.raises(LoginFailed):
        auth.get_session(settings)


def test_login_failure_unknown_code_with_braces_does_not_crash(settings):
    s = FakeSession([login_page(), fail_login("weird{code}")])
    with pytest.raises(LoginFailed) as ei:
        auth.login(s, settings)
    assert "weird{code}" in str(ei.value)
    assert auth._read_failures(settings.login_state_file) == 1
