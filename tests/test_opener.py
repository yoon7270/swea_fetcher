"""opener (M13): 에디터 판별 / VS Code 창 재사용·새 창 / 폴백. 전부 모킹 — 실제 창·COM·프로세스 실행 없음."""

from __future__ import annotations

from pathlib import Path

import pytest

from swea_fetcher import opener
from swea_fetcher.config import load_settings
from swea_fetcher.opener import detect_editor, editor_label, editor_tooltip, open_in_editor
from tests.conftest import DUMMY_ID, DUMMY_PW

PDIR = Path("C:/sol/1234")
PFILE = PDIR / "1234.py"


@pytest.fixture
def win(monkeypatch):
    """win32 로 가장하고 실행 경로를 모두 가짜로 바꾼다. calls 에 Popen 인자·startfile 인자가 쌓인다."""
    calls = {"popen": [], "startfile": []}
    monkeypatch.setattr(opener.sys, "platform", "win32")
    monkeypatch.setattr(opener, "_vscode_exe", lambda: "C:/vs/Code.exe")
    monkeypatch.setattr(opener.subprocess, "Popen", lambda args, **kw: calls["popen"].append((args, kw)))
    monkeypatch.setattr(opener.os, "startfile", lambda p: calls["startfile"].append(p), raising=False)
    return calls


# --- detect_editor / 라벨 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "exe, kind",
    [
        (r"C:\Users\x\AppData\Local\Programs\Microsoft VS Code\Code.exe", "vscode"),
        (r"C:\VS\Code - Insiders.exe", "vscode"),
        (r"C:\JB\bin\pycharm64.exe", "pycharm"),
        (r"C:\Windows\notepad.exe", "default"),
        (None, "default"),
    ],
)
def test_detect_auto(monkeypatch, exe, kind):
    monkeypatch.setattr(opener.sys, "platform", "win32")
    monkeypatch.setattr(opener, "_assoc_exe", lambda: exe)
    assert detect_editor("auto") == kind


def test_detect_assoc_exception_is_default(monkeypatch):
    def boom():
        raise OSError("x")

    monkeypatch.setattr(opener, "_assoc_exe", boom)
    assert detect_editor("auto") == "default"


def test_detect_forced_value_beats_auto(monkeypatch):
    monkeypatch.setattr(opener, "_assoc_exe", lambda: r"C:\notepad.exe")
    assert detect_editor("vscode") == "vscode"
    assert detect_editor("PyCharm") == "pycharm"


def test_detect_invalid_value_is_auto(monkeypatch):
    monkeypatch.setattr(opener.sys, "platform", "win32")
    monkeypatch.setattr(opener, "_assoc_exe", lambda: r"C:\Code.exe")
    assert detect_editor("emacs") == "vscode"
    assert detect_editor(None) == "vscode"


def test_labels_and_tooltip(monkeypatch):
    assert editor_label("vscode") == "VS Code"
    assert editor_label("pycharm") == "PyCharm"
    assert editor_label("default") == "기본 연결 프로그램"
    assert editor_label("???") == "기본 연결 프로그램"
    monkeypatch.setattr(opener.sys, "platform", "win32")
    monkeypatch.setattr(opener, "_assoc_exe", lambda: r"C:\Code.exe")
    assert editor_tooltip("auto") == "열릴 프로그램: VS Code"


# --- VS Code ---------------------------------------------------------------------------


def _fake_windows(monkeypatch, windows, on_current):
    monkeypatch.setattr(opener, "_windows_of", lambda match: windows)
    monkeypatch.setattr(opener, "_on_current_desktop", on_current)


def test_vscode_reuses_window_on_current_desktop(win, monkeypatch):
    _fake_windows(monkeypatch, [(1, "1234.py - 1234 - Visual Studio Code")], lambda h: True)
    res = open_in_editor(PDIR, PFILE, "vscode")
    args, kw = win["popen"][0]
    assert res.ok and res.kind == "vscode"
    assert "--new-window" not in args and "-g" in args
    assert isinstance(args, list) and not kw.get("shell")
    assert win["startfile"] == []


