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
    app.setStyleSheet(tokens.build_qss(tokens.LIGHT))
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    return app


def _selftest(out_path: str) -> int:
    """SWEA_FETCH_SELFTEST=<파일> 이면 창을 띄우지 않고 진단 결과를 파일에 쓰고 종료 (exe 빌드 검증용)."""
    import os
    from .. import config
    from .widgets import ICON_DIR

    lines = [f"frozen={getattr(sys, 'frozen', False)}", f"icon_dir_exists={ICON_DIR.exists()}",
             f"icons={sorted(p.name for p in ICON_DIR.glob('*.svg')) if ICON_DIR.exists() else []}"]
    try:
        kr = config._keyring()
        lines.append(f"keyring_backend={type(kr.get_keyring()).__name__}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"keyring_error={type(e).__name__}: {e}")
    try:
        st = config.load_settings()
        lines.append(f"settings=ok user_id_set={bool(st.user_id)} root_exists={st.root.is_dir()}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"settings_error={type(e).__name__}: {e}")
    from .main_window import MainWindow

    win = MainWindow()
    lines.append(f"window={win.width()}x{win.height()} page={win.nav.currentRow()} status={win.status_login.text()}")
    win.close()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 0


def main() -> int:
    import os

    app = create_app()
    if os.environ.get("SWEA_FETCH_SELFTEST"):
        return _selftest(os.environ["SWEA_FETCH_SELFTEST"])
    from .main_window import MainWindow  # QApplication 이후 import (QSettings 등)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
