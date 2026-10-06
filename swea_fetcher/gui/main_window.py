"""MainWindow (스펙 §3): 사이드바(앱 이름 + 내비 6) + 페이지 스택 + 상태바."""

from __future__ import annotations

from datetime import date, datetime
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
from .coach_widgets import growth_consent_ok
from .pages.fetch_page import FetchPage
from .pages.growth_page import GrowthPage
from .pages.history_page import HistoryPage
from .pages.problem_page import ProblemPage
from .pages.settings_page import SettingsPage
from .theme import appearance, tokens
from .theme.bus import bus
from .theme.qt_palette import qt_palette
from . import motion
from .widgets import Button, NavDelegate, StatusDot, Toast, nav_icon, set_class, svg_icon
from .workers import FetchWorker, FuncWorker, GrowthWorker

PAGES = (
    ("저장", "fetch", "nav-fetch"),
    ("문제", "problem", "nav-problem"),
    ("검증", "check", "nav-check"),
    ("최근", "history", "nav-history"),
    ("성장", "growth", "nav-growth"),  # M19: 최근 뒤·설정 앞 (설정은 마지막에 두는 관례)
    ("설정", "settings", "nav-settings"),
)
APP_TITLE = "SWEA Fetch"
REDUCE_MOTION_KEY = "ui/reduce_motion"  # QSettings: 동작 줄이기 (bool, 기본 False)
NAV_HISTORY_MAX = 50  # 뒤로 가기 기록 상한
UNSAVED_TOPIC = "preview"  # 저장 안 한 문제의 지문만 가져올 때 쓰는 자리표시 주제 (dry-run 이라 폴더를 만들지 않는다)
UPDATE_CHECK_DELAY_MS = 1500  # 창이 뜬 뒤에 조회 (시작 속도에 영향 없게). app.main() 이 사용
GROWTH_KICK_DELAY_MS = 1500  # 시작 후 지연 실행 (M19 성장 리포트 확정·주간 코멘트)
GROWTH_TICK_MS = 30 * 60 * 1000  # 켜 둔 채 월요일을 넘기는 경우 대응: 30분마다 파일만 확인