@pytest.mark.parametrize(
    "windows, on_current",
    [
        ([], lambda h: True),  # 창 없음
        ([(1, "other - Visual Studio Code")], lambda h: True),  # 다른 폴더 창
        ([(1, "1234.py - 1234 - Visual Studio Code")], lambda h: False),  # 다른 데스크톱에만
        ([(1, "1234.py - 1234 - Visual Studio Code")], lambda h: None),  # 판별 불가
    ],
)
def test_vscode_new_window(win, monkeypatch, windows, on_current):
    _fake_windows(monkeypatch, windows, on_current)
    open_in_editor(PDIR, PFILE, "vscode")
    args, _ = win["popen"][0]
    assert args[1] == "--new-window" and "-g" in args and str(PFILE) in args


@pytest.mark.parametrize("on_current", [lambda h: False, lambda h: None])  # 다른 데스크톱에만 / 판별 불가
def test_vscode_folder_elsewhere_opens_file_only(win, monkeypatch, on_current):
    # 같은 폴더를 넘기면 VS Code 가 다른 데스크톱의 기존 창을 활성화하므로 폴더 인자를 빼야 한다
    _fake_windows(monkeypatch, [(1, "1234.py - 1234 - Visual Studio Code")], on_current)
    open_in_editor(PDIR, PFILE, "vscode")
    args, _ = win["popen"][0]
    assert args[1:] == ["--new-window", "-g", str(PFILE)]


def test_vscode_no_folder_window_passes_folder(win, monkeypatch):
    _fake_windows(monkeypatch, [(1, "other - Visual Studio Code")], lambda h: False)
    open_in_editor(PDIR, PFILE, "vscode")
    args, _ = win["popen"][0]
    assert args[1:] == ["--new-window", str(PDIR), "-g", str(PFILE)]


def test_vscode_enum_exception_means_new_window(win, monkeypatch):
    def boom(match):
        raise OSError("enum")

    monkeypatch.setattr(opener, "_windows_of", boom)
    open_in_editor(PDIR, PFILE, "vscode")
    assert "--new-window" in win["popen"][0][0]


def test_vscode_popen_oserror_falls_back_to_startfile(win, monkeypatch):
    _fake_windows(monkeypatch, [], lambda h: True)

    def boom(args, **kw):
        raise OSError("nope")

    monkeypatch.setattr(opener.subprocess, "Popen", boom)
    res = open_in_editor(PDIR, PFILE, "vscode")
    assert res.ok and win["startfile"] == [str(PFILE)]


def test_vscode_exe_missing_falls_back(win, monkeypatch):
    monkeypatch.setattr(opener, "_vscode_exe", lambda: None)
    res = open_in_editor(PDIR, PFILE, "vscode")
    assert res.ok and win["popen"] == [] and win["startfile"] == [str(PFILE)]


def test_final_failure_returns_not_ok(win, monkeypatch):
    def boom(p):
        raise OSError("x")

    monkeypatch.setattr(opener.os, "startfile", boom, raising=False)
    assert not open_in_editor(PDIR, PFILE, "default").ok


# --- PyCharm / default / 비 Windows -------------------------------------------------------


def test_pycharm_other_desktop_warns_and_opens(win, monkeypatch):
    _fake_windows(monkeypatch, [(5, "proj - PyCharm")], lambda h: False)
    res = open_in_editor(PDIR, PFILE, "pycharm")
    assert res.ok and res.kind == "pycharm" and "전환" in res.note
    assert win["startfile"] == [str(PFILE)] and win["popen"] == []


def test_pycharm_current_desktop_no_warning(win, monkeypatch):
    _fake_windows(monkeypatch, [(5, "proj - PyCharm")], lambda h: True)
    assert open_in_editor(PDIR, PFILE, "pycharm").note == ""


def test_default_uses_startfile_only(win):
    res = open_in_editor(PDIR, PFILE, "default")
    assert res.ok and win["startfile"] == [str(PFILE)] and win["popen"] == []


