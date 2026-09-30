"""성장 페이지 (스펙 §6.7, M19): 주간 리포트(좋아진 점·지켜볼 점) · AI 코멘트 · 이번 주 숫자 · 강점·약점 · 지난 리포트.

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

from ... import growth, service
from ...config import Settings
from ..coach_widgets import AnswerBrowser, growth_consent_ok, set_growth_consent
from ..growth_widgets import BarChart, CategoryRowWidget, MetricRowWidget, week_label
from ..theme import tokens
from ..widgets import Badge, Banner, EmptyState, set_class

REFERENCE_NOTE = "AI 분류 기반 참고용"
EMPTY_TITLE = "아직 기록이 없어요"
EMPTY_BODY = "문제를 제출하거나 AI 코치에서 평가·힌트를 받으면 쌓여요."
MIN_TAGGED = growth.THRESH["min_tagged"]


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
    m = tokens.SPACE * 2
    lay.setContentsMargins(m, tokens.SPACE * 3 // 2, m, tokens.SPACE * 3 // 2)
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
        self._build()

    # --- UI ------------------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("page")
        self.scroll.setWidget(inner)
        outer.addWidget(self.scroll)
        root = QVBoxLayout(inner)
        m = tokens.SPACE * 3
        root.setContentsMargins(m, m, m, m)
        root.setSpacing(tokens.SPACE * 2)
        title = QLabel("성장")
        set_class(title, "title")
        root.addWidget(title)
        self.banner = Banner()  # 0~1개: 꺼짐 안내 / 코멘트 동의
        root.addWidget(self.banner)

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
        self.empty = EmptyState(EMPTY_TITLE, EMPTY_BODY)
        self.empty.setObjectName("GrowthEmpty")
        self.off_state = EmptyState("성장 기록이 꺼져 있어요", "설정에서 켜면 AI 코치 응답과 제출 결과로 주간 리포트가 쌓여요", "설정으로 이동")
        self.off_state.setObjectName("GrowthOff")
        self.off_state.button.clicked.connect(lambda: self.goto_requested.emit("settings"))
        for w in (self.content, self.empty, self.off_state):
            self.stack.addWidget(w)
        root.addWidget(holder, 1)
        self.banner.action_clicked.connect(self._banner_action)

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
            box.setSpacing(2)
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
        self.comment_btn = QPushButton("코멘트 받기")
        self.comment_btn.setObjectName("GrowthCommentButton")
        self.comment_cancel_btn = QPushButton("취소")
        self.comment_cancel_btn.setObjectName("GrowthCommentCancel")
        self.comment_settings_btn = QPushButton("설정으로 이동")
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
        self.metric_box = QVBoxLayout()
        self.metric_box.setSpacing(0)
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
            self.comment_state = "off"
            self.stack.setCurrentWidget(self.off_state)
            self._set_banner("off")
            self.banner.show_message("info", "성장 기록이 꺼져 있어요", "설정에서 켜면 주간 리포트가 다시 쌓여요", [("settings", "설정으로 이동")])
            return
        if self._banner_kind == "off":
            self._set_banner("")
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
        for lab, box, items in ((self.good_label, self.good_box, good), (self.watch_label, self.watch_box, watch), (self.persist_label, self.persist_box, persist)):
            lab.setVisible(bool(items))
            for j in items:
                box.addWidget(_label("· " + j.text, "muted"))
        self.confirm_note.setVisible(rep.in_progress)

    def _fill_metrics(self, rep: growth.GrowthReport) -> None:
        values = [0.0 if st is None else float(st.solved) for st in rep.chart_stats]
        self.chart.set_data(values, [week_label(d) for d in rep.chart_weeks], len(values) - 1)
        _clear(self.metric_box)
        for row in growth.metric_rows(rep):
            self.metric_box.addWidget(MetricRowWidget(row))

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
                box.addWidget(CategoryRowWidget(row))

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
