"""ThemeBus — 테마·모드 적용이 끝난 뒤 한 번 emit 되는 신호 (스펙 §17.9).

캐시(QPixmap·QIcon·문서 CSS·잔디 기준색)를 가진 위젯은 changed 를 구독해 재생성한다.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class ThemeBus(QObject):
    changed = Signal()


_bus: ThemeBus | None = None


def bus() -> ThemeBus:
    """싱글톤. QApplication 이 있어야 시그널이 동작한다(없어도 객체 생성은 가능)."""
    global _bus
    if _bus is None:
        _bus = ThemeBus()
    return _bus