def test_non_windows_uses_xdg_open_without_windll(monkeypatch):
    calls = []
    monkeypatch.setattr(opener.sys, "platform", "linux")
    monkeypatch.setattr(opener.subprocess, "Popen", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(opener, "_windows_of", lambda m: pytest.fail("windll 접근"))
    monkeypatch.setattr(opener, "_assoc_exe", lambda: pytest.fail("windll 접근"))
    res = open_in_editor(PDIR, PFILE, "auto")
    assert res.ok and calls == [["xdg-open", str(PFILE)]]


# --- 설정 (SWEA_EDITOR) ------------------------------------------------------------------


def _env(config_dir, root_dir, **kv):
    text = f"SWEA_ROOT={root_dir}\nSWEA_ID={DUMMY_ID}\nSWEA_PW={DUMMY_PW}\n" + "".join(f"{k}={v}\n" for k, v in kv.items())
    (config_dir / ".env").write_text(text, encoding="utf-8")


def test_settings_editor_default_and_value(root_dir, config_dir):
    _env(config_dir, root_dir)
    assert load_settings(config_dir).editor == "auto"
    _env(config_dir, root_dir, SWEA_EDITOR=" VSCode ")
    assert load_settings(config_dir).editor == "vscode"


def test_settings_editor_invalid_warns(root_dir, config_dir, caplog):
    _env(config_dir, root_dir, SWEA_EDITOR="emacs")
    with caplog.at_level("WARNING"):
        assert load_settings(config_dir).editor == "auto"
    assert "SWEA_EDITOR" in caplog.text


# --- 폴더 열기 (탐색기) -------------------------------------------------------------------


def test_folder_reuses_explorer_window_on_current_desktop(win, monkeypatch):
    activated = []
    monkeypatch.setattr(opener, "_explorer_window_here", lambda name: 42 if name == "1234" else None)
    monkeypatch.setattr(opener, "_activate", lambda h: activated.append(h) or True)
    assert opener.open_folder(PDIR) is True
    assert activated == [42] and win["popen"] == [] and win["startfile"] == []


def test_folder_opens_new_window_when_none_here(win, monkeypatch):
    # startfile 은 다른 데스크톱의 탐색기 창에 탭으로 붙어 화면이 전환될 수 있다 → explorer /n, 로 새 창
    monkeypatch.setattr(opener, "_explorer_window_here", lambda name: None)
    assert opener.open_folder(PDIR) is True
    args, kw = win["popen"][0]
    assert args == ["explorer.exe", "/n,", str(PDIR)] and not kw.get("shell")
    assert win["startfile"] == []


def test_folder_activate_failure_opens_new_window(win, monkeypatch):
    monkeypatch.setattr(opener, "_explorer_window_here", lambda name: 42)
    monkeypatch.setattr(opener, "_activate", lambda h: False)
    opener.open_folder(PDIR)
    assert win["popen"][0][0][0] == "explorer.exe"


def test_folder_enum_exception_falls_back_to_startfile(win, monkeypatch):
    def boom(name):
        raise OSError("enum")

    monkeypatch.setattr(opener, "_explorer_window_here", boom)
    assert opener.open_folder(PDIR) is True
    assert win["startfile"] == [str(PDIR)] and win["popen"] == []


def test_folder_startfile_failure_is_false(win, monkeypatch):
    def boom(name):
        raise OSError("enum")

    def fail(p):
        raise OSError("nope")

    monkeypatch.setattr(opener, "_explorer_window_here", boom)
    monkeypatch.setattr(opener.os, "startfile", fail, raising=False)
    assert opener.open_folder(PDIR) is False


def test_folder_non_windows_uses_xdg_open(monkeypatch):
    calls = []
    monkeypatch.setattr(opener.sys, "platform", "linux")
    monkeypatch.setattr(opener.subprocess, "Popen", lambda args, **kw: calls.append(args))
    assert opener.open_folder(PDIR) is True
    assert calls == [["xdg-open", str(PDIR)]]
