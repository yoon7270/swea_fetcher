"""시스템 앱 모드 감지와 네이티브 요소(타이틀 바) 색 구성표 — 스펙 §17.2.

tokens 는 Qt 를 모르므로 감지 결과는 여기서 tokens.set_system_dark() 로 주입된다. 모든 OS 호출은 실패해도 조용히 무시한다.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

POLL_MS = 3000  # colorSchemeChanged 신호가 없을 때의 폴링 간격


def _registry_dark() -> bool:
    """HKCU\\...\\Themes\\Personalize 의 AppsUseLightTheme (0 = 다크). 읽기 실패 = 라이트."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except Exception:  # noqa: BLE001 — 키 없음·권한·비 Windows
        return False


def detect_system_dark() -> bool:
    """OS 앱 모드가 다크인가. ① Qt styleHints().colorScheme() → ② 값이 Unknown 이면 레지스트리."""
    try:
        from PySide6.QtCore import Qt

        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except Exception:  # noqa: BLE001 — 구버전 Qt: 속성 없음
        pass
    return _registry_dark()


def apply_native_scheme(window, mode: str | None = None, dark: bool | None = None) -> None:
    """강제 모드일 때 타이틀 바·네이티브 다이얼로그를 앱 선택에 맞춘다.

    Qt 6.8+: styleHints().setColorScheme(Light|Dark|Unknown). 없으면 DWM 의 USE_IMMERSIVE_DARK_MODE(20) 를 창 핸들에 설정.
    mode 가 None 이면 tokens 의 현재 값을 쓴다.
    """
    from PySide6.QtCore import Qt

    from swea_fetcher.gui.theme import tokens

    mode = mode or tokens.color_mode()
    dark = tokens.is_dark() if dark is None else dark
    try:
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "setColorScheme"):
            scheme = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}.get(mode, Qt.ColorScheme.Unknown)
            hints.setColorScheme(scheme)
            return
    except Exception:  # noqa: BLE001
        pass
    if sys.platform != "win32" or window is None:
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:  # noqa: BLE001
        pass


class SystemWatcher(QObject):
    """OS 앱 모드 변경 감시. 모드가 system 일 때만 changed(bool) 를 emit 한다 (감시 자체는 항상 하되 emit 을 거른다)."""

    changed = Signal(bool)

    def __init__(self, mode_getter, parent: QObject | None = None):
        super().__init__(parent)
        self._mode_getter = mode_getter
        self._last = detect_system_dark()
        self._timer: QTimer | None = None
        sig = None
        try:
            sig = QGuiApplication.styleHints().colorSchemeChanged
        except Exception:  # noqa: BLE001
            sig = None
        if sig is not None:
            sig.connect(lambda *_: self.check())
        else:
            self._timer = QTimer(self)
            self._timer.setInterval(POLL_MS)
            self._timer.timeout.connect(self.check)
            self._timer.start()

    def check(self) -> None:
        """현재 OS 모드를 읽어 바뀌었으면(그리고 모드가 system 이면) emit."""
        now = detect_system_dark()
        if now == self._last:
            return
        self._last = now
        if self._mode_getter() == "system":
            self.changed.emit(now)
