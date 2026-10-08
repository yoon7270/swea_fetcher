"""사용자에게 보이는 문구 중 OS 마다 달라지는 것 (단축키 표기, 경로 예시). 동작은 바꾸지 않는다."""
from __future__ import annotations

import sys


def keys(text: str) -> str:
    """'Ctrl+Enter' → macOS 에서는 '⌘Enter'. Qt 가 Ctrl 을 Cmd 로 매핑하므로 표기만 맞춘다."""
    if sys.platform != "darwin":
        return text
    return text.replace("Ctrl+", "⌘").replace("Alt+", "⌥").replace("Shift+", "⇧")


def example_root() -> str:
    """루트 폴더 입력란 예시."""
    if sys.platform == "win32":
        return "예: C:\\Users\\<you>\\Desktop\\swea"
    return "예: /Users/<you>/Desktop/swea" if sys.platform == "darwin" else "예: /home/<you>/swea"


def config_dir_hint() -> str:
    """설정 폴더(~/.swea-fetch) 의 OS 별 표기."""
    return "%USERPROFILE%\\.swea-fetch" if sys.platform == "win32" else "~/.swea-fetch"


def login_state_hint() -> str:
    return config_dir_hint() + ("\\" if sys.platform == "win32" else "/") + "login_state.json"
