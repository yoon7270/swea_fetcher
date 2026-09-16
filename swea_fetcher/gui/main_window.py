"""MainWindow (스펙 §3): 사이드바(앱 이름 + 내비 4) + 페이지 스택 + 상태바."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import config, service
from ..config import Settings
from ..errors import ConfigMissing
from .pages.check_page import CheckPage
from .pages.fetch_page import FetchPage
from .pages.history_page import HistoryPage
from .pages.settings_page import SettingsPage
from .theme import tokens
from .widgets import nav_icon, set_class

PAGES = (("저장", "fetch", "nav-fetch"), ("검증", "check", "nav-check"), ("최근", "history", "nav-history"), ("설정", "settings", "nav-settings"))
APP_TITLE = "SWEA Fetch"


class MainWindow(QMainWindow):
    def __init__(self, config_dir: Path | None = None) -> None:
        super().__init__()
        self.config_dir = Path(config_dir) if config_dir is not None else config.CONFIG_DIR
        self.qs = QSettings("swea-fetch", "gui")
        self.settings: Settings | None = None
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(*tokens.WINDOW_MIN)
        self.resize(*tokens.WINDOW_DEFAULT)
        self._build()
        self._restore_state()
        self.reload_settings(first_run=True)

    # --- UI ---------------------------------------------------------------------------
    def _build(self) -> None:
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(tokens.SIDEBAR_W)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        app_title = QLabel(APP_TITLE)
        app_title.setObjectName("AppTitle")
        set_class(app_title, "app-title")
        sl.addWidget(app_title)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(20, 20))
        self.nav.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        for label, _key, icon in PAGES:
            item = QListWidgetItem(nav_icon(icon), label)
            item.setSizeHint(QSize(0, tokens.NAV_ITEM_H))
            self.nav.addItem(item)
        sl.addWidget(self.nav, 1)
        lay.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.fetch_page = FetchPage(self.qs)
        self.check_page = CheckPage(self.qs)
        self.history_page = HistoryPage()
        self.settings_page = SettingsPage(self.qs, self.config_dir)
        for p in (self.fetch_page, self.check_page, self.history_page, self.settings_page):
            self.stack.addWidget(p)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # 상태바 (§3): 좌 로그인 상태 · 중 임시 메시지 · 우 루트 경로
        self.status_login = QLabel("○ 세션 없음")
        self.status_login.setObjectName("LoginState")
        set_class(self.status_login, "login", "none")
        self.status_root = QLabel("")  # 상태바 permanent 위젯은 Ignored 정책이 0폭으로 눌리므로 고정폭 elide 사용
        set_class(self.status_root, "hint")
        self.status_root.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sb = self.statusBar()
        sb.addWidget(self.status_login)
        sb.addPermanentWidget(self.status_root)

        # 연결
        self.nav.currentRowChanged.connect(self._page_changed)
        for p in (self.fetch_page, self.check_page, self.settings_page):
            p.busy_changed.connect(self._set_busy)
        for p in (self.fetch_page, self.check_page, self.history_page, self.settings_page):
            p.status_message.connect(self.flash)
        for p in (self.fetch_page, self.check_page, self.history_page):
            p.goto_requested.connect(self.goto)
        self.settings_page.settings_changed.connect(lambda: self.reload_settings(stay=True))
        self.settings_page.timeout_changed.connect(lambda _v: self.check_page.refresh_hint())
        self.history_page.check_requested.connect(self._goto_check)
        self.fetch_page.saved.connect(lambda _oc: self.history_page.refresh())
        self.fetch_page.saved.connect(lambda _oc: self._update_status())

        for i in range(4):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.nav.setCurrentRow(i))
        QShortcut(QKeySequence("Ctrl+,"), self, activated=lambda: self.goto("settings"))

    def _page_changed(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        self.qs.setValue("window/last_page", row)
        if PAGES[row][1] == "history":
            self.history_page.refresh()
        elif PAGES[row][1] == "fetch":
            self.fetch_page.target.setFocus()

    def goto(self, key: str) -> None:
        for i, (_label, k, _icon) in enumerate(PAGES):
            if k == key:
                self.nav.setCurrentRow(i)
                return

    def _goto_check(self, topic: str, num: int) -> None:
        self.check_page.set_target(topic, num)
        self.goto("check")

    def _set_busy(self, busy: bool, suffix: str) -> None:
        self.setWindowTitle(f"{APP_TITLE} — {suffix}" if busy and suffix else APP_TITLE)

    def flash(self, msg: str, ms: int = 4000) -> None:
        """상태바 임시 메시지 (토스트 대용, 스펙 §3)."""
        self.statusBar().showMessage(msg, ms)

    # --- 설정 -------------------------------------------------------------------------
    def reload_settings(self, first_run: bool = False, stay: bool = False) -> None:
        try:
            self.settings = config.load_settings(self.config_dir)
        except ConfigMissing:
            self.settings = None
            for p in (self.fetch_page, self.check_page, self.history_page, self.settings_page):
                p.set_settings(None)
            self._update_status()
            if not stay:
                self.settings_page.show_first_run()
                self.goto("settings")
            return
        for p in (self.fetch_page, self.check_page, self.history_page, self.settings_page):
            p.set_settings(self.settings)
        self._update_status()
        if first_run:
            row = int(self.qs.value("window/last_page", 0, type=int))
            self.nav.setCurrentRow(row if 0 <= row < len(PAGES) else 0)
            self.stack.setCurrentIndex(self.nav.currentRow())
        # stay=True (설정 페이지에서 저장): 자동 이동 없음 — 결과를 확인할 시간을 준다 (§4.1)

    def _update_status(self) -> None:
        if self.settings is None:
            self.status_login.setText("○ 설정 없음")
            set_class(self.status_login, "login", "none")
            self.status_root.setText("")
            return
        cached = service.is_session_cached(self.settings)
        self.status_login.setText("● 로그인됨" if cached else "○ 세션 없음")
        set_class(self.status_login, "login", "ok" if cached else "none")
        root = str(self.settings.root)
        self.status_root.setText(self.status_root.fontMetrics().elidedText(root, Qt.TextElideMode.ElideMiddle, 360))
        self.status_root.setToolTip(root)

    # --- 창 상태 ------------------------------------------------------------------------
    def _restore_state(self) -> None:
        geo = self.qs.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        # 화면 밖 복원 방지
        screen = QGuiApplication.primaryScreen()
        if screen is not None and not screen.availableGeometry().intersects(self.frameGeometry()):
            self.resize(*tokens.WINDOW_DEFAULT)
            self.move(screen.availableGeometry().center() - self.rect().center())

    def closeEvent(self, e) -> None:  # noqa: N802
        self.qs.setValue("window/geometry", self.saveGeometry())
        super().closeEvent(e)
