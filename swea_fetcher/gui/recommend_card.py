"""오늘의 추천 카드 (M24): 성장 탭 풀이 잔디 아래. 수준 한 줄 · 추천 문제 3~5행 · AI 안내 줄 · 문제 목록 푸터.

- 계산·네트워크·AI 는 전부 RecommendWorker(워커 스레드)가 한다. 이 위젯은 서비스 결과(RecommendResult)를 그리기만 한다 (파일·네트워크·AI 직접 호출 없음).
- 항목을 누르면 recommend_open_requested(번호) — 메인 창이 문제 탭에서 지문을 연다 (저장·덮어쓰기 없음).
- 동의 게이트: AI 약점 분석은 성장/코치 동의(`growth_consent_ok`)가 없으면 호출하지 않고 카드에 안내 + [동의하고 사용] 만 띄운다 (앱 시작 시 모달 없음).
- 색은 tokens/QSS/Badge 로만 (색 리터럴 금지 — tests/gui/test_no_hardcoded_colors).
- 상태(self.state, 테스트·접근성용): loading · catalog_loading · ready · cold_start · empty · error · offline · logged_out · hidden.
"""

from __future__ import annotations

import time
from datetime import date

from PySide6.QtCore import QRectF, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QSizePolicy, QVBoxLayout, QWidget

from .. import ai_engine, growth, service
from ..config import Settings
from . import motion
from .coach_widgets import growth_consent_ok, set_growth_consent
from .theme import tokens
from .theme.bus import bus
from .widgets import Badge, Button, ElidedLabel, EmptyState, SegmentedControl, Skeleton, Spinner, set_class
from .workers import RecommendWorker

START_LEVEL_KEY = "recommend/start_level"
START_LEVELS = (1, 2, 3, 4, 5)
OPEN_TOOLTIP = "클릭하면 문제 탭에서 지문을 봅니다 (저장되지 않아요)"
LEVEL_TOOLTIP = (
    "최근 90일에 푼 문제의 난이도(D1~D8)와 풀기 전 오답 횟수로 추정해요.\n"
    "오답 1회 이하로 깨끗하게 3문제 이상 푼 가장 높은 난이도가 내 수준이고, 그 난이도와 한 단계 위에서 골라요.\n"
    "참고용입니다."
)
KIND_BADGE = {"retry": ("다시 도전", "warning"), "fit": ("수준 맞춤", "idle"), "fill": ("수준 맞춤", "idle"), "stretch": ("한 단계 위", "running")}
LOAD_THROTTLE_S = 3.0  # 탭에 들어올 때마다 읽기 워커를 또 띄우지 않게
CATALOG_ERRORS = {  # 코드 → (제목, 힌트). 스택·URL·쿠키는 보이지 않는다
    "network": ("문제 목록을 받지 못했어요", "네트워크를 확인해 주세요"),
    "rate_limited": ("SWEA 가 잠시 요청을 제한하고 있어요", "몇 분 뒤에 다시 시도해 주세요"),
    "parse": ("문제 목록을 읽지 못했어요", "SWEA 페이지 구조가 바뀐 것 같아요. 앱을 업데이트해 주세요"),
    "shrunk": ("문제 목록이 평소와 달라서 쓰지 않았어요", "이전 목록을 계속 사용해요"),
    "budget": ("문제 목록을 받는 데 너무 오래 걸렸어요", "네트워크를 확인하고 다시 시도해 주세요"),
    "cancelled": ("문제 목록 받기를 취소했어요", "필요할 때 다시 시도해 주세요"),
    "session": ("SWEA 에 연결하지 못했어요", "설정에서 로그인을 확인해 주세요"),
    "unwritable": ("문제 목록을 저장하지 못했어요", "설정의 루트 폴더 위치를 확인해 주세요"),
    "cooldown": ("문제 목록은 조금 뒤에 다시 받을 수 있어요", ""),
    "blocked": ("문제 목록을 받지 못했어요", "잠시 뒤 다시 시도해 주세요"),
}


def count_text(n: int | None) -> str:
    """참여자 수 "7K" 표기 (대략값)."""
    if n is None:
        return "-"
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M"
    if n >= 1000:
        return f"{n / 1000:g}K"
    return str(n)


