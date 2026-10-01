"""성장 페이지 (스펙 §6.7, M19): 풀이 잔디(M20, §6.8) · 주간 리포트(좋아진 점·지켜볼 점) · AI 코멘트 · 이번 주 숫자 · 강점·약점 · 지난 리포트.

- 서비스 읽기 함수(growth_overview / growth_report)는 파일 읽기 전용이라 UI 스레드에서 부른다. 리포트 생성·AI 코멘트는 메인 창의 GrowthWorker 가 한다
  (이 페이지는 신호로 요청만 한다: comment_requested).
- 동의는 QSettings `growth/consent/{engine}` 또는 코치 동의. 코어(service)는 동의를 모른다 — 게이트는 이 계층 책임. 앱 시작 시 모달 없음.
- "AI 분류 기반 참고용" 을 항상 표시한다 (태그는 AI 판단이라 정확한 진단이 아니라 경향치).
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ... import growth, service, solved
from ...config import Settings
from ..coach_widgets import AnswerBrowser, growth_consent_ok, set_growth_consent
from .. import motion
from ..growth_widgets import BarChart, BulletLabel, CategoryRowWidget, HeatLegend, HeatmapWidget, MetricRowWidget, day_text, number_parts, week_label
from ..theme import tokens
from ..theme.bus import bus
from ..widgets import Badge, Banner, Button, EmptyState, PageColumn, set_class

REFERENCE_NOTE = "AI 분류 기반 참고용"
EMPTY_TITLE = "아직 기록이 없어요"
EMPTY_BODY = "문제를 제출하거나 AI 코치에서 평가·힌트를 받으면 쌓여요."
MIN_TAGGED = growth.THRESH["min_tagged"]
_HEAT_INTRO_DONE = False  # 잔디 채움 애니메이션은 앱 실행당 처음 성장 탭에 들어올 때 1번만 (A11)
METRIC_ONE_COL_W = 560  # 지표 카드가 이보다 좁으면 타일 1열


def _big_number_html(prefix: str, n: float, suffix: str, color: str) -> str:
    """"지난 1년간 [178]문제 해결" 처럼 숫자만 xl 700 주색으로 (rich text 한 줄)."""
    return f"{prefix}<span style='font-size:{tokens.FONT_SIZE_XL}pt; font-weight:700; color:{color}'>{int(round(n))}</span>{suffix}"


def ask_growth_consent(parent: QWidget | None, engine_label: str) -> bool:
    """주간 코멘트 전송 동의 (엔진별 1회). 기본 포커스·Esc 는 [취소]. 동의하면 True (저장은 호출자)."""
    box = QMessageBox(
        QMessageBox.Icon.Question, "주간 AI 코멘트",
        f"{engine_label} 로 주간 집계 숫자와 분류 이름만 보냅니다.\n코드·지문·문제 번호·제목·폴더명은 보내지 않습니다. 내용은 해당 서비스의 약관에 따라 처리됩니다.",
        parent=parent,
    )
    ok = box.addButton("동의하고 코멘트 받기", QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is ok


def _range_text(start: date, end: date) -> str:
    return f"{start.isoformat()} ~ {end.strftime('%m-%d')}"


def _card() -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    set_class(card, "card")
    lay = QVBoxLayout(card)
    m = tokens.SPACE * 3  # 카드 패딩 24 (스펙 §16.5)
    lay.setContentsMargins(m, m, m, m)
    lay.setSpacing(tokens.SPACE)
    return card, lay


def _section(text: str) -> QLabel:
    lab = QLabel(text)
    set_class(lab, "section")
    return lab


def _label(text: str = "", cls: str = "muted") -> QLabel:
    lab = QLabel(text)
    set_class(lab, cls)
    lab.setWordWrap(True)
    return lab


def _clear(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()


class GrowthPage(QWidget):
    goto_requested = Signal(str)
    status_message = Signal(str)
    seen_changed = Signal()  # 리포트를 봐서 미확인 수가 줄었다 — 메인이 상태바 배지를 갱신
    comment_requested = Signal(object)  # 주 월요일(date): 수동 [코멘트 받기]/[다시 받기]/동의 후 시작
    cancel_requested = Signal()
    problem_requested = Signal(str, int)  # 잔디 날짜 목록에서 고른 문제 (주제, 번호) — 메인이 문제 탭으로 연다

    def __init__(self, qsettings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.qs = qsettings
        self.settings: Settings | None = None
        self.selected_week: date | None = None
        self.report: growth.GrowthReport | None = None
        self.overview: growth.GrowthOverview | None = None
        self.comment_state = ""  # 코멘트 카드 상태 (테스트·접근성용)
        self.blocker: str | None = None
        self._running_week: date | None = None  # 코멘트 작성 중인 주
        self._failures: dict[date, str] = {}  # 이번 실행 중 코멘트 실패 제목
        self._stale = True
        self._banner_kind = ""  # 지금 배너가 무엇인지 ("off" | "consent" | "")
        self.heat_days: dict = {}  # 풀이 잔디 {날짜: [SolvedItem]}
        self.heat_selected: date | None = None
        self._heat_total: int | None = None  # 지금 제목에 보이는 값 (카운트업 시작점)
        self._pass_shown: int | None = None
        self._metric_prev: dict[str, float] = {}
        self._metric_tiles: list[QWidget] = []
        self._metric_cols = 0
        self._build()
        bus().changed.connect(self.refresh_theme)

    # --- UI ------------------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        col = PageColumn()  # 본문 최대 폭 840 + 가운데 정렬 (스펙 §16.5)
        self.scroll.setWidget(col)
        outer.addWidget(self.scroll)
        root = col.body
        root.setSpacing(tokens.SPACE * 2)
        title = QLabel("성장")
        set_class(title, "title")
        root.addWidget(title)
        self.banner = Banner()  # 0~1개: 꺼짐 안내 / 코멘트 동의
        root.addWidget(self.banner)
        self._build_heat(root)

        holder = QWidget()
        self.stack = QStackedLayout(holder)
        self.stack.setContentsMargins(0, 0, 0, 0)
        # 0: 리포트, 1: 기록 없음, 2: 꺼짐
        self.content = QWidget()
        self.content.setObjectName("GrowthContent")
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(tokens.SPACE * 2)
        self._build_header(cl)
        self._build_comment(cl)
        self._build_metrics(cl)
        self._build_categories(cl)
        self._build_history(cl)
        self.empty = EmptyState(EMPTY_TITLE, EMPTY_BODY, icon="nav-growth")
        self.empty.setObjectName("GrowthEmpty")
        self.off_state = EmptyState("성장 기록이 꺼져 있어요", "설정에서 켜면 AI 코치 응답과 제출 결과로 주간 리포트가 쌓여요", "설정으로 이동", icon="nav-growth")
        self.off_state.setObjectName("GrowthOff")
        self.off_state.button.clicked.connect(lambda: self.goto_requested.emit("settings"))
        for w in (self.content, self.empty, self.off_state):
            self.stack.addWidget(w)
        root.addWidget(holder, 1)
        self.banner.action_clicked.connect(self._banner_action)

    def _build_heat(self, lay: QVBoxLayout) -> None:
        """풀이 잔디 카드 (맨 위): 제목 · 격자 · 범례 · 선택한 날의 문제 목록."""
        self.heat_card, hl = _card()
        self.heat_card.setObjectName("GrowthHeat")
        self.heat_title = _section("")
        self.heat_title.setObjectName("GrowthHeatTitle")
        self.heat_title.setTextFormat(Qt.TextFormat.RichText)  # 숫자만 크게 — 접근성 이름은 평문 (_set_heat_title)
        self._set_heat_title(0)
        hl.addWidget(self.heat_title)
        self.heatmap = HeatmapWidget()
        hl.addWidget(self.heatmap)
        self.heat_legend = HeatLegend()
        hl.addWidget(self.heat_legend)
        self.heat_hint = _label("칸을 누르면 그날 푼 문제가 보여요. 앱으로 낸 SWEA Pass 와 로컬 검증 통과를 세요 (같은 날 같은 문제는 1번).", "hint")
        self.heat_hint.setObjectName("GrowthHeatHint")
        hl.addWidget(self.heat_hint)
        self.day_title = _label("", "section")
        self.day_title.setObjectName("GrowthDayTitle")
        self.day_title.hide()
        hl.addWidget(self.day_title)
        self.day_list = QListWidget()
        self.day_list.setObjectName("GrowthDayList")
        self.day_list.setAccessibleName("그날 푼 문제 목록")
        self.day_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.day_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.day_list.hide()
        hl.addWidget(self.day_list)
        lay.addWidget(self.heat_card)
        self.heatmap.day_clicked.connect(self._heat_day_clicked)
        self.day_list.itemClicked.connect(self._day_item_clicked)
        self.day_list.itemActivated.connect(self._day_item_clicked)  # Enter

    def heat_setting(self) -> tuple[str, str | None]:
        """저장된 잔디 색 설정: ("follow", None) | ("fixed", "#RRGGBB"). 키 없음·쓰레기 값 = 테마 색 따르기."""
        return solved.heat_base(self.qs.value(solved.HEAT_COLOR_KEY, solved.HEAT_FOLLOW))

    def heat_base(self) -> str:
        """지금 잔디의 기준색: 따르기면 현재 테마·모드의 primary, 고정색이면 모드 보정 후 색 (저장값은 그대로)."""
        kind, hexv = self.heat_setting()
        if kind == "fixed" and hexv:
            return solved.adjust_for_mode(hexv, tokens.is_dark())
        return tokens.current().primary

    def refresh_theme(self) -> None:
        """테마·모드 전환: 잔디 기준색(따르기면 새 primary)을 다시 잡고 색을 담은 글자(rich text)를 새 팔레트로 다시 만든다. 채움 애니메이션은 재생하지 않는다."""
        self.apply_heat_color()
        if self.isVisible():
            self.refresh()

    def apply_heat_color(self) -> None:
        """설정에서 색을 바꾸면 즉시 반영."""
        base = self.heat_base()
        self.heatmap.set_base(base)
        self.heat_legend.set_base(base)

    def _refresh_heat(self) -> None:
        s = self.settings
        if s is None or not s.growth:
            self.heat_card.hide()
            self.heat_days = {}
            return
        now = growth.now()
        try:
            self.heat_days = service.growth_solved(s, now)
        except Exception:  # noqa: BLE001 — 부가 화면이 앱을 죽이지 않는다
            self.heat_days = {}
        counts = solved.counts(self.heat_days)
        self.heatmap.set_data(counts, now.date(), self.heat_base())
        self.heat_legend.set_base(self.heat_base())
        total = solved.total_last_year(self.heat_days, now.date())
        self.heat_card.show()
        self._set_heat_title(total, animate=self.isVisible())
        global _HEAT_INTRO_DONE
        if not _HEAT_INTRO_DONE and self.isVisible():  # 처음 들어올 때 1회만 잔디 채움 (갱신·hover·칸 선택에서는 재생 안 함)
            _HEAT_INTRO_DONE = True
            self.heatmap.play_reveal()
        if self.heat_selected is not None:
            self._show_day(self.heat_selected)

    def _set_heat_title(self, total: int, animate: bool = False) -> None:
        """제목 "지난 1년간 N문제 해결". 접근성 이름·툴팁은 즉시 평문 최종값, 표시 숫자만 값이 바뀐 경우 카운트업."""
        plain = f"지난 1년간 {total}문제 해결"
        color = tokens.current().primary_soft_text

        def fmt(v: float) -> str:
            return _big_number_html("지난 1년간 ", v, "문제 해결", color)

        prev, self._heat_total = self._heat_total, total
        self.heat_title.setAccessibleName(plain)
        self.heat_title.setToolTip(plain)
        if animate and (prev is None or prev != total):
            motion.count_up(self.heat_title, total, fmt, start=0 if prev is None else prev, accessible=plain)
        else:
            self.heat_title.setText(fmt(total))

    def _heat_day_clicked(self, d: date) -> None:
        self.heat_selected = d
        self._show_day(d)

    def _show_day(self, d: date) -> None:
        """선택한 날의 문제 목록. 0문제면 안내 글자."""
        items = self.heat_days.get(d, [])
        self.heatmap.select(d)
        self.day_title.setText(f"{day_text(d)} · {len(items)}문제" if items else f"{day_text(d)} · 이날은 푼 문제가 없어요")
        self.day_title.show()
        self.day_list.clear()
        for it in items:
            head = f"{it.num} · {it.title}" if it.title else str(it.num)
            li = QListWidgetItem(f"{head} · {it.topic or '-'} · {solved.VIA_LABEL[it.via]}")
            li.setData(Qt.ItemDataRole.UserRole, (it.topic, it.num))
            li.setToolTip("클릭하면 문제 탭에서 지문을 봅니다")
            self.day_list.addItem(li)
        self.day_list.setVisible(bool(items))
        if items:
            self.day_list.setFixedHeight(min(len(items), 6) * 28 + 8)
        self.heat_hint.setVisible(False)

    def _day_item_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.problem_requested.emit(str(data[0]), int(data[1]))

    def _build_header(self, lay: QVBoxLayout) -> None:
        self.header_card, hl = _card()
        self.header_card.setObjectName("GrowthHeader")
        top = QHBoxLayout()
        top.setSpacing(tokens.SPACE)
        self.range_label = QLabel()
        set_class(self.range_label, "section")
        self.state_badge = Badge("진행 중", "idle")
        self.new_badge = Badge("새 리포트", "running")
        self.new_badge.hide()
        top.addWidget(self.range_label)
        top.addWidget(self.state_badge)
        top.addWidget(self.new_badge)
        top.addStretch(1)
        hl.addLayout(top)
        big = QHBoxLayout()  # 큰 숫자 줄: "Pass N문제" + 지난 기록 대비 변화 (글자+화살표)
        big.setSpacing(tokens.SPACE * 3 // 2)
        self.pass_label = QLabel()
        self.pass_label.setObjectName("GrowthPass")
        self.pass_label.setTextFormat(Qt.TextFormat.RichText)
        set_class(self.pass_label, "section")
        self.pass_change = QLabel()
        self.pass_change.setObjectName("GrowthPassChange")
        set_class(self.pass_change, "muted")
        big.addWidget(self.pass_label, 0, Qt.AlignmentFlag.AlignBottom)
        big.addWidget(self.pass_change, 1, Qt.AlignmentFlag.AlignBottom)
        hl.addLayout(big)
        self.reference = QLabel(REFERENCE_NOTE)  # 좁은 창(720)에서 헤더가 가로로 넘치지 않게 한 줄 아래
        set_class(self.reference, "hint")
        hl.addWidget(self.reference)
        self.headline = _label("", "muted")
        self.headline.setObjectName("GrowthHeadline")
        hl.addWidget(self.headline)
        self.good_label, self.good_box = _section("좋아진 점"), QVBoxLayout()
        self.watch_label, self.watch_box = _section("지켜볼 점"), QVBoxLayout()
        self.persist_label, self.persist_box = _section("꾸준히 지적되는 약점"), QVBoxLayout()
        for lab, box in ((self.good_label, self.good_box), (self.watch_label, self.watch_box), (self.persist_label, self.persist_box)):
            box.setSpacing(tokens.SPACE // 2)
            hl.addWidget(lab)
            hl.addLayout(box)
        self.confirm_note = _label("월요일에 확정돼요", "hint")
        hl.addWidget(self.confirm_note)
        lay.addWidget(self.header_card)

    def _build_comment(self, lay: QVBoxLayout) -> None:
        self.comment_card, cl = _card()
        self.comment_card.setObjectName("GrowthCommentCard")
        head = QHBoxLayout()
        head.addWidget(_section("AI 코멘트"))
        self.comment_meta = QLabel()
        set_class(self.comment_meta, "hint")
        head.addWidget(self.comment_meta)
        head.addStretch(1)
        cl.addLayout(head)
        self.comment_browser = AnswerBrowser()
        self.comment_browser.setObjectName("GrowthCommentBrowser")
        self.comment_browser.setAccessibleName("주간 AI 코멘트")
        self.comment_browser.setFixedHeight(96)  # 내용에 맞춰 _fit_comment 가 72~240 으로 조정
        cl.addWidget(self.comment_browser)
        self.comment_text = _label("", "muted")
        self.comment_text.setObjectName("GrowthCommentText")
        cl.addWidget(self.comment_text)
        btns = QHBoxLayout()
        btns.setSpacing(tokens.BTN_GAP)
        self.comment_btn = Button("코멘트 받기")
        self.comment_btn.setObjectName("GrowthCommentButton")
        self.comment_cancel_btn = Button("취소")
        self.comment_cancel_btn.setObjectName("GrowthCommentCancel")
        self.comment_settings_btn = Button("설정으로 이동")
        self.comment_settings_btn.setObjectName("GrowthCommentSettings")
        for b in (self.comment_btn, self.comment_cancel_btn, self.comment_settings_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        cl.addLayout(btns)
        lay.addWidget(self.comment_card)
        self.comment_btn.clicked.connect(self._comment_clicked)
        self.comment_cancel_btn.clicked.connect(self.cancel_requested)
        self.comment_settings_btn.clicked.connect(lambda: self.goto_requested.emit("settings"))

    def _build_metrics(self, lay: QVBoxLayout) -> None:
        self.metrics_card, ml = _card()
        self.metrics_card.setObjectName("GrowthMetrics")
        ml.addWidget(_section("이번 주 숫자"))
        self.chart = BarChart()
        ml.addWidget(self.chart)
        self.metric_box = QGridLayout()  # 타일 그리드: 2열 (카드가 좁으면 1열). count()/itemAt(i).widget() 은 이전과 같다
        self.metric_box.setHorizontalSpacing(tokens.SPACE * 3 // 2)
        self.metric_box.setVerticalSpacing(tokens.SPACE * 3 // 2)
        ml.addLayout(self.metric_box)
        lay.addWidget(self.metrics_card)

    def _build_categories(self, lay: QVBoxLayout) -> None:
        self.category_card, cl = _card()
        self.category_card.setObjectName("GrowthCategories")
        cl.addWidget(_section("강점·약점 변화"))
        self.category_note = _label("", "hint")
        cl.addWidget(self.category_note)
        self.weak_label = _label("자주 지적된 점(약점)", "muted")
        self.weak_box = QVBoxLayout()
        self.strong_label = _label("잘한 점(강점)", "muted")
        self.strong_box = QVBoxLayout()
        for lab, box in ((self.weak_label, self.weak_box), (self.strong_label, self.strong_box)):
            box.setSpacing(0)
            cl.addWidget(lab)
            cl.addLayout(box)
        lay.addWidget(self.category_card)

    def _build_history(self, lay: QVBoxLayout) -> None:
        self.history_card, hl = _card()
        self.history_card.setObjectName("GrowthHistory")
        hl.addWidget(_section("지난 리포트"))
        self.report_list = QListWidget()
        self.report_list.setObjectName("GrowthReportList")
        self.report_list.setAccessibleName("지난 리포트 목록")
        self.report_list.setMinimumHeight(120)
        self.report_list.setMaximumHeight(220)
        hl.addWidget(self.report_list)
        lay.addWidget(self.history_card)
        self.report_list.itemSelectionChanged.connect(self._list_selected)

    # --- 설정 / 갱신 ----------------------------------------------------------------------
    def set_settings(self, settings: Settings | None) -> None:
        self.settings = settings
        self._stale = True
        self._running_week = None
        if self.isVisible():
            self.refresh()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.refresh()  # 다른 탭에서 기록이 늘었을 수 있으니 매번 (파일 읽기 전용, 가벼움)

    def _consent_ok(self, engine: str) -> bool:
        return growth_consent_ok(self.qs, engine)

    def refresh(self) -> None:
        """개요·선택 주 리포트를 다시 읽어 그린다. 성장 기록이 꺼져 있으면 꺼짐 안내만."""
        self._stale = False
        s = self.settings
        if s is None or not s.growth:
            self.overview = self.report = None
            self._refresh_heat()  # 꺼짐: 잔디 카드를 숨긴다 (기록·표시 모두 멈춤)
            self.comment_state = "off"
            self.stack.setCurrentWidget(self.off_state)
            self._set_banner("off")
            self.banner.show_message("info", "성장 기록이 꺼져 있어요", "설정에서 켜면 주간 리포트가 다시 쌓여요", [("settings", "설정으로 이동")])
            return
        if self._banner_kind == "off":
            self._set_banner("")
        self._refresh_heat()
        try:
            self.overview = service.growth_overview(s)
        except Exception:  # noqa: BLE001 — 부가 화면이 앱을 죽이지 않는다
            self.overview = None
        if self.overview is None or not self.overview.has_events:
            self.report = None
            self.comment_state = "empty"
            self.stack.setCurrentWidget(self.empty)
            self._set_banner("")
            return
        self.stack.setCurrentWidget(self.content)
        weeks = [w.week_start for w in self.overview.weeks]
        if self.selected_week not in weeks + [self.overview.this_week.week_start]:
            self.selected_week = weeks[0] if weeks else self.overview.this_week.week_start  # 기본: 가장 최근 확정, 없으면 진행 중
        self._fill_list()
        self._show_report(self.selected_week)

    def _fill_list(self) -> None:
        ov = self.overview
        self.report_list.blockSignals(True)
        self.report_list.clear()
        rows = [(ov.this_week, "이번 주 (진행 중)")]
        for w in ov.weeks[:52]:
            prefix = "새 · " if w.unseen else ""
            rows.append((w, f"{prefix}{w.week_start.strftime('%m-%d')} ~ {w.week_end.strftime('%m-%d')} · Pass {w.solved} · 좋아진 점 {w.good_count}"))
        for w, text in rows:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, w.week_start.isoformat())
            self.report_list.addItem(item)
            if w.week_start == self.selected_week:
                self.report_list.setCurrentItem(item)
        self.report_list.blockSignals(False)

    def _list_selected(self) -> None:
        items = self.report_list.selectedItems()
        if not items:
            return
        week = date.fromisoformat(items[0].data(Qt.ItemDataRole.UserRole))
        if week != self.selected_week or self.report is None:
            self.select_week(week)

    def select_week(self, week: date) -> None:
        """지난 리포트를 골라 카드들을 갱신하고 맨 위로 스크롤한다."""
        self.selected_week = week
        self._show_report(week)
        self.scroll.verticalScrollBar().setValue(0)

    # --- 리포트 그리기 ----------------------------------------------------------------------
    def _show_report(self, week: date) -> None:
        s = self.settings
        try:
            rep = service.growth_report(s, week)
        except Exception:  # noqa: BLE001
            return
        self.report = rep
        was_unseen = rep.confirmed and not rep.seen
        self.range_label.setText(_range_text(rep.week_start, rep.week_end))
        if rep.in_progress:
            self.state_badge.set_state("진행 중", "idle")
        else:
            self.state_badge.set_state("확정", "success")
        self.new_badge.setVisible(was_unseen)
        self._fill_header(rep)
        self._fill_comment(rep)
        self._fill_metrics(rep)
        self._fill_categories(rep)
        if was_unseen and self.isVisible():
            service.growth_mark_seen(s, rep.week_start)
            self.overview = service.growth_overview(s)
            self._fill_list()
            self.seen_changed.emit()

    def _fill_header(self, rep: growth.GrowthReport) -> None:
        _clear(self.good_box)
        _clear(self.watch_box)
        _clear(self.persist_box)
        good = rep.judgments_of(*growth.GOOD_KINDS)
        watch = rep.judgments_of("watch")
        persist = rep.judgments_of("persistent")
        self.headline.setText(rep.headline)
        for lab, box, items, kind in (
            (self.good_label, self.good_box, good, "success"),
            (self.watch_label, self.watch_box, watch, "warning"),
            (self.persist_label, self.persist_box, persist, "error"),
        ):
            lab.setVisible(bool(items))
            for j in items:
                box.addWidget(BulletLabel(j.text, kind))  # 6px 색 점 + 글자 (색 단독 아님)
        self.confirm_note.setVisible(rep.in_progress)
        self._fill_pass(rep)

    def _fill_pass(self, rep: growth.GrowthReport) -> None:
        """헤더의 큰 숫자 줄. N 은 바뀐 경우에만 카운트업, 접근성 이름은 즉시 평문."""
        n = rep.stats.solved
        p = tokens.current()
        row = growth.metric_rows(rep)[0]
        color = p.success_text if row.direction == "better" else p.warning_text if row.direction == "worse" else p.text_2
        self.pass_change.setText(f"<span style='color:{color}'>{row.change}</span>")
        plain = f"Pass {n}문제"

        def fmt(v: float) -> str:
            return _big_number_html("Pass ", v, "문제", p.primary_soft_text)

        prev, self._pass_shown = self._pass_shown, n
        self.pass_label.setToolTip(plain)
        if self.isVisible() and (prev is None or prev != n):
            motion.count_up(self.pass_label, n, fmt, start=0 if prev is None else prev, accessible=plain)
        else:
            self.pass_label.setText(fmt(n))
            self.pass_label.setAccessibleName(plain)

    def _fill_metrics(self, rep: growth.GrowthReport) -> None:
        values = [0.0 if st is None else float(st.solved) for st in rep.chart_stats]
        self.chart.set_data(values, [week_label(d) for d in rep.chart_weeks], len(values) - 1)
        _clear(self.metric_box)
        self._metric_tiles = []
        self._metric_cols = 0
        for row in growth.metric_rows(rep):
            parts = number_parts(row.value)
            prev = self._metric_prev.get(row.key)
            start = (0.0 if prev is None else prev) if parts is not None else None  # 숫자 하나인 값만, 처음엔 0 에서, 이후엔 바뀐 경우에만
            tile = MetricRowWidget(row, animate_from=start)
            if parts is not None:
                self._metric_prev[row.key] = parts[1]
            self._metric_tiles.append(tile)
        self._layout_metrics()

    def _layout_metrics(self) -> None:
        """타일을 2열(좁으면 1열)로 배치. 이미 놓인 타일을 옮기므로 위젯은 그대로."""
        cols = 1 if self.metrics_card.width() < METRIC_ONE_COL_W else 2
        if cols == self._metric_cols and self.metric_box.count() == len(self._metric_tiles):
            return
        self._metric_cols = cols
        for w in self._metric_tiles:
            self.metric_box.removeWidget(w)
        for i, w in enumerate(self._metric_tiles):
            self.metric_box.addWidget(w, i // cols, i % cols)
        for c in range(2):
            self.metric_box.setColumnStretch(c, 1 if c < cols else 0)

    def _fill_categories(self, rep: growth.GrowthReport) -> None:
        _clear(self.weak_box)
        _clear(self.strong_box)
        few = rep.stats.tagged < MIN_TAGGED
        self.category_note.setText(f"AI 코치를 더 사용하면 변화가 보여요 (이번 주 분류 {rep.stats.tagged}건)" if few else "")
        self.category_note.setVisible(few)
        for lab, box in ((self.weak_label, self.weak_box), (self.strong_label, self.strong_box)):
            lab.setVisible(not few)
        if few:
            return
        for weak, box in ((True, self.weak_box), (False, self.strong_box)):
            rows = growth.category_rows(rep, weak)
            if not rows:
                box.addWidget(_label("이번 주는 해당 없음", "hint"))
            for row in rows:
                box.addWidget(CategoryRowWidget(row, kind="warning" if weak else "success"))  # 약점=주황, 강점=초록 (옆 소제목이 글자로 구분)

    # --- 코멘트 카드 ------------------------------------------------------------------------
    def set_comment_running(self, week: date | None) -> None:
        """워커가 코멘트를 작성 중인 주 (None 이면 아님). 카드를 즉시 다시 그린다."""
        self._running_week = week
        if week is not None:
            self._failures.pop(week, None)
        if self.report is not None and self.settings is not None and self.settings.growth:
            self._fill_comment(self.report)

    def note_comment_failure(self, week: date | None, title: str) -> None:
        if week is not None:
            self._failures[week] = title

    def _fill_comment(self, rep: growth.GrowthReport) -> None:
        s = self.settings
        week = rep.week_start
        manual_blocker = service.growth_comment_blocker(s, self._consent_ok, manual=True)
        self.blocker = service.growth_comment_blocker(s, self._consent_ok)
        for w in (self.comment_browser, self.comment_text, self.comment_btn, self.comment_cancel_btn, self.comment_settings_btn):
            w.hide()
        self.comment_meta.setText("")
        text, button, state = "", "", ""
        if self._running_week == week:
            state, text = "loading", "코멘트 작성 중…"
            self.comment_cancel_btn.show()
        elif rep.in_progress:
            first = self.overview is not None and not self.overview.weeks
            state = "in_progress"
            text = "첫 주가 끝나면 리포트가 만들어져요" if first else "주가 끝나면 자동으로 만들어져요"
        elif rep.comment and rep.comment.get("text"):
            state = "done"
            self.comment_browser.set_markdown(str(rep.comment["text"]))
            self.comment_browser.show()
            self._fit_comment()
            when = str(rep.comment.get("at") or "")[:16].replace("T", " ")
            engine = str(rep.comment.get("engine") or "").split(" (")[0]
            self.comment_meta.setText(f"{engine} · {when}".strip(" ·"))
            button = "다시 받기" if manual_blocker in (None, "needs_consent") else ""
        elif not rep.confirmed:
            state, text = "unconfirmed", "이 주는 리포트가 확정되지 않아 통계만 표시합니다"
        elif rep.comment_status == "skipped_low_data":
            state, text = "skipped_low_data", "이 주는 기록이 적어 코멘트를 생략했어요"
        else:
            if rep.comment_status == "skipped_backlog":
                state, text = "skipped_backlog", "밀린 주라 통계만 만들었어요"
            elif rep.comment_status == "failed":
                state, text = "failed", "코멘트를 만들지 못했어요" + (f" — {self._failures[week]}" if week in self._failures else "")
            else:
                state, text = "pending", "코멘트를 곧 자동으로 만들어요"
            button = "다시 받기" if rep.comment_status == "failed" else "코멘트 받기"
            if manual_blocker == "no_engine":
                state, text, button = "no_engine", "AI 엔진을 찾지 못해 코멘트를 만들지 못했어요", ""
                self.comment_settings_btn.show()
            elif self.blocker == "comment_off" and rep.comment_status == "pending":
                state, text = "comment_off", "주간 AI 코멘트 자동 생성이 꺼져 있어요. 필요하면 [코멘트 받기] 를 누르세요"
            elif self.blocker == "needs_consent":
                text += " · 동의가 필요해요"
        self.comment_state = state
        self.comment_text.setText(text)
        self.comment_text.setVisible(bool(text))
        self.comment_btn.setText(button or "코멘트 받기")
        self.comment_btn.setVisible(bool(button))
        self._update_consent_banner(rep, manual_blocker)

    def _fit_comment(self) -> None:
        """코멘트 본문 높이를 내용에 맞춘다 (짧은 코멘트가 빈 칸으로 늘어나지 않게). 72~240px, 넘치면 안에서 스크롤."""
        b = self.comment_browser
        doc = b.document()
        doc.setTextWidth(max(b.viewport().width(), 320))
        b.setFixedHeight(max(72, min(int(doc.size().height()) + 2 * b.frameWidth() + 16, 240)))

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self._metric_tiles:
            self._layout_metrics()
        if self.comment_state == "done":
            self._fit_comment()

    def _update_consent_banner(self, rep: growth.GrowthReport, manual_blocker: str | None) -> None:
        need = (
            manual_blocker == "needs_consent" and rep.confirmed and not rep.in_progress and self._running_week is None
            and rep.comment_status in ("pending", "failed", "skipped_backlog") and not (rep.comment or {}).get("text")
        )
        if need:
            engine = service.growth_comment_engine(self.settings)
            label = engine.label if engine is not None else "AI"
            self._banner_kind = "consent"
            self.banner.show_message(
                "info", "주간 AI 코멘트를 받으려면 동의가 필요해요",
                f"주간 AI 코멘트는 집계 숫자와 분류 이름만 {label} 으로 보냅니다(코드·지문·문제 번호 제외).", [("consent", "동의하고 코멘트 받기")],
            )
        elif self._banner_kind == "consent":
            self._set_banner("")

    def _set_banner(self, kind: str) -> None:
        """kind 가 "" 이면 배너를 숨긴다."""
        self._banner_kind = kind
        if not kind:
            self.banner.hide()

    # --- 동작 ------------------------------------------------------------------------------
    def _banner_action(self, key: str) -> None:
        if key == "settings":
            self.goto_requested.emit("settings")
        elif key == "consent":
            self._request_comment()

    def _comment_clicked(self) -> None:
        self._request_comment()

    def _request_comment(self) -> None:
        """[코멘트 받기]/[다시 받기]/[동의하고 코멘트 받기]: 필요하면 동의를 받고 워커 시작을 요청한다."""
        if self.report is None or self.settings is None or self._running_week is not None:
            return
        week = self.report.week_start
        engine = service.growth_comment_engine(self.settings)
        if engine is None:
            self.goto_requested.emit("settings")
            return
        if not self._consent_ok(engine.name):
            if not ask_growth_consent(self, engine.label):
                return
            set_growth_consent(self.qs, engine.name)
        self.comment_requested.emit(week)
