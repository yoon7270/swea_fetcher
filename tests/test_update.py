"""update: 버전 비교, 캐시(24h), 끄기 스위치, 조회 실패 무음, CLI 알림·--no-update-check (M10 §2).

`_no_network` autouse 는 그대로 둔다. `check()` 는 `update.fetch_latest` 를 monkeypatch 로 흉내 내고,
`fetch_latest` 자체는 모듈 import 시점에 잡아 둔 원본을 FakeSession 으로만 호출한다 (실제 전송은 계속 차단됨).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import requests

from swea_fetcher import __version__, cli, config, update
from swea_fetcher.update import UpdateInfo, check, fetch_latest as _real_fetch_latest, notice, parse_version
from tests.conftest import FakeResponse, FakeSession

NOW = datetime(2026, 9, 18, 12, 0, 0)


def _bump(v: str, i: int = 2, by: int = 1) -> str:
    parts = [int(x) for x in v.split(".")]
    parts[i] += by
    return ".".join(str(x) for x in parts)


NEWER = _bump(__version__)
OLDER = "0.0.1"


@pytest.fixture
def fetch(monkeypatch):
    """update.fetch_latest 대역. st['result'] 를 돌려주거나 st['raise'] 를 던진다. 호출 횟수 기록."""
    st = {"result": (NEWER, "https://github.com/x/releases/tag/v" + NEWER), "raise": None, "calls": 0}

    def fake(timeout=update.TIMEOUT, session=None):
        st["calls"] += 1
        if st["raise"]:
            raise st["raise"]
        return st["result"]

    monkeypatch.setattr(update, "fetch_latest", fake)
    return st


# =============================================================================
# parse_version / UpdateInfo
# =============================================================================


@pytest.mark.parametrize(
    "s, expected",
    [("v0.4.1", (0, 4, 1)), ("0.10.0", (0, 10, 0)), ("V1.2", (1, 2)), ("", (0,)), (None, (0,)), ("release-3", (3,))],
)
def test_parse_version(s, expected):
    assert parse_version(s) == expected


@pytest.mark.parametrize("latest, newer", [(NEWER, True), (__version__, False), (OLDER, False), ("v" + NEWER, True), ("0.10.0", parse_version("0.10.0") > parse_version(__version__))])
def test_is_newer(latest, newer):
    assert UpdateInfo(__version__, latest, "u").is_newer is newer


# =============================================================================
# 캐시 / 끄기
# =============================================================================


def test_cache_roundtrip_and_merge(config_dir):
    assert update.read_cache(config_dir) == {}
    update.write_cache(config_dir, latest="1.0.0", url="u")
    update.write_cache(config_dir, checked_at="t")
    assert update.read_cache(config_dir) == {"latest": "1.0.0", "url": "u", "checked_at": "t"}


@pytest.mark.parametrize("content", ["garbage", "[1]", ""])
def test_cache_corrupt_is_empty(config_dir, content):
    update.cache_path(config_dir).write_text(content, encoding="utf-8")
    assert update.read_cache(config_dir) == {}


def test_write_cache_creates_dir(tmp_path):
    d = tmp_path / "new" / "cfg"
    update.write_cache(d, latest="1")
    assert update.read_cache(d) == {"latest": "1"}


@pytest.mark.parametrize("value, disabled", [("1", True), ("true", True), ("yes", True), ("0", False), ("false", False), ("no", False), ("", False), ("  ", False)])
def test_is_disabled_env(config_dir, monkeypatch, value, disabled):
    monkeypatch.setenv(update.DISABLE_ENV, value)
    assert update.is_disabled(config_dir) is disabled


def test_set_disabled_cache(config_dir, monkeypatch):
    monkeypatch.delenv(update.DISABLE_ENV, raising=False)
    assert update.is_disabled(config_dir) is False
    update.set_disabled(config_dir, True)
    assert update.is_disabled(config_dir) is True
    update.set_disabled(config_dir, False)
    assert update.is_disabled(config_dir) is False


# =============================================================================
# check()
# =============================================================================


def test_check_fetches_and_caches_when_no_cache(config_dir, fetch):
    info = check(config_dir, now=NOW)
    assert fetch["calls"] == 1
    assert info == UpdateInfo(__version__, NEWER, fetch["result"][1]) and info.is_newer
    cache = update.read_cache(config_dir)
    assert cache["latest"] == NEWER and cache["url"] == fetch["result"][1]
    assert cache["checked_at"] == NOW.isoformat(timespec="seconds")


def test_check_uses_fresh_cache_without_http(config_dir, fetch):
    update.write_cache(config_dir, latest="9.9.9", url="cached-url", checked_at=(NOW - timedelta(hours=23)).isoformat())
    info = check(config_dir, now=NOW)
    assert fetch["calls"] == 0
    assert (info.latest, info.url) == ("9.9.9", "cached-url")


def test_check_refetches_when_cache_stale(config_dir, fetch):
    update.write_cache(config_dir, latest="9.9.9", url="old", checked_at=(NOW - timedelta(hours=25)).isoformat())
    info = check(config_dir, now=NOW)
    assert fetch["calls"] == 1 and info.latest == NEWER
    assert update.read_cache(config_dir)["latest"] == NEWER


def test_check_bad_checked_at_refetches(config_dir, fetch):
    update.write_cache(config_dir, latest="9.9.9", url="old", checked_at="not-a-date")
    check(config_dir, now=NOW)
    assert fetch["calls"] == 1


def test_check_force_ignores_fresh_cache_and_disabled(config_dir, fetch, monkeypatch):
    monkeypatch.setenv(update.DISABLE_ENV, "1")
    update.write_cache(config_dir, latest="9.9.9", url="old", checked_at=NOW.isoformat())
    assert check(config_dir, now=NOW) is None
    info = check(config_dir, now=NOW, force=True)
    assert fetch["calls"] == 1 and info.latest == NEWER


def test_check_disabled_by_env_or_cache(config_dir, fetch, monkeypatch):
    monkeypatch.setenv(update.DISABLE_ENV, "1")
    assert check(config_dir) is None
    monkeypatch.delenv(update.DISABLE_ENV)
    update.set_disabled(config_dir, True)
    assert check(config_dir) is None
    assert fetch["calls"] == 0


@pytest.mark.parametrize("exc", [requests.Timeout("slow"), requests.HTTPError("401"), ValueError("tag_name 없음"), RuntimeError("x")])
def test_check_failure_is_silent(config_dir, fetch, exc):
    fetch["raise"] = exc
    assert check(config_dir, now=NOW) is None
    cache = update.read_cache(config_dir)
    assert cache["checked_at"] == NOW.isoformat(timespec="seconds") and "latest" not in cache
    assert fetch["calls"] == 1


def test_check_failure_backs_off_for_a_day_even_without_prior_success(config_dir, fetch):
    """모듈 주석: "실패해도 checked_at 은 갱신해 하루 동안 재시도하지 않는다 (오프라인 환경 배려)".
    한 번도 성공한 적이 없는(캐시에 latest 없음) 오프라인/비공개 환경에서도 지켜져야 한다."""
    fetch["raise"] = requests.Timeout("offline")
    assert check(config_dir, now=NOW) is None
    assert check(config_dir, now=NOW + timedelta(hours=1)) is None
    assert fetch["calls"] == 1, "실패 1시간 뒤에 다시 조회함 — 매 명령마다 타임아웃(최대 6초)을 기다리게 됨"


def test_check_fresh_checked_at_without_latest_is_none_and_no_http(config_dir, fetch):
    """W1 회귀: 실패 직후 캐시 상태(checked_at 만 있음)에서 하루 안에는 조회하지 않고 None."""
    update.write_cache(config_dir, checked_at=(NOW - timedelta(hours=23)).isoformat())
    assert check(config_dir, now=NOW) is None
    assert fetch["calls"] == 0
    # 하루가 지나면 다시 조회한다
    assert check(config_dir, now=NOW + timedelta(hours=2)).latest == NEWER
    assert fetch["calls"] == 1


def test_check_failure_with_stale_cache_returns_cached(config_dir, fetch):
    update.write_cache(config_dir, latest="9.9.9", url="old", checked_at=(NOW - timedelta(days=2)).isoformat())
    fetch["raise"] = requests.ConnectionError("down")
    info = check(config_dir, now=NOW)
    assert info is not None and info.latest == "9.9.9"
    assert update.read_cache(config_dir)["checked_at"] == NOW.isoformat(timespec="seconds")


def test_check_never_raises(config_dir, monkeypatch):
    monkeypatch.setattr(update, "read_cache", lambda d: (_ for _ in ()).throw(RuntimeError("boom")))
    assert check(config_dir) is None


# =============================================================================
# notice()
# =============================================================================


def test_notice_newer(config_dir, fetch):
    line = notice(config_dir)
    assert line.startswith("[알림] 새 버전 " + NEWER) and fetch["result"][1] in line


@pytest.mark.parametrize("latest", [__version__, OLDER])
def test_notice_none_when_not_newer(config_dir, fetch, latest):
    fetch["result"] = (latest, "u")
    assert notice(config_dir) is None


def test_notice_none_on_failure(config_dir, fetch):
    fetch["raise"] = requests.Timeout("x")
    assert notice(config_dir) is None


# =============================================================================
# fetch_latest — 원본 함수를 FakeSession 으로만 (실제 전송은 _no_network 가 계속 차단)
# =============================================================================


def test_fetch_latest_uses_redirect_first():
    s = FakeSession([FakeResponse(302, headers={"Location": "https://github.com/x/y/releases/tag/v1.2.3"})])
    assert _real_fetch_latest(session=s) == ("1.2.3", "https://github.com/x/y/releases/tag/v1.2.3")
    call = s.calls[0]
    assert call["url"] == update.LATEST_PAGE and call["allow_redirects"] is False and call["timeout"] == update.TIMEOUT
    assert call["headers"]["User-Agent"].startswith("swea-fetch/")
    assert len(s.calls) == 1  # API 호출 없음


def test_fetch_latest_relative_location():
    s = FakeSession([FakeResponse(302, headers={"Location": "/x/y/releases/tag/v2.0.0"})])
    assert _real_fetch_latest(session=s) == ("2.0.0", "https://github.com/x/y/releases/tag/v2.0.0")


def test_fetch_latest_falls_back_to_api():
    s = FakeSession([FakeResponse(200, text="<html>no redirect</html>"), FakeResponse(200, json_data={"tag_name": "v0.9.0", "html_url": "https://github.com/x/y/releases/tag/v0.9.0"})])
    assert _real_fetch_latest(session=s) == ("0.9.0", "https://github.com/x/y/releases/tag/v0.9.0")
    assert s.calls[1]["url"] == update.LATEST_API and "github" in s.calls[1]["headers"]["Accept"]


def test_fetch_latest_api_without_html_url_uses_releases_page():
    s = FakeSession([FakeResponse(200, text=""), FakeResponse(200, json_data={"tag_name": "1.0.0"})])
    assert _real_fetch_latest(session=s) == ("1.0.0", update.RELEASES_URL)


def test_fetch_latest_redirect_error_then_api():
    s = FakeSession([requests.ConnectionError("x"), FakeResponse(200, json_data={"tag_name": "v3.0.0", "html_url": "u"})])
    assert _real_fetch_latest(session=s) == ("3.0.0", "u")


@pytest.mark.parametrize("second", [FakeResponse(401, text="{}"), FakeResponse(404, text="{}"), FakeResponse(200, text="not json"), FakeResponse(200, json_data={"tag_name": ""})])
def test_fetch_latest_api_failures_raise(second):
    s = FakeSession([FakeResponse(200, text=""), second])
    with pytest.raises(Exception):
        _real_fetch_latest(session=s)


# =============================================================================
# CLI 연동: 명령 끝 알림, --no-update-check, doctor 는 자체 항목
# =============================================================================


@pytest.fixture
def notice_spy(monkeypatch):
    st = {"calls": 0, "line": "[알림] 새 버전 9.9.9 — u"}

    def fake(config_dir):
        st["calls"] += 1
        assert config_dir == config.CONFIG_DIR
        return st["line"]

    monkeypatch.setattr(cli.update, "notice", fake)
    return st


def test_cli_prints_notice_to_stderr_after_command(notice_spy, config_dir, capsys):
    assert cli.main(["logout"]) == 0
    assert notice_spy["calls"] == 1
    assert "[알림] 새 버전 9.9.9" in capsys.readouterr().err


def test_cli_no_update_check_flag(notice_spy, capsys):
    assert cli.main(["logout", "--no-update-check"]) == 0
    assert notice_spy["calls"] == 0
    assert "[알림]" not in capsys.readouterr().err


def test_cli_notice_none_prints_nothing(notice_spy, capsys):
    notice_spy["line"] = None
    cli.main(["logout"])
    assert "[알림]" not in capsys.readouterr().err


def test_cli_notice_runs_even_when_command_fails(notice_spy):
    assert cli.main(["check", "sim", "1"]) == 1  # 설정 없음
    assert notice_spy["calls"] == 1


def test_cli_notice_failure_does_not_change_exit_code(monkeypatch):
    def boom(config_dir):
        raise RuntimeError("x")

    monkeypatch.setattr(cli.update, "notice", boom)
    assert cli.main(["logout"]) == 0


def test_cli_doctor_skips_trailing_notice(notice_spy, monkeypatch):
    monkeypatch.setattr(cli.doctor, "report", lambda offline=False: "swea-fetch x")
    assert cli.main(["doctor", "--offline"]) == 0
    assert notice_spy["calls"] == 0


def test_no_network_fixture_blocks_real_fetch(config_dir):
    """회귀 방지: autouse 차단이 살아 있는지 (없으면 CLI 테스트마다 GitHub 에 요청한다)."""
    with pytest.raises(RuntimeError, match="네트워크"):
        update.fetch_latest()
    with pytest.raises(RuntimeError, match="네트워크"):
        requests.get("https://example.invalid/", timeout=1)
