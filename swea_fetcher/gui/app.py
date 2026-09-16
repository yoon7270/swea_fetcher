"""진입점 `swea-fetch-gui`: QApplication + 테마 + MainWindow."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .theme import tokens

ICON_PATH = Path(__file__).parent / "theme" / "icons" / "app.svg"


def create_app(argv: list[str] | None = None) -> QApplication:
    """HiDPI 정책을 QApplication 생성 전에 설정하고 테마를 적용한다."""
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("swea-fetch")
    app.setOrganizationName("swea-fetch")
    app.setStyle("Fusion")  # 플랫폼별 편차를 줄이고 QSS 가 일관되게 먹도록
    app.setStyleSheet(tokens.build_qss(tokens.LIGHT) + _builder_supplement(tokens.LIGHT))
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    return app


def _builder_supplement(p: tokens.Palette) -> str:
    """스펙 QSS 에 없는 최소 보강 (design-spec §15 대체안 기록). 색은 토큰만."""
    return f"""
QFrame#Sidebar {{ background: {p.surface}; border-right: 1px solid {p.border}; }}
QListWidget#nav {{ border-right: none; }}
QFrame[class="card"][state="drop"] {{ border: 2px solid {p.primary}; }}
QLabel#preview {{ background: {p.surface_alt}; color: {p.text_2}; border-radius: {tokens.RADIUS_SM}px; }}
"""


def main() -> int:
    app = create_app()
    from .main_window import MainWindow  # QApplication 이후 import (QSettings 등)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
