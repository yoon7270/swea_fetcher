import pytest

from swea_fetcher import platform_text


@pytest.mark.parametrize("plat, expected", [("win32", "Enter · Ctrl+Enter"), ("linux", "Enter · Ctrl+Enter"), ("darwin", "Enter · ⌘Enter")])
def test_keys_only_changes_on_mac(monkeypatch, plat, expected):
    monkeypatch.setattr(platform_text.sys, "platform", plat)
    assert platform_text.keys("Enter · Ctrl+Enter") == expected


def test_keys_alt_shift_on_mac(monkeypatch):
    monkeypatch.setattr(platform_text.sys, "platform", "darwin")
    assert platform_text.keys("Alt+Shift+Left") == "⌥⇧Left"


@pytest.mark.parametrize("plat, needle", [("win32", "C:\\Users"), ("darwin", "/Users/"), ("linux", "/home/")])
def test_example_root(monkeypatch, plat, needle):
    monkeypatch.setattr(platform_text.sys, "platform", plat)
    assert needle in platform_text.example_root()


def test_login_state_hint(monkeypatch):
    monkeypatch.setattr(platform_text.sys, "platform", "win32")
    assert platform_text.login_state_hint() == "%USERPROFILE%\\.swea-fetch\\login_state.json"
    monkeypatch.setattr(platform_text.sys, "platform", "darwin")
    assert platform_text.login_state_hint() == "~/.swea-fetch/login_state.json"
