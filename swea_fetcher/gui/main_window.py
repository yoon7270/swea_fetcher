"""MainWindow (스펙 §3): 사이드바(앱 이름 + 내비 4) + 페이지 스택 + 상태바."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import config, content_cache, service, storage, update
from ..config import Settings
from ..errors import ConfigMissing
from .pages.check_page import CheckPage
from .pages.fetch_page import FetchPage
from .pages.history_page import HistoryPage
from .pages.problem_page import ProblemPage
from .pages.settings_page import SettingsPage
from .theme import tokens
from .widgets import nav_icon, set_class
from .workers import FetchWorker, FuncWorker

PAGES = (
    ("저장", "fetch", "nav-fetch"),
    ("문제", "problem", "nav-problem"),
    ("검증", "check", "nav-check"),
    ("최근", "history", "nav-history"),
    ("설정", "settings", "nav-settings"),
)
APP_TITLE = "SWEA Fetch"
NAV_HISTORY_MAX = 50  # 뒤로 가기 기록 상한
UPDATE_CHECK_DELAY_MS = 1500  # 창이 뜬 뒤에 조회 (시작 속도에 영향 없게). app.main() 이 사용


class MainWindow(QMainWindow):
    def __init__(self, config_dir: Path | None = None) -> None:
        super().__init__()
        self.config_dir = Path(config_dir) if config_dir is not None else config.CONFIG_DIR
        self.qs = QSettings("swea-fetch", "gui")
        self.settings: Settings | None = None
        self._update_worker: FuncWorker | None = None
        self._stmt_worker: FetchWorker | None = None  # 최근 탭 "문제 보기" 의 지문만 가져오기 (M14)
        self.autosync = None  # AutoSyncController (M11) — _build 뒤 생성
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(*tokens.WINDOW_MIN)
        self.resize(*tokens.WINDOW_DEFAULT)
        self._build()
        self._restore_state()
        self.reload_settings(first_run=True)
        # 새 버전 확인은 app.main() 이 창을 띄운 뒤 시작한다 (테스트·자가진단에서는 네트워크를 쓰지 않도록)

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
        self.problem_page = ProblemPage(self.qs)
        self.check_page = CheckPage(self.qs)
        self.history_page = HistoryPage()
        self.settings_page = SettingsPage(self.qs, self.config_dir)
        for p in (self.fetch_page, self.problem_page, self.check_page, self.history_page, self.settings_page):  # PAGES 순서
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
        self.update_badge = QPushButton("")  # 새 버전 배지 (M6 §4): 클릭 → Release 페이지
        self.update_badge.setObjectName("UpdateBadge")
        set_class(self.update_badge, "link")
        self.update_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_badge.hide()
        self.update_badge.clicked.connect(self._open_release)
        self.autosync_badge = QPushButton("")  # 자동 동기화 상태 (M11): 클릭 → 설정
        self.autosync_badge.setObjectName("AutoSyncBadge")
        set_class(self.autosync_badge, "link")
        self.autosync_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.autosync_badge.hide()
        self.autosync_badge.clicked.connect(lambda: self.goto("settings"))
        self.review_badge = QPushButton("")  # 복습할 문제 (M17 AI 코치): 클릭 → 최근 탭의 복습 카드
        self.review_badge.setObjectName("ReviewBadge")
        set_class(self.review_badge, "link")
        self.review_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.review_badge.hide()
        self.review_badge.clicked.connect(lambda: self.goto("history"))
        sb = self.statusBar()
        sb.addWidget(self.status_login)
        sb.addWidget(self.autosync_badge)
        sb.addWidget(self.review_badge)
        sb.addPermanentWidget(self.update_badge)
        sb.addPermanentWidget(self.status_root)

        # 연결
        self.nav.currentRowChanged.connect(self._page_changed)
        for p in (self.fetch_page, self.check_page, self.settings_page):
            p.busy_changed.connect(self._set_busy)
        for p in (self.fetch_page, self.problem_page, self.check_page, self.history_page, self.settings_page):
            p.status_message.connect(self.flash)
        for p in (self.fetch_page, self.problem_page, self.check_page, self.history_page):
            p.goto_requested.connect(self.goto)
        self.fetch_page.problem_ready.connect(self._on_problem_ready)
        self.fetch_page.cached_problem_requested.connect(self._show_cached_problem)
        self.history_page.problem_requested.connect(self._open_recent_problem)
        self.settings_page.cache_settings_changed.connect(self.problem_page.refresh_footer)
        self.settings_page.settings_changed.connect(lambda: self.reload_settings(stay=True))
        self.settings_page.timeout_changed.connect(lambda _v: self.check_page.refresh_hint())
        self.history_page.check_requested.connect(self._goto_check)
        self.history_page.reviews_changed.connect(self._refresh_review_badge)
        self.check_page.coach_changed.connect(self._refresh_review_badge)
        self.settings_page.coach_settings_changed.connect(self._reload_coach_settings)
        self.history_page.push_requested.connect(self._goto_push)
        self.history_page.submit_requested.connect(self._goto_submit)
        self.fetch_page.saved.connect(lambda _oc: self.history_page.refresh())
        self.fetch_page.saved.connect(lambda _oc: self._update_status())

        from .autosync import AutoSyncController
        self.autosync = AutoSyncController(self)
        self.autosync.status_changed.connect(self._on_autosync_status)
        self.autosync.synced.connect(lambda r: self.check_page._show_git_log(f"[자동 동기화] {r.note}\n{r.output}"))

        for i in range(len(PAGES)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.nav.setCurrentRow(i))
        QShortcut(QKeySequence("Ctrl+,"), self, activated=lambda: self.goto("settings"))

        # 뒤로/앞으로 (브라우저처럼): 마우스 옆 버튼 + Alt+←/→. 자식 위젯이 먼저 받아 먹지 않도록 앱 단위 필터로 잡는다
        self._back: list[int] = []
        self._forward: list[int] = []
        self._cur_row: int | None = None
        self._nav_by_history = False
        QShortcut(QKeySequence("Alt+Left"), self, activated=self.go_back)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.go_forward)
        QApplication.instance().installEventFilter(self)

    def _page_changed(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        if self._cur_row is not None and row != self._cur_row and not self._nav_by_history:
            self._back.append(self._cur_row)
            del self._back[:-NAV_HISTORY_MAX]
            self._forward.clear()
        self._cur_row = row
        # 행 번호는 내비 순서가 바뀌면 어긋나므로 key 로 저장한다 (옛 window/last_page 는 무시)
        self.qs.setValue("window/last_page_key", PAGES[row][1])
        if PAGES[row][1] == "history":
            self.history_page.refresh()
        elif PAGES[row][1] == "fetch":
            self.fetch_page.target.setFocus()
        elif PAGES[row][1] == "problem":
            self.problem_page.focus_browser()  # 키보드 스크롤

    # --- 문제 탭 (M12) ---------------------------------------------------------------
    def _on_problem_ready(self, outcome) -> None:
        """fetch 결과의 지문을 문제 탭에 싣는다. 저장/뼈대 성공이고 토글이 켜져 있으면 탭도 전환 (미리보기는 전환 안 함)."""
        self.problem_page.show_outcome(outcome)
        if outcome.result is not None and self.qs.value("fetch/auto_open_problem", True, type=bool):
            self.goto("problem")

    def _show_cached_problem(self, num: int) -> None:
        """앱 캐시에서 지문을 읽어 문제 탭으로 (네트워크 없음)."""
        cached = content_cache.load(self.settings, num) if self.settings is not None else None
        if cached is None:
            self.flash("저장된 지문이 없습니다. 저장 탭에서 다시 가져오면 볼 수 있습니다")
            return
        self.problem_page.show_cached(cached)
        self.goto("problem")

    def _open_recent_problem(self, topic: str, num: int) -> None:
        """최근 탭에서 고른 문제의 지문을 문제 탭으로. 캐시에 있으면 바로, 없으면 지문만 가져온다 (저장·덮어쓰기 없음)."""
        if self.settings is None:
            return
        try:
            problem_dir: Path | None = storage.resolve_problem_dir(self.settings.root, topic, num)
        except ValueError:
            problem_dir = None
        cached = content_cache.load(self.settings, num)
        if cached is not None:
            self.problem_page.show_cached(cached, problem_dir)
            self.goto("problem")
            return
        if self._stmt_worker is not None:  # 클릭·Enter 중복 방지
            return
        opts = service.FetchOptions(dry_run=True, skeleton_only=True, with_content=True)  # 첨부·저장 없이 페이지만
        w = FetchWorker(self.settings, str(num), topic, opts, self)
        w.finished_ok.connect(lambda oc, d=problem_dir: self._on_statement_fetched(oc, d))
        w.failed.connect(lambda title, _hint, _detail: self.flash(f"지문을 가져오지 못했습니다: {title}", 8000))
        w.finished.connect(self._clear_stmt_worker)
        self._stmt_worker = w
        self.statusBar().showMessage(f"{num} 지문 가져오는 중…")
        w.start()

    def _on_statement_fetched(self, outcome, problem_dir: Path | None) -> None:
        self.statusBar().clearMessage()
        info = outcome.info
        num = info.num if info.num is not None else 0
        if outcome.content is not None and self.settings is not None and self.qs.value("problem/cache_enabled", True, type=bool):
            content_cache.save(self.settings, num, outcome.topic, info.title, outcome.content)
        cached = content_cache.CachedStatement(num, outcome.topic, info.title, datetime.now().isoformat(timespec="seconds"), outcome.content)
        self.problem_page.show_cached(cached, problem_dir, badge="최신")
        self.goto("problem")

    def _clear_stmt_worker(self) -> None:
        if self._stmt_worker is not None:
            self._stmt_worker.deleteLater()
        self._stmt_worker = None

    # --- 뒤로/앞으로 ------------------------------------------------------------------
    def go_back(self) -> None:
        self._step(self._back, self._forward)

    def go_forward(self) -> None:
        self._step(self._forward, self._back)

    def _step(self, src: list[int], dst: list[int]) -> None:
        if not src or self._cur_row is None:
            return
        dst.append(self._cur_row)
        self._nav_by_history = True
        try:
            self.nav.setCurrentRow(src.pop())
        finally:
            self._nav_by_history = False

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        """이 창 안 어디서든 마우스 뒤로/앞으로 버튼 → 페이지 이동. 다이얼로그 등 다른 창은 건드리지 않는다."""
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and isinstance(obj, QWidget)
            and obj.window() is self
            and event.button() in (Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton)
        ):
            self.go_back() if event.button() == Qt.MouseButton.BackButton else self.go_forward()
            return True
        return super().eventFilter(obj, event)

    def goto(self, key: str) -> None:
        for i, (_label, k, _icon) in enumerate(PAGES):
            if k == key:
                self.nav.setCurrentRow(i)
                return

    def _goto_check(self, topic: str, num: int) -> None:
        self.check_page.set_target(topic, num)
        self.goto("check")

    def _goto_push(self, topic: str, num: int) -> None:
        """최근 페이지 우클릭 '커밋 + 푸시…' → 검증 페이지로 이동 후 같은 확인 다이얼로그 (M7)."""
        self.check_page.set_target(topic, num)
        self.goto("check")
        self.check_page.request_push(topic, num)

    def _goto_submit(self, topic: str, num: int) -> None:
        self.goto("check")
        self.check_page.request_submit(topic, num)

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
            for p in (self.fetch_page, self.problem_page, self.check_page, self.history_page, self.settings_page):
                p.set_settings(None)
            self._update_status()
            self._refresh_review_badge()
            if not stay:
                self.settings_page.show_first_run()
                self.goto("settings")
            return
        for p in (self.fetch_page, self.problem_page, self.check_page, self.history_page, self.settings_page):
            p.set_settings(self.settings)
        if self.autosync is not None:
            self.autosync.configure(self.settings)
        self._update_status()
        self._refresh_review_badge(startup=first_run)
        if first_run:
            key = str(self.qs.value("window/last_page_key", "fetch", type=str))
            row = next((i for i, (_l, k, _ic) in enumerate(PAGES) if k == key), 0)
            if key == "problem" and not self.problem_page.has_content():
                row = 0  # 앱을 다시 켜면 문제 탭은 비어 있으므로 저장 탭으로
            self.nav.setCurrentRow(row)
            self.stack.setCurrentIndex(self.nav.currentRow())
            self._back.clear()  # 시작 페이지 복원은 기록하지 않는다
            self._forward.clear()
        # stay=True (설정 페이지에서 저장): 자동 이동 없음 — 결과를 확인할 시간을 준다 (§4.1)

    def _refresh_review_badge(self, startup: bool = False) -> None:
        """도래한 복습 개수를 상태바 배지에 (파일 1개 읽기). 시작 시 있으면 임시 메시지도 (자정을 넘긴 경우는 다음 갱신 때 반영)."""
        n = service.due_count(self.settings) if self.settings is not None else 0
        self.review_badge.setText(f"복습 {n}개 ↗")
        self.review_badge.setToolTip("클릭하면 최근 탭의 복습 목록으로 이동합니다")
        self.review_badge.setVisible(n > 0)
        if startup and n > 0:
            self.flash(f"복습할 문제 {n}개가 있습니다 — 최근 탭에서 확인", 6000)

    def _reload_coach_settings(self) -> None:
        """AI 코치 설정(엔진·오답 기준·복습일)이 바뀜: 페이지 입력을 건드리지 않고 설정 객체만 교체한다."""
        try:
            self.settings = config.load_settings(self.config_dir)
        except ConfigMissing:
            return
        for p in (self.check_page, self.history_page, self.settings_page):
            p.settings = self.settings
        self._refresh_review_badge()
        self.history_page.refresh()  # 기록을 지웠다면 복습 카드도 사라져야 한다

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

    # --- 새 버전 확인 (M6 §4) -------------------------------------------------------------
    def check_update(self) -> None:
        """워커에서 update.check (하루 1회 조회, 꺼져 있거나 실패면 None). 새 버전이면 상태바 배지."""
        if self._update_worker is not None:
            return
        self._update_worker = FuncWorker(lambda: update.check(self.config_dir), self)
        self._update_worker.finished_ok.connect(self.show_update)
        self._update_worker.finished.connect(self._update_cleanup)
        self._update_worker.start()

    def _update_cleanup(self) -> None:
        self._update_worker = None

    def show_update(self, info) -> None:
        if info is None or not info.is_newer:
            self.update_badge.hide()
            return
        self._release_url = info.url
        self.update_badge.setText(f"새 버전 {info.latest} ↗")
        self.update_badge.setToolTip(f"클릭하면 Release 페이지를 엽니다\n{info.url}")
        self.update_badge.show()

    def _on_autosync_status(self, text: str) -> None:
        self.autosync_badge.setText(text)
        self.autosync_badge.setVisible(bool(text))

    def _open_release(self) -> None:
        QDesktopServices.openUrl(QUrl(getattr(self, "_release_url", update.RELEASES_URL)))

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
        QApplication.instance().removeEventFilter(self)
        self.qs.setValue("window/geometry", self.saveGeometry())
        if self.autosync is not None:
            self.autosync._timer.stop()
            if self.settings is not None and self.qs.value("autosync/sync_on_close", True, type=bool):
                self.autosync.sync_on_close()
        if self._stmt_worker is not None:
            self._stmt_worker.wait(5000)
        for p in (self.settings_page, self.check_page):  # 실행 중 QThread 가 파괴되지 않게
            p.wait_workers()
        if self._update_worker is not None and self._update_worker.isRunning():
            self._update_worker.wait(3000)
        super().closeEvent(e)
