"""최근 페이지 (스펙 §6.3·§17.12): {topic}/{num}/ 를 수정 시각순으로. 문제별 상태 칩·왼쪽 띠·복습 태그(M22).
더블클릭/Enter → 검증, 우클릭 → 메뉴."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedLayout,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ... import service
from ...config import Settings
from ..theme import tokens
from ..theme.bus import bus
from ..widgets import AppMenu, Banner, Button, EmptyState, open_in_editor, open_in_explorer, editor_tooltip, set_class, svg_icon

LIMIT = 20
REVIEW_MAX_ROWS = 5  # 복습 카드에 보여줄 최대 항목 (나머지는 "외 N개")
COL_STATUS, COL_NUM, COL_TITLE, COL_TOPIC, COL_TIME = range(5)
COL_W_STATUS, COL_W_NUM, COL_W_TOPIC, COL_W_TIME, TITLE_MIN_W = 128, 84, 112, 124, 140  # 번호 84: 스펙 72 는 항목 좌우 패딩 16×2 를 빼면 5자리 번호가 잘린다
TOPIC_HIDE_BELOW = 640  # 표 폭이 이보다 좁으면 주제 열 숨김 (툴팁에는 포함)
ROLE_STATUS = Qt.ItemDataRole.UserRole + 1  # 첫 열 아이템: 상태 key (service.STATUS_ORDER) — 없으면 칩을 그리지 않는다
ROLE_REVIEW = Qt.ItemDataRole.UserRole + 2  # 첫 열 아이템: 복습 태그 (글자, 톤)

# 상태 → (아이콘, 칩 면, 칩 글자·아이콘, 왼쪽 띠) 팔레트 필드 이름 (스펙 §17.12 표). 색은 그릴 때 tokens.current() 에서 읽는다
_STATUS_LOOK = {
    "pass": ("status-pass", "success_bg", "success_text", "success"),
    "wrong": ("status-wrong", "error_bg", "error_text", "error"),
    "timeout": ("status-timeout", "warning_bg", "warning_text", "warning"),
    "runtime_error": ("status-runtime", "error_bg", "error_text", "error"),
    "none": ("status-none", "surface_alt", "text_2", None),
}


class StatusDelegate(QStyledItemDelegate):
    """첫 열: 왼쪽 3px 띠 + 상태 칩(아이콘+글자), 제목 열: 오른쪽 끝 복습 태그를 직접 그린다 (셀에 위젯을 넣지 않음).
    행 hover·선택 배경은 QSS(::item)가 그리고 칩 색은 그대로 둔다."""

    BAND_X, BAND_W, CHIP_X, CHIP_H, TAG_H = 8, 3, 18, 22, 20

    @staticmethod
    def _font(base: QFont) -> QFont:
        f = QFont(base)
        f.setPointSizeF(float(tokens.FONT_SIZE_XS))
        f.setBold(True)
        return f

    def _tag_width(self, option, text: str) -> int:
        fm = QFontMetrics(self._font(option.font))
        return 6 + 12 + 4 + fm.horizontalAdvance(text) + 8

    @staticmethod
    def _review_tag(index):
        return index.model().index(index.row(), COL_STATUS).data(ROLE_REVIEW)

    def paint(self, painter, option, index) -> None:  # noqa: N802
        col = index.column()
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        tag = self._review_tag(index) if col == COL_TITLE else None
        title = opt.text
        if col == COL_STATUS or tag:
            opt.text = ""  # 상태 칸의 글자는 칩으로 대신 그린다 (아이템 텍스트는 접근성용). 태그가 있는 제목은 아래에서 직접 말줄임
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        if col == COL_STATUS:
            key = index.data(ROLE_STATUS)
            if key in _STATUS_LOOK:
                self._paint_chip(painter, option.rect, key)
        elif tag:
            fg = index.data(Qt.ItemDataRole.ForegroundRole)
            painter.save()
            painter.setFont(option.font)
            painter.setPen(fg.color() if hasattr(fg, "color") else QColor(tokens.current().text))
            room = option.rect.width() - 16 - (self._tag_width(option, tag[0]) + 8 + 8)  # 왼쪽 패딩 16, 오른쪽은 태그 폭 + 간격 8 만큼 비운다
            elided = QFontMetrics(option.font).elidedText(title, Qt.TextElideMode.ElideRight, max(room, 20))
            painter.drawText(QRectF(option.rect.left() + 16, option.rect.top(), max(room, 20), option.rect.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided)
            painter.restore()
            self._paint_tag(painter, option, tag)

    def _paint_chip(self, painter: QPainter, rect, key: str) -> None:
        p = tokens.current()
        icon, bg, fg, band = _STATUS_LOOK[key]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if band:
            painter.setBrush(QColor(getattr(p, band)))
            painter.drawRoundedRect(QRectF(rect.left() + self.BAND_X, rect.top() + 8, self.BAND_W, rect.height() - 16), 1.5, 1.5)
        label = service.STATUS_LABELS[key]
        font = self._font(painter.font())
        fm = QFontMetrics(font)
        w = 6 + 14 + 4 + fm.horizontalAdvance(label) + 8
        chip = QRectF(rect.left() + self.CHIP_X, rect.center().y() - self.CHIP_H / 2, w, self.CHIP_H)
        painter.setBrush(QColor(getattr(p, bg)))
        painter.drawRoundedRect(chip, self.CHIP_H / 2, self.CHIP_H / 2)
        color = getattr(p, fg)
        painter.drawPixmap(int(chip.left() + 6), int(chip.center().y() - 7), svg_icon(icon, color, 14).pixmap(14, 14))
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(QRectF(chip.left() + 6 + 14 + 4, chip.top(), w, chip.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
        painter.restore()

    def _paint_tag(self, painter: QPainter, option, tag) -> None:
        p = tokens.current()
        text, tone = tag
        bg, fg = (p.warning_bg, p.warning_text) if tone == "due" else (p.surface_alt, p.text_2)
        rect = option.rect
        w = self._tag_width(option, text)
        r = QRectF(rect.right() - 8 - w, rect.center().y() - self.TAG_H / 2, w, self.TAG_H)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(r, self.TAG_H / 2, self.TAG_H / 2)
        painter.drawPixmap(int(r.left() + 6), int(r.center().y() - 6), svg_icon("review", fg, 12).pixmap(12, 12))
        painter.setFont(self._font(painter.font()))
        painter.setPen(QColor(fg))
        painter.drawText(QRectF(r.left() + 6 + 12 + 4, r.top(), w, r.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        painter.restore()


class HistoryPage(QWidget):
    check_requested = Signal(str, int)  # topic, num
    push_requested = Signal(str, int)  # topic, num — 검증 페이지의 확인 다이얼로그로 (M7)
    submit_requested = Signal(str, int)  # topic, num — 검증 페이지의 [SWEA 제출] 흐름으로 (M8)
    problem_requested = Signal(str, int)  # topic, num — 앱 캐시의 지문을 문제 탭으로 (M12)
    goto_requested = Signal(str)
    status_message = Signal(str)
    reviews_changed = Signal()  # 복습 항목을 [✕] 로 지움 — 메인이 상태바 배지를 갱신 (M17)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.settings: Settings | None = None
        self._items: list[service.RecentItem] = []
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        m = tokens.SPACE * 3
        root.setContentsMargins(m, m, m, m)
        root.setSpacing(tokens.SPACE * 2)
        head = QHBoxLayout()
        head.setSpacing(tokens.BTN_GAP)
        title = QLabel("최근 저장")
        set_class(title, "title")
        self.count_label = QLabel(f"최근 {LIMIT}개")
        set_class(self.count_label, "hint")
        self.count_label.hide()
        self.refresh_btn = Button("새로고침")
        set_class(self.refresh_btn, "tonal")  # 바닥 위 버튼 (스펙 §16.5)
        self.refresh_btn.setToolTip("F5")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.count_label)
        head.addWidget(self.refresh_btn)
        root.addLayout(head)
        self.banner = Banner()
        root.addWidget(self.banner)
        hint = QLabel("클릭 = 문제 보기 · 우클릭 = 에디터·폴더 열기·검증")
        set_class(hint, "hint")
        root.addWidget(hint)

        # 복습 카드 (M17): 항목이 있을 때만. 최근 20개 표와 별개로 조회한다 (표에 없는 문제도 보이게)
        self.review_card = QFrame()
        set_class(self.review_card, "card")
        self.review_card.setObjectName("ReviewCard")
        self._review_lay = QVBoxLayout(self.review_card)
        self._review_lay.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 3 // 2, tokens.SPACE * 2, tokens.SPACE * 3 // 2)
        self._review_lay.setSpacing(tokens.SPACE // 2)
        self.review_card.hide()
        root.addWidget(self.review_card)

        holder = QWidget()
        self.stack = QStackedLayout(holder)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["상태", "번호", "제목", "주제", "저장 시각"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        hh.setMinimumSectionSize(40)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)  # S1
        self.table.horizontalHeaderItem(COL_NUM).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setColumnWidth(COL_STATUS, COL_W_STATUS)
        self.table.setColumnWidth(COL_NUM, COL_W_NUM)
        self.table.setColumnWidth(COL_TOPIC, COL_W_TOPIC)
        self.table.setColumnWidth(COL_TIME, COL_W_TIME)
        self._delegate = StatusDelegate(self.table)
        self.table.setItemDelegateForColumn(COL_STATUS, self._delegate)
        self.table.setItemDelegateForColumn(COL_TITLE, self._delegate)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(tokens.CONTROL_H_SM)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.empty = EmptyState("아직 저장한 문제가 없어요", "저장 페이지에서 문제 번호와 주제를 입력하면 여기에 쌓입니다", "저장 페이지로", icon="nav-history")
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addWidget(holder, 1)

        self.refresh_btn.clicked.connect(self.refresh)
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=self.refresh)
        self.table.cellClicked.connect(self._clicked)
        self.table.cellActivated.connect(self._clicked)  # Enter
        self.table.customContextMenuRequested.connect(self._context_menu)
        bus().changed.connect(self.refresh_theme)
        if self.empty.button:
            self.empty.button.clicked.connect(lambda: self.goto_requested.emit("fetch"))

    def set_settings(self, settings: Settings | None) -> None:
        self.settings = settings
        self.refresh()

    def refresh_theme(self) -> None:
        """델리게이트가 매번 토큰을 읽으므로 표는 다시 그리기만 하면 된다. 복습 카드의 아이콘은 다시 만든다."""
        self.table.viewport().update()
        self._refresh_reviews()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._apply_topic_visibility()

    def _apply_topic_visibility(self) -> None:
        """표 폭이 640 미만이면 주제 열을 숨긴다 (툴팁에 주제 포함)."""
        narrow = self.table.width() < TOPIC_HIDE_BELOW
        if self.table.isColumnHidden(COL_TOPIC) != narrow:
            self.table.setColumnHidden(COL_TOPIC, narrow)

    def refresh(self) -> None:
        """디스크 stat 20개 — 스펙 §6.3 에 따라 UI 스레드 허용."""
        self._refresh_reviews()
        if self.settings is None:
            self._fill([])
            return
        try:
            items = service.list_recent(self.settings.root, limit=LIMIT)
        except OSError as e:
            self.banner.show_message("error", f"루트 폴더를 읽을 수 없습니다: {self.settings.root}", str(e), [("settings", "설정으로 이동")])
            self._fill([])
            return
        self.banner.hide()
        self._fill(items)

    def _refresh_reviews(self) -> None:
        """복습 예약 카드 (제목 + 항목 최대 5개 + 행 끝 [✕]). 상태는 색만이 아니라 글자로도 구분 (도래: 오늘 복습/N일 지남, 예정: N일 뒤)."""
        while self._review_lay.count():
            w = self._review_lay.takeAt(0).widget()
            if w is not None:
                w.hide()  # deleteLater 는 이벤트 루프가 돌아야 지워지므로 그 전에 잔상이 보이지 않게 먼저 숨긴다
                w.deleteLater()
        items = service.review_items(self.settings) if self.settings is not None else []
        if not items:
            self.review_card.hide()
            return
        title = QLabel("복습")
        set_class(title, "section")
        self._review_lay.addWidget(title)
        p = tokens.current()
        for it in items[:REVIEW_MAX_ROWS]:
            row = QHBoxLayout()
            row.setSpacing(tokens.BTN_GAP_SM)
            btn = Button(f"{it.num}. {it.title or '—'}")
            set_class(btn, "link")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip("검증 탭에서 이 문제를 엽니다")
            btn.clicked.connect(lambda _=False, i=it: self.check_requested.emit(i.topic, i.num))
            if it.overdue_days > 0:
                status = f"{it.overdue_days}일 지남"
            elif it.overdue_days == 0:
                status = "오늘 복습"
            else:
                status = f"{-it.overdue_days}일 뒤"
            lab = QLabel(f"· {status}")
            set_class(lab, "review-status", "due" if it.overdue_days >= 0 else "upcoming")  # 색은 QSS 클래스 (스펙 §17.12)
            close = QToolButton()
            close.setIcon(svg_icon("close", p.text_3, 14))  # ✕ 글리프는 Pretendard 에 없어 SVG
            close.setIconSize(QSize(14, 14))
            close.setToolTip("복습 목록에서 지웁니다")
            close.setAccessibleName(f"{it.num}번 복습 지우기")
            close.clicked.connect(lambda _=False, i=it: self._dismiss_review(i.num))
            row.addWidget(btn)
            row.addWidget(lab)
            row.addStretch(1)
            row.addWidget(close)
            holder = QWidget()
            holder.setLayout(row)
            self._review_lay.addWidget(holder)
        if len(items) > REVIEW_MAX_ROWS:
            more = QLabel(f"외 {len(items) - REVIEW_MAX_ROWS}개")
            set_class(more, "hint")
            self._review_lay.addWidget(more)
        self.review_card.show()

    def _dismiss_review(self, num: int) -> None:
        if self.settings is None:
            return
        service.dismiss_review(self.settings, num)
        self._refresh_reviews()
        self.reviews_changed.emit()

    def _fill(self, items: list[service.RecentItem]) -> None:
        self._items = list(items)
        self.table.setRowCount(len(items))
        p = tokens.current()
        stats = service.problem_statuses(self.settings, [it.num for it in items]) if (items and self.settings is not None) else {}
        counts: dict[str, int] = {}
        for i, it in enumerate(items):
            st = stats.get(it.num)
            vals = (st.label if st else "", str(it.num), it.title or "—", it.topic, it.saved_at.strftime("%m-%d %H:%M"))
            for col, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if col == COL_NUM:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == COL_TITLE and it.title is None:
                    cell.setForeground(QColor(p.text_3))
                tip = str(it.path)
                if col == COL_STATUS and st is not None:
                    cell.setData(ROLE_STATUS, st.key)
                    cell.setData(ROLE_REVIEW, st.review_tag)
                    tip = self._status_tooltip(it, st)
                    cell.setData(Qt.ItemDataRole.AccessibleDescriptionRole, self._status_description(it, st))
                elif col == COL_TITLE:
                    tip = f"{it.topic} · {it.path}"  # 주제 열이 숨겨져도 툴팁에서 볼 수 있다
                cell.setToolTip(tip)
                self.table.setItem(i, col, cell)
            if st is not None:
                counts[st.key] = counts.get(st.key, 0) + 1
        self.stack.setCurrentIndex(0 if items else 1)
        if stats:  # 상태 요약 (Pass 12 · 오답 3 …, 0 인 것 생략). 20개 미만이어도 표시
            self.count_label.setText(" · ".join(f"{service.STATUS_LABELS[k]} {counts[k]}" for k in service.STATUS_ORDER if counts.get(k)))
            self.count_label.setVisible(bool(counts))
        else:
            self.count_label.setText(f"최근 {LIMIT}개")
            self.count_label.setVisible(len(items) >= LIMIT)
        self._apply_topic_visibility()

    @staticmethod
    def _status_tooltip(it: service.RecentItem, st: service.ProblemStatus) -> str:
        """"1226번 · Pass(SWEA) · 마지막 제출 09-30 14:44 · 복습 2일 뒤" (Pass 는 SWEA/로컬 구분, 미제출은 안내 문구)."""
        d = ""
        if st.key == "pass" and st.detail != "Pass":
            d = st.detail.replace(" Pass", "")
        elif st.key == "none":
            d = st.detail
        parts = [f"{it.num}번", f"{st.label}({d})" if d else st.label]
        if st.last_submit:
            parts.append(f"마지막 제출 {st.last_submit}")
        if st.review_tag:
            parts.append(st.review_tag[0])
        parts.append(f"주제 {it.topic}")
        return " · ".join(parts)

    @staticmethod
    def _status_description(it: service.RecentItem, st: service.ProblemStatus) -> str:
        tail = f", {st.review_tag[0]}" if st.review_tag else ""
        return f"{it.num}번 문제, {st.label}{tail}"

    def _clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._items):
            it = self._items[row]
            self.problem_requested.emit(it.topic, it.num)

    def _open_editor(self, problem_dir, py, editor: str) -> None:
        res = open_in_editor(problem_dir, py, editor)
        if res.ok and res.note:
            self.status_message.emit(res.note)

    def _context_menu(self, pos: QPoint) -> None:
        row = self.table.rowAt(pos.y())
        if not (0 <= row < len(self._items)):
            return
        it = self._items[row]
        menu = AppMenu(self)
        menu.addAction("폴더 열기", lambda: open_in_explorer(it.path) and self.status_message.emit("폴더를 열었습니다"))
        editor = self.settings.editor if self.settings else "auto"
        open_act = menu.addAction("에디터에서 열기", lambda: self._open_editor(it.path, it.path / f"{it.num}.py", editor))
        open_act.setToolTip(editor_tooltip(editor))
        menu.addAction("문제 보기", lambda: self.problem_requested.emit(it.topic, it.num))  # 캐시에 없으면 지문만 새로 가져온다
        menu.addAction("검증하기", lambda: self.check_requested.emit(it.topic, it.num))
        menu.addAction("SWEA 제출…", lambda: self.submit_requested.emit(it.topic, it.num))
        menu.addAction("커밋 + 푸시…", lambda: self.push_requested.emit(it.topic, it.num))
        menu.exec(self.table.viewport().mapToGlobal(pos))