def level_state(level: int) -> str:
    """난이도 배지 톤 (글자로도 구분되므로 색만으로 의미를 전하지 않는다): D1~2 success / D3~4 info(running) / D5+ warning."""
    return "success" if level <= 2 else ("running" if level <= 4 else "warning")


def ask_recommend_consent(parent: QWidget | None, engine_label: str) -> bool:
    """AI 약점 분석 전송 동의 (엔진별 1회). 기본 포커스·Esc 는 [취소]. 동의하면 True (저장은 호출자)."""
    box = QMessageBox(
        QMessageBox.Icon.Question, "오늘의 추천 · AI 약점 분석",
        f"{engine_label} 로 약점 분류 이름·수준 숫자·후보 문제 제목만 보냅니다.\n"
        "코드·지문·푼 문제 목록·폴더명은 보내지 않습니다. 내용은 해당 서비스의 약관에 따라 처리됩니다.",
        parent=parent,
    )
    ok = box.addButton("동의하고 사용", QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is ok


class _LevelSegments(SegmentedControl):
    """시작 수준 D1~D5 선택 (콜드 스타트). 글자만 있는 좁은 칸 — 720px 창에서도 폭이 고정이다."""

    CELL_MIN_W = 52

    @property
    def _icons(self) -> bool:  # 아이콘 없음 (기반 클래스가 resize 마다 대입해도 무시)
        return False

    @_icons.setter
    def _icons(self, _v: bool) -> None:
        pass


class _RowSkeleton(Skeleton):
    """추천 행 자리표시 (막대 2줄)."""

    WIDTHS = (1.0, 0.6)


class RecommendRow(QFrame):
    """추천 문제 한 행. 클릭/Enter/Space 로 열기. 색은 그릴 때 tokens.current() 에서 읽는다."""

    activated = Signal(int)

    def __init__(self, rec: service.Recommendation, parent=None) -> None:
        super().__init__(parent)
        self.rec = rec
        self.setObjectName(f"RecommendItem_{rec.num}")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._kb_focus = False
        self._down = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(tokens.SPACE * 3 // 2, tokens.SPACE * 3 // 2, tokens.SPACE * 3 // 2, tokens.SPACE * 3 // 2)
        lay.setSpacing(tokens.SPACE // 2)
        top = QHBoxLayout()
        top.setSpacing(tokens.SPACE)
        num = QLabel(f"{rec.num}.")
        num.setObjectName("RecommendNum")
        set_class(num, "section")
        title = ElidedLabel(mode=Qt.TextElideMode.ElideRight)
        title.setObjectName("RecommendTitle")
        title.setText(rec.title or "(제목 없음)")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)  # 클릭이 행으로 전달되게
        self.level_badge = Badge(f"D{rec.level}" if rec.level else "D?", level_state(rec.level) if rec.level else "idle")
        self.level_badge.setObjectName("RecommendLevelBadge")
        text, state = KIND_BADGE.get(rec.kind, KIND_BADGE["fit"])
        self.kind_badge = Badge(text, state)
        self.kind_badge.setObjectName("RecommendKindBadge")
        top.addWidget(num)
        top.addWidget(title, 1)
        top.addWidget(self.level_badge)
        top.addWidget(self.kind_badge)
        self.solved_badge: Badge | None = None
        if rec.solved_today:
            self.solved_badge = Badge("해결", "success")
            self.solved_badge.setObjectName("RecommendSolvedBadge")
            top.addWidget(self.solved_badge)
        lay.addLayout(top)
        self.reason = QLabel(rec.reason)
        self.reason.setObjectName("RecommendReason")
        set_class(self.reason, "muted")
        self.reason.setWordWrap(True)
        lay.addWidget(self.reason)
        meta = " · ".join(p for p in (
            f"정답률 {rec.pass_rate:.1f}%" if rec.pass_rate is not None else "",
            f"참여자 {count_text(rec.participants)}" if rec.participants is not None else "",
        ) if p)
        self.meta = QLabel(meta)
        self.meta.setObjectName("RecommendMeta")
        set_class(self.meta, "hint")
        self.meta.setWordWrap(True)
        self.meta.setVisible(bool(meta))
        lay.addWidget(self.meta)
        for w in self.findChildren(QWidget):  # 클릭·호버는 행이 받는다
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        parts = [f"{rec.num}번 {rec.title}".strip(), f"난이도 D{rec.level}" if rec.level else "",
                 f"정답률 {rec.pass_rate:.1f}%" if rec.pass_rate is not None else "", rec.reason, "해결함" if rec.solved_today else ""]
        self.setAccessibleName(", ".join(p for p in parts if p))
        self.setToolTip(OPEN_TOOLTIP)

    # --- 동작 ---
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self.update()
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        was, self._down = self._down, False
        self.update()
        if was and e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.activated.emit(self.rec.num)
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.rec.num)
            e.accept()
        else:
            super().keyPressEvent(e)

    def focusInEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = False
        super().focusOutEvent(e)
        self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        super().enterEvent(e)
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        super().leaveEvent(e)
        self.update()

    # --- 그리기 ---
    def paintEvent(self, e) -> None:  # noqa: N802
        p = tokens.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._down or self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.hover_fill))
            painter.drawRoundedRect(r, tokens.RADIUS_MD, tokens.RADIUS_MD)
        else:
            painter.setPen(QPen(QColor(p.border), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(r, tokens.RADIUS_MD, tokens.RADIUS_MD)
        if self._kb_focus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.primary), 2))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), tokens.RADIUS_MD, tokens.RADIUS_MD)
        painter.end()


