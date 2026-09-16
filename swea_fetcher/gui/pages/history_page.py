"""최근 페이지 (스펙 §6.3): {topic}/{num}/ 를 수정 시각순으로. 더블클릭/Enter → 검증, 우클릭 → 메뉴."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import service
from ...config import Settings
from ..theme import tokens
from ..widgets import Banner, EmptyState, open_in_explorer, open_with_default_app, set_class

LIMIT = 20


class HistoryPage(QWidget):
    check_requested = Signal(str, int)  # topic, num
    goto_requested = Signal(str)
    status_message = Signal(str)

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
        hint = QLabel("더블클릭 = 검증 · 우클릭 = 폴더 열기")
        set_class(hint, "hint")
        root.addWidget(hint)

        holder = QWidget()
        self.stack = QStackedLayout(holder)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["번호", "제목", "주제", "저장 시각"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
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
        self.table.cellDoubleClicked.connect(self._double_clicked)
        self.table.cellActivated.connect(self._double_clicked)  # Enter
        self.table.customContextMenuRequested.connect(self._context_menu)
        if self.empty.button:
            self.empty.button.clicked.connect(lambda: self.goto_requested.emit("fetch"))

    def set_settings(self, settings: Settings | None) -> None:
        self.settings = settings
        self.refresh()

    def refresh(self) -> None:
        """디스크 stat 20개 — 스펙 §6.3 에 따라 UI 스레드 허용."""
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

    def _double_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._items):
            it = self._items[row]
            self.check_requested.emit(it.topic, it.num)

    def _context_menu(self, pos: QPoint) -> None:
        row = self.table.rowAt(pos.y())
        if not (0 <= row < len(self._items)):
            return
        it = self._items[row]
        menu = QMenu(self)
        menu.addAction("폴더 열기", lambda: open_in_explorer(it.path) and self.status_message.emit("폴더를 열었습니다"))
        menu.addAction("PyCharm 에서 열기", lambda: open_with_default_app(it.path / f"{it.num}.py"))
        menu.addAction("검증하기", lambda: self.check_requested.emit(it.topic, it.num))
        menu.exec(self.table.viewport().mapToGlobal(pos))
