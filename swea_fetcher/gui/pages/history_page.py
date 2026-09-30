"""최근 페이지 (스펙 §6.3): {topic}/{num}/ 를 수정 시각순으로. 더블클릭/Enter → 검증, 우클릭 → 메뉴."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ... import service
from ...config import Settings
from ..theme import tokens
from ..widgets import Banner, EmptyState, open_in_editor, open_in_explorer, editor_tooltip, set_class

LIMIT = 20
REVIEW_MAX_ROWS = 5  # 복습 카드에 보여줄 최대 항목 (나머지는 "외 N개")


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
        title = QLabel("최근 저장")
        set_class(title, "title")
        self.count_label = QLabel(f"최근 {LIMIT}개")
        set_class(self.count_label, "hint")
        self.count_label.hide()
        self.refresh_btn = QPushButton("새로고침")
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
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["번호", "제목", "주제", "저장 시각"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)  # S1
        self.table.horizontalHeaderItem(0).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 140)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(tokens.CONTROL_H_SM)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.empty = EmptyState("아직 저장한 문제가 없어요", "저장 페이지에서 문제 번호와 주제를 입력하면 여기에 쌓입니다", "저장 페이지로")
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addWidget(holder, 1)

        self.refresh_btn.clicked.connect(self.refresh)
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=self.refresh)
        self.table.cellClicked.connect(self._clicked)
        self.table.cellActivated.connect(self._clicked)  # Enter
        self.table.customContextMenuRequested.connect(self._context_menu)
        if self.empty.button:
            self.empty.button.clicked.connect(lambda: self.goto_requested.emit("fetch"))

    def set_settings(self, settings: Settings | None) -> None:
        self.settings = settings
        self.refresh()

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
                w.deleteLater()
        items = service.review_items(self.settings) if self.settings is not None else []
        if not items:
            self.review_card.hide()
            return
        title = QLabel("복습")
        set_class(title, "section")
        self._review_lay.addWidget(title)
        p = tokens.LIGHT
        for it in items[:REVIEW_MAX_ROWS]:
            row = QHBoxLayout()
            btn = QPushButton(f"{it.num}. {it.title or '—'}")
            set_class(btn, "link")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip("검증 탭에서 이 문제를 엽니다")
            btn.clicked.connect(lambda _=False, i=it: self.check_requested.emit(i.topic, i.num))
            if it.overdue_days > 0:
                status, color = f"{it.overdue_days}일 지남", p.warning_text
            elif it.overdue_days == 0:
                status, color = "오늘 복습", p.warning_text
            else:
                status, color = f"{-it.overdue_days}일 뒤", p.text_3
            lab = QLabel(f"· {status}")
            lab.setStyleSheet(f"color: {color};")
            close = QToolButton()
            close.setText("✕")
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
        p = tokens.LIGHT
        for i, it in enumerate(items):
            vals = (str(it.num), it.title or "—", it.topic, it.saved_at.strftime("%m-%d %H:%M"))
            for col, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if col == 0:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 1 and it.title is None:
                    cell.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(p.text_3))
                cell.setToolTip(str(it.path))
                self.table.setItem(i, col, cell)
        self.stack.setCurrentIndex(0 if items else 1)
        self.count_label.setVisible(len(items) >= LIMIT)

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
        menu = QMenu(self)
        menu.addAction("폴더 열기", lambda: open_in_explorer(it.path) and self.status_message.emit("폴더를 열었습니다"))
        editor = self.settings.editor if self.settings else "auto"
        open_act = menu.addAction("에디터에서 열기", lambda: self._open_editor(it.path, it.path / f"{it.num}.py", editor))
        open_act.setToolTip(editor_tooltip(editor))
        menu.addAction("문제 보기", lambda: self.problem_requested.emit(it.topic, it.num))  # 캐시에 없으면 지문만 새로 가져온다
        menu.addAction("검증하기", lambda: self.check_requested.emit(it.topic, it.num))
        menu.addAction("SWEA 제출…", lambda: self.submit_requested.emit(it.topic, it.num))
        menu.addAction("커밋 + 푸시…", lambda: self.push_requested.emit(it.topic, it.num))
        menu.exec(self.table.viewport().mapToGlobal(pos))