class RecommendCard(QFrame):
    recommend_open_requested = Signal(int)
    goto_requested = Signal(str)

    def __init__(self, qsettings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.qs = qsettings
        self.settings: Settings | None = None
        self.state = "hidden"
        self.result: service.RecommendResult | None = None
        self.rows: list[RecommendRow] = []
        self._worker: RecommendWorker | None = None
        self._queued: str | None = None
        self._touched = False  # 사용자가 [다른 추천]·항목 열기를 했다 (AI 가 늦게 와도 보던 화면을 바꾸지 않는다)
        self._failure: tuple[str, str] | None = None  # 마지막 카탈로그 실패 (코드, 힌트)
        self._notices: set[str] = set()
        self._dl: tuple[int, int] | None = None  # 카탈로그 받는 중 (완료, 전체)
        self._ai_status = "none"
        self._ai_engines: list[str] = []
        self._ai_pending = False
        self._items_key: tuple = ()
        self._last_start = 0.0
        self._footer_warn = ""
        self.setObjectName("GrowthRecommend")
        set_class(self, "card")
        self._build()
        self.hide()
        bus().changed.connect(self.refresh_theme)

    # --- UI -----------------------------------------------------------------------------
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        m = tokens.SPACE * 3
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(tokens.SPACE)
        head = QHBoxLayout()
        head.setSpacing(tokens.SPACE)
        title = QLabel("오늘의 추천")
        title.setObjectName("RecommendTitleLabel")
        set_class(title, "section")
        self.ai_badge = Badge("규칙 기반", "idle")
        self.ai_badge.setObjectName("RecommendAiBadge")
        self.ai_badge.hide()
        self.shuffle_btn = Button("다른 추천")
        self.shuffle_btn.setObjectName("RecommendShuffle")
        head.addWidget(title)
        head.addWidget(self.ai_badge)
        head.addStretch(1)
        head.addWidget(self.shuffle_btn)
        lay.addLayout(head)
        self.level_label = QLabel()
        self.level_label.setObjectName("RecommendLevel")
        set_class(self.level_label, "muted")
        self.level_label.setWordWrap(True)
        self.level_label.setToolTip(LEVEL_TOOLTIP)
        lay.addWidget(self.level_label)
        # 콜드 스타트 시작 수준 선택기
        self.picker = QWidget()
        self.picker.setObjectName("RecommendPicker")
        pl = QVBoxLayout(self.picker)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(tokens.SPACE // 2)
        self.picker_hint = QLabel("시작 수준을 골라 주세요 · 기록이 쌓이면 자동으로 맞춰요")
        set_class(self.picker_hint, "hint")
        self.picker_hint.setWordWrap(True)
        self.segments = _LevelSegments(items=tuple((str(n), f"D{n}", "") for n in START_LEVELS), default="2", name="시작 수준")
        self.segments.setObjectName("RecommendLevelPicker")
        self.segments.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.segments.setFixedWidth(self.segments.minimumSizeHint().width() + 8)
        pl.addWidget(self.picker_hint)
        pl.addWidget(self.segments, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.picker)
        # 본문: 행 목록 / 스켈레톤 / 상태 메시지 / 빈 상태
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(tokens.SPACE)
        lay.addLayout(self.rows_box)
        self.skeleton = QWidget()
        self.skeleton.setObjectName("RecommendSkeleton")
        sk = QVBoxLayout(self.skeleton)
        sk.setContentsMargins(0, 0, 0, 0)
        sk.setSpacing(tokens.SPACE)
        for _ in range(4):
            sk.addWidget(_RowSkeleton())
        lay.addWidget(self.skeleton)
        self.status_box = QWidget()
        self.status_box.setObjectName("RecommendStatusBox")
        st = QVBoxLayout(self.status_box)
        st.setContentsMargins(0, 0, 0, 0)
        st.setSpacing(tokens.SPACE // 2)
        self.status_title = QLabel()
        self.status_title.setObjectName("RecommendStatus")
        set_class(self.status_title, "muted")
        self.status_title.setWordWrap(True)
        self.status_hint = QLabel()
        self.status_hint.setObjectName("RecommendStatusHint")
        set_class(self.status_hint, "hint")
        self.status_hint.setWordWrap(True)
        btns = QHBoxLayout()
        btns.setSpacing(tokens.BTN_GAP)
        self.retry_btn = Button("다시 시도")
        self.retry_btn.setObjectName("RecommendRetry")
        self.cancel_btn = Button("취소")
        self.cancel_btn.setObjectName("RecommendCancel")
        self.settings_btn = Button("설정으로 이동")
        self.settings_btn.setObjectName("RecommendSettings")
        for b in (self.retry_btn, self.cancel_btn, self.settings_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        st.addWidget(self.status_title)
        st.addWidget(self.status_hint)
        st.addLayout(btns)
        lay.addWidget(self.status_box)
        self.empty = EmptyState("추천할 문제가 없어요", "이 수준의 문제를 모두 풀었어요. 시작 수준을 올려 보세요", icon="nav-growth")
        self.empty.setObjectName("RecommendEmpty")
        lay.addWidget(self.empty)
        # 안내 줄 (오프라인·로그아웃)
        self.note_row = QWidget()
        self.note_row.setObjectName("RecommendNoteRow")
        nl = QHBoxLayout(self.note_row)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(tokens.SPACE)
        self.note_label = QLabel()
        self.note_label.setObjectName("RecommendNote")
        set_class(self.note_label, "muted")
        self.note_label.setWordWrap(True)
        self.note_btn = Button("설정으로 이동")
        self.note_btn.setObjectName("RecommendNoteSettings")
        set_class(self.note_btn, "link")
        nl.addWidget(self.note_label, 1)
        nl.addWidget(self.note_btn)
        lay.addWidget(self.note_row)
        # AI 안내 줄
        self.ai_row = QWidget()
        self.ai_row.setObjectName("RecommendAiRow")
        al = QHBoxLayout(self.ai_row)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(tokens.SPACE)
        self.spinner = Spinner()
        self.spinner.setObjectName("RecommendAiSpinner")
        self.ai_note = QLabel()
        self.ai_note.setObjectName("RecommendAiNote")
        set_class(self.ai_note, "hint")
        self.ai_note.setWordWrap(True)
        self.ai_btn = Button("")
        self.ai_btn.setObjectName("RecommendAiAction")
        set_class(self.ai_btn, "link")
        al.addWidget(self.spinner)
        al.addWidget(self.ai_note, 1)
        al.addWidget(self.ai_btn)
        lay.addWidget(self.ai_row)
        # 푸터
        foot = QHBoxLayout()
        foot.setSpacing(tokens.SPACE)
        self.footer = QLabel()
        self.footer.setObjectName("RecommendFooter")
        set_class(self.footer, "hint")
        self.footer.setWordWrap(True)
        self.refresh_btn = Button("새로 받기")
        self.refresh_btn.setObjectName("RecommendRefresh")
        set_class(self.refresh_btn, "link")
        foot.addWidget(self.footer, 1)
        foot.addWidget(self.refresh_btn)
        lay.addLayout(foot)

        self.shuffle_btn.clicked.connect(self._shuffle_clicked)
        self.retry_btn.clicked.connect(self._retry_clicked)
        self.cancel_btn.clicked.connect(self.cancel)
        self.settings_btn.clicked.connect(lambda: self.goto_requested.emit("settings"))
        self.note_btn.clicked.connect(lambda: self.goto_requested.emit("settings"))
        self.ai_btn.clicked.connect(self._ai_action)
        self.refresh_btn.clicked.connect(lambda: self._start("refresh_catalog"))
        self.segments.selected_changed.connect(self._level_picked)

    # --- 설정 / 표시 ----------------------------------------------------------------------
    def enabled(self) -> bool:
        s = self.settings
        return s is not None and bool(s.growth and s.recommend)

    def set_settings(self, settings: Settings | None) -> None:
        """설정이 바뀜(켜기/끄기·기록 지우기): 화면 상태를 처음부터 다시 만든다. 진행 중 워커는 취소한다."""
        self.settings = settings
        self.cancel()
        self.result = None
        self._failure = None
        self._notices = set()
        self._dl = None
        self._ai_status, self._ai_engines, self._ai_pending = "none", [], False
        self._touched = False
        self._footer_warn = ""
        self._last_start = 0.0
        self._items_key = ()
        self._queued = None
        self._render()

    def sync_visibility(self) -> bool:
        on = self.enabled()
        self.setVisible(on)
        if not on:
            self.state = "hidden"
        return on

    def start_level(self) -> int | None:
        try:
            v = int(self.qs.value(START_LEVEL_KEY, 0) or 0)
        except (TypeError, ValueError):
            return None
        return v if v in START_LEVELS else None

    def ensure_loaded(self) -> None:
        """성장 탭이 보일 때: 오늘 첫 진입이면 auto 워커(카탈로그·규칙·AI), 같은 날 재진입이면 규칙만 조용히 다시 읽는다 (해결 배지 갱신)."""
        if not self.sync_visibility():
            return
        if self._worker is not None or time.monotonic() - self._last_start < LOAD_THROTTLE_S:
            return
        today = growth.now().date()
        if self.result is not None and self.result.day != today:  # 날짜가 바뀜: 새 세트
            self.result, self._failure, self._notices, self._touched = None, None, set(), False
            self._ai_status, self._ai_engines = "none", []
        if self.result is not None and self.result.items:
            self._start("rules")
        elif self._failure is not None:
            self._render()  # 실패 상태는 [다시 시도] 로만 (탭에 들어올 때마다 요청하지 않는다)
        else:
            self._start("auto")

    # --- 워커 ------------------------------------------------------------------------------
    def _consented(self) -> frozenset:
        return frozenset(k for k in ai_engine.ENGINE_NAMES if growth_consent_ok(self.qs, k))

    def _start(self, mode: str) -> None:
        if not self.enabled():
            return
        if self._worker is not None:
            if mode != "auto":
                self._queued = mode
            return
        self._last_start = time.monotonic()
        if mode in ("auto", "refresh_catalog"):
            self._failure = None
        w = RecommendWorker(self.settings, mode, self.start_level(), self._consented(), touched=lambda: self._touched, parent=self)
        w.rule_ready.connect(self._on_rule)
        w.ai_started.connect(self._on_ai_started)
        w.ai_ready.connect(self._on_ai_ready)
        w.catalog_progress.connect(self._on_progress)
        w.catalog_updated.connect(self._on_catalog_updated)
        w.catalog_failed.connect(self._on_catalog_failed)
        w.notice.connect(self._on_notice)
        w.failed.connect(self._on_worker_failed)
        w.finished.connect(self._worker_finished)
        self._worker = w
        w.start()
        self._render()

    def cancel(self) -> None:
        """진행 중 워커 취소 (AI 프로세스 트리 종료, 카탈로그는 페이지 사이에서 중단)."""
        w = self._worker
        if w is not None:
            w.cancel()

    def wait_workers(self, ms: int = 5000) -> None:
        """창 닫기: 먼저 cancel() 로 AI 프로세스를 죽이고 스레드가 끝나길 기다린다."""
        w = self._worker
        if w is not None and w.isRunning():
            w.cancel()
            w.wait(ms)

    def _worker_finished(self) -> None:
        w, self._worker = self._worker, None
        if w is not None:
            w.deleteLater()
        self._dl = None
        self._ai_pending = False
        queued, self._queued = self._queued, None
        self._render()
        if queued is not None:
            self._start(queued)

    # --- 워커 신호 ---------------------------------------------------------------------------
    def _on_rule(self, res) -> None:
        self.result = res
        self._failure = None if res.items else self._failure
        self._dl = None
        st = res.ai_status
        if st in ("ok", "failed", "off", "skipped_low_data"):
            self._ai_status = st
            self._ai_engines = list(res.ai_engines)
        elif st == "none" and self._ai_status in ("", "ok", "failed", "off", "skipped_low_data"):
            self._ai_status = "none"
        self._render(animate=True)

    def _on_ai_started(self, engines) -> None:
        self._ai_pending = True
        self._ai_status = "pending"
        self._ai_engines = list(engines or [])
        self._render()

    def _on_ai_ready(self, res) -> None:
        self._ai_pending = False
        self._ai_status = res.ai_status
        self._ai_engines = list(res.ai_engines)
        if res.ai_status == "ok":
            self.result = res  # 보던 화면을 바꿔도 되는 경우만 서비스가 items 를 교체해서 돌려준다
        elif self.result is not None:
            self.result.weak_tagged = res.weak_tagged
        self._render(animate=res.ai_status == "ok")

    def _on_progress(self, done: int, total: int) -> None:
        self._dl = (done, total)
        self._render()

    def _on_catalog_updated(self, status) -> None:
        self._dl = None
        self._failure = None
        self._footer_warn = ""
        if self.result is not None:
            self.result.catalog = status
        self._render()

    def _on_catalog_failed(self, code: str, hint: str, usable: bool) -> None:
        self._dl = None
        if usable:  # 저장된 목록으로 계속 추천한다 — 오류 상태 대신 푸터 경고 (오프라인이면 안내 줄)
            self._footer_warn = CATALOG_ERRORS[code][0] if code in ("cooldown", "cancelled") else "문제 목록을 새로 받지 못해 저장된 목록을 쓰고 있어요"
            self._failure = (code, hint) if code == "network" else None
        else:
            self._failure = (code, hint)
        self._render()

    def _on_notice(self, kind: str) -> None:
        self._notices.add(kind)
        self._render()

    def _on_worker_failed(self, title: str, hint: str, _detail: str) -> None:
        self._dl = None
        self._failure = ("blocked", hint)
        self._render()

    # --- 사용자 동작 ---------------------------------------------------------------------------
    def _shuffle_clicked(self) -> None:
        if self._worker is not None or self.result is None or not self.result.items:
            return
        self._touched = True
        self._start("shuffle")

    def _retry_clicked(self) -> None:
        self._start("refresh_catalog" if (self._failure is not None or self.result is None) else "auto")

    def _open(self, num: int) -> None:
        self._touched = True
        self.recommend_open_requested.emit(num)

    def _level_picked(self, key: str) -> None:
        try:
            n = int(key)
        except ValueError:
            return
        self.qs.setValue(START_LEVEL_KEY, n)
        self._touched = True
        self._start("rules")

    def _ai_action(self) -> None:
        st = self._ai_status
        if st == "needs_consent":
            if self.settings is None:
                return
            engine = service.growth_comment_engine(self.settings)
            if engine is None:
                self.goto_requested.emit("settings")
                return
            if not ask_recommend_consent(self, engine.label):
                return
            set_growth_consent(self.qs, engine.name)
            self._start("retry_ai")
        elif st == "no_engine":
            self.goto_requested.emit("settings")
        elif st in ("failed", "cancelled"):
            self._start("retry_ai")

    # --- 그리기 ---------------------------------------------------------------------------------
    def refresh_theme(self) -> None:
        """테마·모드 전환: 행을 새로 만든다 (색은 QSS·토큰으로만 — 이미 있는 위젯은 앱 QSS 가 다시 칠한다)."""
        if self.rows:
            self._items_key = ()
            self._render()

    def _compute_state(self) -> str:
        res = self.result
        has_items = bool(res and res.items)
        if not self.enabled():
            return "hidden"
        if self._dl is not None:
            return "catalog_loading"
        if not has_items:
            if self._failure is not None:
                return "offline" if self._failure[0] == "network" else "error"
            if res is None:
                return "loading"
            if res.catalog is not None and not res.catalog.usable:
                return "loading" if self._worker is not None else "error"
            return "empty"
        if self._failure is not None and self._failure[0] == "network":
            return "offline"
        if "logged_out" in self._notices:
            return "logged_out"
        return "cold_start" if res.level is not None and res.level.cold else "ready"

    def _render(self, animate: bool = False) -> None:
        if not self.sync_visibility():
            return
        res = self.result
        state = self._compute_state()
        self.state = state
        busy = self._worker is not None
        showing_items = state in ("ready", "cold_start", "offline", "logged_out") and bool(res and res.items)
        # 수준 줄
        if res is not None and res.level is not None:
            self.level_label.setText(f"내 수준 D{res.level.level} · {res.level.basis}")
            self.level_label.show()
        else:
            self.level_label.hide()
        cold = bool(res and res.level is not None and res.level.cold and res.catalog is not None and res.catalog.usable)
        self.picker.setVisible(cold)
        if cold:
            saved = self.start_level()
            self.segments.set_value(str(saved if saved else min(res.level.level, 5)))
        # 행 목록
        self._fill_rows(res if showing_items else None, animate)
        self.skeleton.setVisible(state in ("loading", "catalog_loading"))
        # 상태 메시지
        self._fill_status(state)
        self.empty.setVisible(state == "empty")
        if state == "empty":
            body = "이 수준의 문제를 모두 풀었어요. 시작 수준을 올려 보세요" if cold else "이 수준의 문제를 모두 풀었어요. 문제 목록을 새로 받아 보세요"
            labels = self.empty.findChildren(QLabel)
            if len(labels) >= 2:
                labels[-1].setText(body)
        # 안내·AI·푸터
        self._fill_note(state)
        self._fill_ai(state)
        self._fill_footer(res)
        self.shuffle_btn.setEnabled(showing_items and not busy)
        self.shuffle_btn.setToolTip("" if showing_items and not busy else ("추천을 고르는 중이에요" if busy else "추천할 문제가 있을 때 쓸 수 있어요"))
        self.shuffle_btn.setVisible(state not in ("error", "offline", "catalog_loading") or showing_items)
        if res is not None and showing_items:
            ai_used = res.source in ("ai", "mixed")
            self.ai_badge.set_state("AI 분석" if ai_used else "규칙 기반", "running" if ai_used else "idle")
        else:
            self.ai_badge.hide()
        self.updateGeometry()

    def _fill_rows(self, res, animate: bool) -> None:
        key = tuple((i.num, i.kind, i.reason, i.source, i.solved_today, i.title, i.level) for i in res.items) if res is not None else ()
        if key == self._items_key:
            return
        self._items_key = key
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.rows = []
        if res is None:
            return
        for rec in res.items:
            row = RecommendRow(rec)
            row.activated.connect(self._open)
            self.rows_box.addWidget(row)
            self.rows.append(row)
        if animate and self.rows and self.isVisible():
            for row in self.rows:
                motion.fade_in(row)

    def _fill_status(self, state: str) -> None:
        title = hint = ""
        retry = cancel = settings = False
        if state == "catalog_loading":
            done, total = self._dl or (0, 0)
            title, hint = f"문제 목록을 받는 중… {done}/{total}", "처음 한 번만 받아요 (1분 안팎). 받는 동안 다른 화면을 써도 돼요"
            cancel = True
        elif state == "loading":
            title = "추천을 고르는 중…"
        elif state in ("error", "offline"):
            code, hint_in = self._failure or ("blocked", "")
            if state == "offline":
                title, hint = "인터넷에 연결되면 문제 목록을 받아와요", "네트워크를 확인한 뒤 다시 시도해 주세요"
            else:
                title, hint = CATALOG_ERRORS.get(code, CATALOG_ERRORS["blocked"])
                hint = hint_in or hint
            retry = True
            settings = code in ("session", "unwritable")
        has_items = bool(self.result and self.result.items)
        show = state in ("catalog_loading", "loading") or (state in ("error", "offline") and not has_items)
        self.status_box.setVisible(show)
        self.status_title.setText(title)
        self.status_hint.setText(hint)
        self.status_hint.setVisible(bool(hint))
        self.retry_btn.setVisible(retry)
        self.cancel_btn.setVisible(cancel)
        self.settings_btn.setVisible(settings)
        set_class(self.status_title, "error" if state == "error" else "muted")
        self.status_box.setAccessibleName(" ".join(p for p in (title, hint) if p))

    def _fill_note(self, state: str) -> None:
        text, btn = "", False
        if self._failure is not None and self._failure[0] == "network" and self.result is not None and self.result.items:
            text = "오프라인이라 저장된 문제 목록으로 추천했어요"
        elif "logged_out" in self._notices and self.result is not None and self.result.items:
            text, btn = "SWEA 풀이 기록을 읽지 못해 앱 기록만 사용했어요", True
        self.note_label.setText(text)
        self.note_btn.setVisible(bool(text) and btn)
        self.note_row.setVisible(bool(text))
        self.note_label.setAccessibleName(text)

    def _fill_ai(self, state: str) -> None:
        st = self._ai_status
        res = self.result
        shows = res is not None and bool(res.items) and state in ("ready", "cold_start", "offline", "logged_out")
        label = " · ".join(ai_engine.ENGINE_SHORT.get(k, k) for k in self._ai_engines)
        text, btn = "", ""
        if st == "pending":
            text = "AI 가 약점을 분석하는 중…"
        elif st == "ok":
            text = "AI 가 약점을 반영했어요" + (f" · {label}" if label else "")
        elif st == "needs_consent":
            text, btn = "AI 약점 분석을 쓰려면 동의가 필요해요", "동의하고 사용"
        elif st == "no_engine":
            text, btn = "AI 엔진을 찾지 못해 규칙 기반으로 추천했어요", "설정으로 이동"
        elif st == "skipped_low_data":
            n = res.weak_tagged if res is not None else 0
            text = f"AI 코치에서 분류가 {service.AI_MIN_TAGGED}건 쌓이면 약점 맞춤 추천을 해요 (현재 {n}건)"
        elif st == "failed":
            text, btn = "AI 분석에 실패해 규칙 기반으로 추천했어요", "다시 시도"
        elif st == "cancelled":
            text, btn = "AI 분석을 취소했어요", "다시 시도"
        self.ai_row.setVisible(shows and bool(text))
        self.spinner.setVisible(st == "pending")
        self.ai_note.setText(text)
        self.ai_note.setAccessibleName(text)  # 상태 변화(요청 중/실패/AI 반영)를 보조기기에 전달
        self.ai_btn.setVisible(bool(btn))
        self.ai_btn.setText(btn)
        self.ai_btn.setEnabled(not self._ai_pending)

    def _fill_footer(self, res) -> None:
        cat = res.catalog if res is not None else None
        if cat is None or not cat.usable:
            self.footer.setText(self._footer_warn)
            self.footer.setVisible(bool(self._footer_warn))
            self.refresh_btn.hide()
            return
        when = cat.fetched_at.strftime("%Y-%m-%d") if cat.fetched_at else "-"
        text = f"문제 목록 {when} 기준 · {cat.count:,}문제"
        if self._footer_warn:
            text += f" · {self._footer_warn}"
        self.footer.setText(text)
        self.footer.show()
        busy = self._worker is not None
        wait = cat.manual_wait
        self.refresh_btn.setVisible(True)
        self.refresh_btn.setEnabled(not busy and wait <= 0)
        self.refresh_btn.setToolTip("" if wait <= 0 else f"{wait // 60 + 1}분 뒤에 다시 받을 수 있어요 (1시간에 한 번)")