class MainWindow(QMainWindow):
    def __init__(self, config_dir: Path | None = None) -> None:
        super().__init__()
        self.config_dir = Path(config_dir) if config_dir is not None else config.CONFIG_DIR
        self.qs = QSettings("swea-fetch", "gui")
        self.settings: Settings | None = None
        self._update_worker: FuncWorker | None = None
        self._stmt_worker: FetchWorker | None = None  # 최근 탭 "문제 보기" 의 지문만 가져오기 (M14)
        self._growth_worker: GrowthWorker | None = None  # 성장 리포트 확정·주간 코멘트 (M19)
        self._growth_queued: date | None = None  # 워커 실행 중에 들어온 수동 코멘트 요청
        self._growth_unseen = 0
        self._autosync_text = ""
        self._restoring = False  # 시작 페이지 복원 중에는 전환 모션 없음
        self.autosync = None  # AutoSyncController (M11) — _build 뒤 생성
        tokens.set_theme(str(self.qs.value(tokens.THEME_SETTING_KEY, tokens.DEFAULT_THEME) or tokens.DEFAULT_THEME))
        tokens.set_color_mode(str(self.qs.value(tokens.COLOR_MODE_SETTING_KEY, tokens.DEFAULT_COLOR_MODE) or tokens.DEFAULT_COLOR_MODE))
        if tokens.color_mode() == "system":
            tokens.set_system_dark(appearance.detect_system_dark())
        motion.set_user_reduce(bool(self.qs.value(REDUCE_MOTION_KEY, False, type=bool)))  # 설정 > 화면 > 동작 줄이기
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(*tokens.WINDOW_MIN)
        self.resize(*tokens.WINDOW_DEFAULT)
        self._build()
        self._restore_state()
        self._sys_watcher = appearance.SystemWatcher(tokens.color_mode, self)  # Windows 앱 모드 변경 → 시스템 따르기일 때만 즉시 반영
        self._sys_watcher.changed.connect(self._on_system_scheme)
        appearance.apply_native_scheme(self)  # 타이틀 바·네이티브 대화상자를 앱 모드에 맞춤 (강제 모드일 때)
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
        self.nav.setItemDelegate(NavDelegate(self.nav))  # 알약 슬라이드 (스펙 §16.7 A2)
        self.nav.setMouseTracking(True)
        for label, _key, icon in PAGES:
            item = QListWidgetItem(nav_icon(icon), label)
            item.setSizeHint(QSize(0, tokens.NAV_ITEM_H + tokens.NAV_GAP))  # 항목 높이 + 사이 간격
            self.nav.addItem(item)
        sl.addWidget(self.nav, 1)
        lay.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.fetch_page = FetchPage(self.qs)
        self.problem_page = ProblemPage(self.qs)
        self.check_page = CheckPage(self.qs)
        self.history_page = HistoryPage()
        self.growth_page = GrowthPage(self.qs)
        self.settings_page = SettingsPage(self.qs, self.config_dir)
        for p in self._pages():  # PAGES 순서
            self.stack.addWidget(p)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.toast = Toast(central)  # 끝난 일의 확인 알림 (스펙 §16.5) — notify() 로 띄운다

        # 상태바 (§3): 좌 로그인 상태 · 중 임시 메시지 · 우 루트 경로
        self.status_login = StatusDot("세션 없음")  # 점은 StatusDot 이 그린다 (● ○ 글리프 대신)
        self.status_login.setObjectName("LoginState")
        set_class(self.status_login, "login", "none")
        self.status_root = QLabel("")  # 상태바 permanent 위젯은 Ignored 정책이 0폭으로 눌리므로 고정폭 elide 사용
        set_class(self.status_root, "hint")
        self.status_root.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.update_badge = Button("")  # 새 버전 배지 (M6 §4): 클릭 → Release 페이지
        self.update_badge.setObjectName("UpdateBadge")
        set_class(self.update_badge, "link")
        self.update_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_badge.hide()
        self.update_badge.clicked.connect(self._open_release)
        self.autosync_badge = Button("")  # 자동 동기화 상태 (M11): 클릭 → 설정
        self.autosync_badge.setObjectName("AutoSyncBadge")
        set_class(self.autosync_badge, "link")
        self.autosync_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.autosync_badge.hide()
        self.autosync_badge.clicked.connect(lambda: self.goto("settings"))
        self.review_badge = Button("")  # 복습할 문제 (M17 AI 코치): 클릭 → 최근 탭의 복습 카드
        self.review_badge.setObjectName("ReviewBadge")
        set_class(self.review_badge, "link")
        self.review_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.review_badge.hide()
        self.review_badge.clicked.connect(lambda: self.goto("history"))
        self.growth_badge = Button("")  # 새 성장 리포트 (M19): 클릭 → 성장 탭
        self.growth_badge.setObjectName("GrowthBadge")
        set_class(self.growth_badge, "link")
        self.growth_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.growth_badge.hide()
        self.growth_badge.clicked.connect(lambda: self.goto("growth"))
        for b in (self.update_badge, self.review_badge, self.growth_badge):
            b.set_trailing_icon("arrow-up-right")  # ↗ 글리프 대신 SVG
        sb = self.statusBar()
        sb.addWidget(self.status_login)
        sb.addWidget(self.autosync_badge)
        sb.addWidget(self.review_badge)
        sb.addWidget(self.growth_badge)
        sb.addPermanentWidget(self.update_badge)
        sb.addPermanentWidget(self.status_root)

        # 연결
        self.nav.currentRowChanged.connect(self._page_changed)
        for p in (self.fetch_page, self.check_page, self.settings_page):
            p.busy_changed.connect(self._set_busy)
        for p in self._pages():
            p.status_message.connect(self._on_page_message)
        for p in (self.fetch_page, self.problem_page, self.check_page, self.history_page, self.growth_page):
            p.goto_requested.connect(self.goto)
        self.growth_page.seen_changed.connect(self._refresh_growth_badge)
        self.growth_page.comment_requested.connect(self._growth_comment_requested)
        self.growth_page.cancel_requested.connect(self._growth_cancel)
        self.growth_page.problem_requested.connect(self._open_recent_problem)  # 풀이 잔디의 날짜 목록 → 문제 탭
        self.settings_page.heat_color_changed.connect(self.growth_page.apply_heat_color)
        self.settings_page.appearance_changed.connect(self.apply_appearance)
        self.fetch_page.problem_ready.connect(self._on_problem_ready)
        self.fetch_page.cached_problem_requested.connect(self._show_cached_problem)
        self.history_page.problem_requested.connect(self._open_recent_problem)
        self.problem_page.open_requested.connect(self._open_problem_by_number)
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

        for i in range(len(PAGES)):  # 인덱스 기반 (내비 순서가 바뀌면 함께 바뀐다). Ctrl+, 는 키 기반
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

        # 성장 기록 (M19): 시작 후 지연 실행 + 30분 틱 (틱은 파일 확인만, 할 일이 있을 때만 워커)
        self._growth_first = QTimer(self)
        self._growth_first.setSingleShot(True)
        self._growth_first.timeout.connect(self._growth_kick)
        self._growth_timer = QTimer(self)
        self._growth_timer.setInterval(GROWTH_TICK_MS)
        self._growth_timer.timeout.connect(self._growth_kick)
        self._growth_timer.start()

    def _pages(self) -> tuple:
        """스택에 넣는 순서 = PAGES 순서."""
        return (self.fetch_page, self.problem_page, self.check_page, self.history_page, self.growth_page, self.settings_page)

    def _page_changed(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        if not self._restoring:
            motion.fade_slide_in(self.stack.currentWidget())  # 페이지 전환 200ms (A1). 시작 복원·창이 안 보일 때는 생략
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
        # 폴더를 함께 넘겨야 지문 아래 입력 | 출력과 [폴더 열기]·[에디터에서 열기] 가 나온다 (충돌 배너의 [문제 보기])
        problem_dir = self.fetch_page._existing_dir
        if problem_dir is None or problem_dir.name != str(num):
            try:
                problem_dir = storage.resolve_problem_dir(self.settings.root, cached.topic, num) if cached.topic else None
            except ValueError:
                problem_dir = None
        self.problem_page.show_cached(cached, problem_dir)
        self.goto("problem")

    def _open_problem_by_number(self, num: int) -> None:
        """문제 탭의 번호 입력: 저장한 문제면 그 폴더(입출력 포함)로, 아니면 캐시 → SWEA 에서 지문만 (저장하지 않음)."""
        if self.settings is None:
            self.flash("먼저 설정에서 루트 폴더와 계정을 정해 주세요", 6000)
            return
        try:
            found = service.find_problem(self.settings, num)
        except OSError:
            found = None
        if found is not None:
            self._open_recent_problem(found.topic, num)
            return
        cached = content_cache.load(self.settings, num)
        if cached is not None:
            self.problem_page.show_cached(cached, None)
            self.goto("problem")
            return
        self._fetch_statement(num, UNSAVED_TOPIC, None, cache_topic="")

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
        self._fetch_statement(num, topic, problem_dir)

    def _fetch_statement(self, num: int, topic: str, problem_dir: Path | None, cache_topic: str | None = None) -> None:
        """지문만 1회 가져온다 (dry-run: 첨부·저장 없음). cache_topic 이 주어지면 캐시·표시에 그 주제를 쓴다 (저장 안 한 문제는 "")."""
        if self._stmt_worker is not None or self.settings is None:  # 클릭·Enter 중복 방지
            return
        opts = service.FetchOptions(dry_run=True, skeleton_only=True, with_content=True)  # 첨부·저장 없이 페이지만
        w = FetchWorker(self.settings, str(num), topic, opts, self)
        w.finished_ok.connect(lambda oc, d=problem_dir, t=cache_topic: self._on_statement_fetched(oc, d, t))
        w.failed.connect(lambda title, _hint, _detail: self.flash(f"지문을 가져오지 못했습니다: {title}", 8000))
        w.finished.connect(self._clear_stmt_worker)
        self._stmt_worker = w
        self.problem_page.set_open_busy(True)
        self.statusBar().showMessage(f"{num} 지문 가져오는 중…")
        w.start()

    def _on_statement_fetched(self, outcome, problem_dir: Path | None, cache_topic: str | None = None) -> None:
        self.statusBar().clearMessage()
        info = outcome.info
        num = info.num if info.num is not None else 0
        topic = outcome.topic if cache_topic is None else cache_topic
        if outcome.content is not None and self.settings is not None and self.qs.value("problem/cache_enabled", True, type=bool):
            content_cache.save(self.settings, num, topic, info.title, outcome.content)
        cached = content_cache.CachedStatement(num, topic, info.title, datetime.now().isoformat(timespec="seconds"), outcome.content)
        self.problem_page.show_cached(cached, problem_dir, badge="최신")
        self.goto("problem")

    def _clear_stmt_worker(self) -> None:
        self.problem_page.set_open_busy(False)
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

    def _sb_set_visible(self, w, on: bool) -> None:
        """상태바 일반 위젯(배지)의 표시. 임시 메시지가 떠 있는 동안 Qt 는 일반 위젯을 숨기는데, 그때 show() 하면
        메시지 글자 위에 겹쳐 그려진다. 메시지 중에는 숨긴 채 "명시적 숨김" 표식만 지워 두면 메시지가 사라질 때 Qt 가 보여 준다."""
        if on and self.statusBar().currentMessage():
            w.setAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide, False)
            return
        w.setVisible(on)

    def flash(self, msg: str, ms: int = 4000) -> None:
        """상태바 임시 메시지 (진행 중·안내 — 토스트 없음)."""
        self.statusBar().showMessage(msg, ms)

    def notify(self, msg: str, kind: str = "success", ms: int = 2400) -> None:
        """끝난 일의 확인: 토스트 + 상태바 메시지 (스크린리더·기존 테스트 호환을 위해 상태바에도 항상 남긴다).
        오류·선택 필요·결과는 토스트가 아니라 배너/카드로 알린다."""
        if kind == "warning":
            ms = max(ms, 4000)
        self.toast.show_message(msg, kind, ms)
        self.statusBar().showMessage(msg, ms)

    # 페이지가 status_message 로 내보내는 문구 중 "끝난 일" 로 보는 것 (토스트 대상). 진행 중·실패 문구는 상태바만
    _DONE_SUFFIXES = ("했습니다", "켰습니다", "껐습니다", "지웠습니다", "열었습니다", "바꿨습니다")

    def _on_page_message(self, msg: str) -> None:
        done = (msg.endswith(self._DONE_SUFFIXES) and "못했습니다" not in msg) or msg.startswith("저장 완료")
        if done:
            self.notify(msg)
        else:
            self.flash(msg)

    def apply_appearance(self, mode: str | None = None, theme_key: str | None = None) -> None:
        """화면 모드(light|dark|system)·테마 전환 (스펙 §17.14): 토큰 → QPalette → QSS → 아이콘 → ThemeBus → 네이티브 → 저장.
        재시작 불필요. 앱 기본 글꼴(힌팅 끔)은 건드리지 않는다. 인자 None 은 현재 값 유지(시스템 모드 재감지만)."""
        app = QApplication.instance()
        self.setUpdatesEnabled(False)  # 한 번에 바꿔 깜빡임·중간 상태 방지
        try:
            if theme_key is not None:
                tokens.set_theme(theme_key)
            if mode is not None:
                tokens.set_color_mode(mode)
            if tokens.color_mode() == "system":
                tokens.set_system_dark(appearance.detect_system_dark())
            if app is not None:
                app.setPalette(qt_palette(tokens.current()))
                app.setStyleSheet(tokens.build_qss())
            for i, (_label, _key, icon) in enumerate(PAGES):
                self.nav.item(i).setIcon(nav_icon(icon))
            for b in self.findChildren(Button):  # 글자 옆 SVG 아이콘 재착색
                b.refresh_icon()
            self._on_autosync_status(self._autosync_text)
            bus().changed.emit()  # 캐시를 가진 위젯(문서 CSS·로그·표·diff·잔디 …)이 스스로 다시 만든다
            appearance.apply_native_scheme(self)
            for w in self.findChildren(QWidget):  # 직접 그리는 위젯(Button·Toggle·차트)이 새 색으로 다시 그리도록
                w.update()
        finally:
            self.setUpdatesEnabled(True)
            self.update()
        self.qs.setValue(tokens.THEME_SETTING_KEY, tokens.current_theme_key())
        self.qs.setValue(tokens.COLOR_MODE_SETTING_KEY, tokens.color_mode())

    def apply_theme(self, key: str) -> None:
        """하위 호환: 테마(색 조합)만 전환."""
        self.apply_appearance(None, key)

    def _on_system_scheme(self, _dark: bool) -> None:
        """OS 앱 모드가 바뀜 (시스템 따르기일 때만 이 신호가 온다)."""
        self.apply_appearance()

    # --- 설정 -------------------------------------------------------------------------
    def reload_settings(self, first_run: bool = False, stay: bool = False) -> None:
        try:
            self.settings = config.load_settings(self.config_dir)
        except ConfigMissing:
            self.settings = None
            for p in self._pages():
                p.set_settings(None)
            self._update_status()
            self._refresh_growth_badge()
            self._refresh_review_badge()
            if not stay:
                self.settings_page.show_first_run()
                self.goto("settings")
            return
        for p in self._pages():
            p.set_settings(self.settings)
        if self.autosync is not None:
            self.autosync.configure(self.settings)
        self._update_status()
        self._refresh_growth_badge()
        self._refresh_review_badge(startup=first_run)  # 복습·성장 알림은 한 메시지로 합친다
        if first_run:
            self._growth_first.start(GROWTH_KICK_DELAY_MS)
        if first_run:
            key = str(self.qs.value("window/last_page_key", "fetch", type=str))
            row = next((i for i, (_l, k, _ic) in enumerate(PAGES) if k == key), 0)
            if key == "problem" and not self.problem_page.has_content():
                row = 0  # 앱을 다시 켜면 문제 탭은 비어 있으므로 저장 탭으로
            self._restoring = True
            try:
                self.nav.setCurrentRow(row)
            finally:
                self._restoring = False
            self.stack.setCurrentIndex(self.nav.currentRow())
            self._back.clear()  # 시작 페이지 복원은 기록하지 않는다
            self._forward.clear()
        # stay=True (설정 페이지에서 저장): 자동 이동 없음 — 결과를 확인할 시간을 준다 (§4.1)

    def _refresh_review_badge(self, startup: bool = False) -> None:
        """도래한 복습 개수를 상태바 배지에 (파일 1개 읽기). 시작 시 있으면 임시 메시지도 (자정을 넘긴 경우는 다음 갱신 때 반영)."""
        n = service.due_count(self.settings) if self.settings is not None else 0
        self.review_badge.setText(f"복습 {n}개")
        self.review_badge.setToolTip("클릭하면 최근 탭의 복습 목록으로 이동합니다")
        self._sb_set_visible(self.review_badge, n > 0)
        if startup:
            msg = self._notice_text(n, self._growth_unseen > 0)
            if msg:
                self.flash(msg, 6000)

    @staticmethod
    def _notice_text(review_n: int, growth_new: bool) -> str | None:
        """시작·리포트 도착 알림 문구. 복습과 성장 알림이 함께 있으면 한 메시지 (서로 덮어쓰지 않게)."""
        if review_n > 0 and growth_new:
            return f"복습 {review_n}개 · 새 성장 리포트 — 최근/성장 탭에서 확인"
        if review_n > 0:
            return f"복습할 문제 {review_n}개가 있습니다 — 최근 탭에서 확인"
        if growth_new:
            return "새 성장 리포트가 도착했어요 — 성장 탭에서 확인"
        return None

    def _refresh_growth_badge(self) -> None:
        """미확인 성장 리포트 수를 상태바 배지에 (파일 읽기만). 성장 기록이 꺼져 있으면 숨긴다."""
        n = service.growth_unseen_count(self.settings) if self.settings is not None else 0
        self._growth_unseen = n
        self.growth_badge.setText("새 성장 리포트" if n <= 1 else f"새 성장 리포트 {n}개")
        self.growth_badge.setToolTip("클릭하면 성장 탭으로 이동합니다")
        self._sb_set_visible(self.growth_badge, n > 0)

    # --- 성장 기록 (M19) ---------------------------------------------------------------------
    def _growth_kick(self, force_week: date | None = None) -> None:
        """리포트 확정·주간 코멘트가 필요하면 GrowthWorker 시작. 성장 기록이 꺼져 있거나 워커가 돌고 있거나 할 일이 없으면 아무 것도 하지 않는다."""
        if not isinstance(force_week, date):
            force_week = None  # QTimer.timeout 이 넘기는 인자 등 무시
        if self.settings is None or not self.settings.growth:
            return
        if self._growth_worker is not None:
            if force_week is not None:
                self._growth_queued = force_week  # 끝나면 이어서
            return
        if force_week is None and not service.growth_due(self.settings):
            return
        consented = frozenset(k for k in ("codex", "claude") if growth_consent_ok(self.qs, k))
        w = GrowthWorker(self.settings, consented, force_week, self)
        w.stats_ready.connect(self._on_growth_stats)
        w.comment_started.connect(self.growth_page.set_comment_running)
        w.comment_ready.connect(self._on_growth_comment)
        w.blocked.connect(self._on_growth_blocked)
        w.failed.connect(lambda title, _hint, _detail: self._on_growth_failed(title))
        w.finished.connect(self._growth_cleanup)
        self._growth_worker = w
        if force_week is not None:
            self.growth_page.set_comment_running(force_week)
        w.start()

    def _growth_comment_requested(self, week) -> None:
        self._growth_kick(week)

    def _growth_cancel(self) -> None:
        if self._growth_worker is not None:
            self._growth_worker.cancel()
        self._growth_queued = None

    def _on_growth_stats(self, weeks) -> None:
        """새 주간 리포트가 확정됨: 배지 + 알림 (복습 알림과 합쳐 1개 메시지)."""
        self._refresh_growth_badge()
        msg = self._notice_text(service.due_count(self.settings) if self.settings is not None else 0, True)
        if msg:
            self.flash(msg, 6000)
        if self.stack.currentWidget() is self.growth_page:
            self.growth_page.refresh()

    def _on_growth_comment(self, _week) -> None:
        self.growth_page.set_comment_running(None)
        if self.stack.currentWidget() is self.growth_page:
            self.growth_page.refresh()

    def _on_growth_blocked(self, reason: str) -> None:
        self.growth_page.set_comment_running(None)
        if reason == "no_engine":
            self.flash("AI 엔진을 찾지 못해 주간 코멘트를 만들지 못했습니다", 6000)

    def _on_growth_failed(self, title: str) -> None:
        running = self.growth_page._running_week
        self.growth_page.note_comment_failure(running, title)
        self.flash(f"주간 코멘트를 만들지 못했습니다: {title}", 6000)

    def _growth_cleanup(self) -> None:
        w, self._growth_worker = self._growth_worker, None
        if w is not None:
            w.deleteLater()
        self.growth_page.set_comment_running(None)
        self._refresh_growth_badge()
        if self.stack.currentWidget() is self.growth_page:
            self.growth_page.refresh()
        queued, self._growth_queued = self._growth_queued, None
        if queued is not None:
            self._growth_kick(queued)

    def _reload_coach_settings(self) -> None:
        """AI 코치 설정(엔진·오답 기준·복습일)이 바뀜: 페이지 입력을 건드리지 않고 설정 객체만 교체한다."""
        try:
            self.settings = config.load_settings(self.config_dir)
        except ConfigMissing:
            return
        for p in (self.check_page, self.history_page, self.settings_page):
            p.settings = self.settings
        self.growth_page.set_settings(self.settings)  # 성장 기록 켜기/끄기·기록 지우기 반영
        self._refresh_growth_badge()
        self._refresh_review_badge()
        self.history_page.refresh()  # 기록을 지웠다면 복습 카드도 사라져야 한다

    def _update_status(self) -> None:
        if self.settings is None:
            self.status_login.setText("설정 없음")
            set_class(self.status_login, "login", "none")
            self.status_root.setText("")
            return
        cached = service.is_session_cached(self.settings)
        self.status_login.setText("로그인됨" if cached else "세션 없음")
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
        self.update_badge.setText(f"새 버전 {info.latest}")
        self.update_badge.setToolTip(f"클릭하면 Release 페이지를 엽니다\n{info.url}")
        self.update_badge.show()

    def _on_autosync_status(self, text: str) -> None:
        """자동 동기화 배지. 컨트롤러 문구 앞의 ⚠ ⟳ 글리프(Pretendard 에 없음)는 떼고 SVG 아이콘으로 대신한다."""
        self._autosync_text = text
        warn = text.startswith("⚠")
        plain = text.lstrip("⚠⟳ ").strip()
        p = tokens.current()
        self.autosync_badge.setText(plain)
        self.autosync_badge.setIcon(svg_icon("status-warning", None, 14) if warn else svg_icon("sync", p.primary_soft_text, 14))
        self.autosync_badge.setIconSize(QSize(14, 14))
        self._sb_set_visible(self.autosync_badge, bool(plain))

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
        self._growth_first.stop()
        self._growth_timer.stop()
        if self._growth_worker is not None and self._growth_worker.isRunning():
            self._growth_worker.cancel()  # 최대 5분을 기다리지 않고 프로세스 트리를 먼저 종료
            self._growth_worker.wait(5000)
        if self._stmt_worker is not None:
            self._stmt_worker.wait(5000)
        for p in (self.settings_page, self.check_page):  # 실행 중 QThread 가 파괴되지 않게
            p.wait_workers()
        if self._update_worker is not None and self._update_worker.isRunning():
            self._update_worker.wait(3000)
        super().closeEvent(e)
