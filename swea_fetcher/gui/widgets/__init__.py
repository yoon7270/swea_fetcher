"""공용 위젯 — design/design-spec.md §5 의 컴포넌트를 Qt 로. 색·간격은 tokens 만 참조한다.

셀렉터 계약(theme/tokens.build_qss): objectName(#nav #log #diff #busy #page) + 동적 속성 class / state.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QStyledItemDelegate,
    QStyle,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import tokens

ICON_DIR = Path(__file__).resolve().parent.parent / "theme" / "icons"
ICON_BASE_COLOR = "#424A53"  # 디자이너 SVG 의 스트로크 색 (= text_2). 재착색은 이 문자열 치환으로


# --- 스타일 도우미 -----------------------------------------------------------------


def set_class(w: QWidget, cls: str, state: str | None = None) -> None:
    """QSS 선택자용 동적 속성. 바꾼 뒤 스타일을 다시 적용한다 (스펙 §13)."""
    w.setProperty("class", cls)
    if state is not None:
        w.setProperty("state", state)
    w.style().unpolish(w)
    w.style().polish(w)


def set_state(w: QWidget, state: str) -> None:
    w.setProperty("state", state)
    w.style().unpolish(w)
    w.style().polish(w)


def set_invalid(w: QWidget, invalid: bool) -> None:
    """입력 검증 실패 표시 (QLineEdit[state="invalid"])."""
    set_state(w, "invalid" if invalid else "")


def svg_icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    """theme/icons/{name}.svg → QIcon. color 를 주면 기본 스트로크 색을 치환해 재착색한다."""
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        return QIcon()
    data = path.read_text(encoding="utf-8")
    if color:
        data = data.replace(ICON_BASE_COLOR, color)
    renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return QIcon(pm)


def nav_icon(name: str) -> QIcon:
    """내비 아이콘: 기본 text_2, 선택(On) 시 primary_soft_text, 비활성은 text_disabled (스펙 §12)."""
    p = tokens.LIGHT
    icon = svg_icon(name, None)
    on = svg_icon(name, p.primary_soft_text)
    dis = svg_icon(name, p.text_disabled)
    icon.addPixmap(on.pixmap(20, 20), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(on.pixmap(20, 20), QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(on.pixmap(20, 20), QIcon.Mode.Selected, QIcon.State.On)
    icon.addPixmap(dis.pixmap(20, 20), QIcon.Mode.Disabled, QIcon.State.Off)
    return icon


def make_busy_bar() -> QProgressBar:
    """헤더 아래 얇은 인디터미넛 진행 막대 (QProgressBar#busy). 진행 중에만 visible."""
    bar = QProgressBar()
    bar.setObjectName("busy")
    bar.setRange(0, 0)
    bar.setTextVisible(False)
    bar.setFixedHeight(tokens.PROGRESS_H)
    bar.hide()
    return bar


# --- Banner (§5.6) ------------------------------------------------------------------


class Banner(QFrame):
    """상태 아이콘 + 제목 + 본문 + 조치 버튼(최대 2) + 닫기. 페이지당 1개, 새 배너가 이전 것을 대체."""

    action_clicked = Signal(str)  # 버튼 key

    _ICONS = {"error": "status-error", "warning": "status-warning", "success": "status-success"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        set_class(self, "banner", "info")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(tokens.SPACE // 2)
        head = QHBoxLayout()
        head.setSpacing(tokens.SPACE)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        set_class(self.title, "banner-title")
        self.close_btn = QToolButton()
        self.close_btn.setText("✕")
        self.close_btn.setToolTip("닫기")
        self.close_btn.setAccessibleName("닫기")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.clicked.connect(self.hide)
        head.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        head.addWidget(self.title, 1)
        head.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(head)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        set_class(self.body, "muted")
        outer.addWidget(self.body)
        self.btn_row = QHBoxLayout()
        self.btn_row.addStretch(1)
        self._buttons: list[QPushButton] = []
        outer.addLayout(self.btn_row)
        self.hide()

    def show_message(self, state: str, title: str, body: str = "", actions: list[tuple[str, str]] | None = None) -> None:
        """actions: [(key, label), ...] 최대 2개. 클릭 시 action_clicked(key)."""
        set_class(self, "banner", state)
        set_class(self.title, "banner-title")
        icon_name = self._ICONS.get(state)
        if icon_name:
            self.icon.setPixmap(svg_icon(icon_name, None, 16).pixmap(16, 16))
            self.icon.show()
        else:
            self.icon.hide()
        self.title.setText(title)
        self.body.setText(body)
        self.body.setVisible(bool(body))
        for b in self._buttons:
            self.btn_row.removeWidget(b)
            b.deleteLater()
        self._buttons = []
        for key, label in (actions or [])[:2]:
            b = QPushButton(label)
            set_class(b, "sm")
            b.clicked.connect(lambda _=False, k=key: self.action_clicked.emit(k))
            self.btn_row.addWidget(b)
            self._buttons.append(b)
        self.show()

    @property
    def hint(self) -> QLabel:  # 하위 호환 (테스트에서 hint.text() 로 본문 확인)
        return self.body

    @property
    def action(self) -> QPushButton | None:
        return self._buttons[0] if self._buttons else None


# --- Badge (§5.7) -------------------------------------------------------------------


class Badge(QLabel):
    """pill 상태 배지. state: success | error | warning | running | idle. 항상 텍스트 포함."""

    def __init__(self, text: str = "대기", state: str = "idle", parent=None) -> None:
        super().__init__(text, parent)
        set_class(self, "badge", state)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_state(self, text: str, state: str) -> None:
        self.setText(text)
        set_class(self, "badge", state)
        self.show()


# --- ElidedLabel (§5.10 경로 줄) -------------------------------------------------------


class ElidedLabel(QLabel):
    """가로 정책 Ignored + 가운데 생략. 긴 경로가 가로 스크롤을 만들지 않는다. 툴팁 = 전문."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self.setToolTip(text)
        self._refresh()

    def fullText(self) -> str:  # noqa: N802
        return self._full

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._refresh()

    def _refresh(self) -> None:
        w = max(self.width() - 4, 40)
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, w))


# --- EmptyState (§5.11) ---------------------------------------------------------------


class EmptyState(QWidget):
    def __init__(self, title: str, body: str = "", button: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        t = QLabel(title)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_class(t, "empty-title")
        lay.addWidget(t)
        if body:
            b = QLabel(body)
            b.setAlignment(Qt.AlignmentFlag.AlignCenter)
            b.setWordWrap(True)
            set_class(b, "empty-body")
            lay.addSpacing(tokens.SPACE)
            lay.addWidget(b)
        self.button: QPushButton | None = None
        if button:
            self.button = QPushButton(button)
            lay.addSpacing(tokens.SPACE * 2)
            lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addStretch(1)


# --- LogView (§5.8) -------------------------------------------------------------------


class LogView(QWidget):
    """접기 가능한 로그. 한 줄 형식 `HH:MM:SS  메시지`. traceback 은 danger_text 로."""

    def __init__(self, qsettings=None, key: str = "log/expanded", parent=None) -> None:
        super().__init__(parent)
        self.qs, self.key = qsettings, key
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(tokens.SPACE // 2)
        head = QHBoxLayout()
        self.toggle = QToolButton()
        self.toggle.setObjectName("LogToggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.toggled.connect(self._toggled)
        head.addWidget(self.toggle)
        head.addStretch(1)
        self.clear_btn = QToolButton()
        self.clear_btn.setText("지우기")
        self.clear_btn.clicked.connect(self.clear)
        head.addWidget(self.clear_btn)
        lay.addLayout(head)
        self.text = QPlainTextEdit()
        self.text.setObjectName("log")
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(2000)
        self.text.setPlaceholderText("진행 로그가 여기에 표시됩니다")
        # 창이 작을 때 결과 카드 대신 로그가 줄어들도록 최소 높이는 0, 선호 높이만 LOG_H_DEFAULT
        self.text.setMinimumHeight(tokens.LOG_H_MIN)
        self.text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.text.sizeHint = lambda: QSize(400, tokens.LOG_H_DEFAULT)  # type: ignore[method-assign]
        lay.addWidget(self.text)
        self._n = 0
        if self.qs is not None:
            self.toggle.setChecked(bool(self.qs.value(self.key, True, type=bool)))
        self._toggled(self.toggle.isChecked())

    def _toggled(self, on: bool) -> None:
        self.text.setVisible(on)
        self.toggle.setText("▼ 로그" if on else f"▶ 로그 ({self._n}줄)")
        if self.qs is not None:
            self.qs.setValue(self.key, on)

    def append(self, msg: str, error: bool = False) -> None:
        self._n += 1
        stamp = datetime.now().strftime("%H:%M:%S")
        ts = f"<span style='font-family:{tokens.FONT_MONO}'>{stamp}</span>"
        if error:
            self.text.appendHtml(f"<span style='color:{tokens.LIGHT.error_text}'>{ts}  {_esc(msg)}</span>")
        else:
            self.text.appendHtml(f"{ts}  {_esc(msg)}")
        if not self.toggle.isChecked():
            self.toggle.setText(f"▶ 로그 ({self._n}줄)")

    def clear(self) -> None:
        self.text.clear()
        self._n = 0
        self._toggled(self.toggle.isChecked())


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


# --- DiffView (§5.9) -------------------------------------------------------------------


class _BackgroundDelegate(QStyledItemDelegate):
    """QSS 의 ::item 규칙이 BackgroundRole 을 무시하므로 배경을 직접 칠한다. 선택 강조는 쓰지 않는다."""

    def paint(self, painter, option, index) -> None:  # noqa: N802
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if bg is not None:
            painter.fillRect(option.rect, bg)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        opt = option
        opt.state &= ~QStyle.StateFlag.State_Selected
        opt.backgroundBrush = Qt.BrushStyle.NoBrush
        super().paint(painter, opt, index)
        if selected and index.column() == 0:  # 선택 표시: 행 왼쪽 2px primary 세로선 (diff 색을 덮지 않게, 스펙 §5.9)
            r = option.rect
            painter.fillRect(r.left(), r.top(), 2, r.height(), QColor(tokens.LIGHT.primary))


class DiffView(QTableWidget):
    """행 단위 diff. 열: #(마커) · 기대 · 실제. 배경 + 마커 문자로 종류 구분 (색 단독 금지)."""

    MAX_ROWS = 1000
    _MARK = {"same": "", "changed": "≠", "missing": "−", "extra": "+"}

    def __init__(self, parent=None) -> None:
        super().__init__(0, 3, parent)
        self.setObjectName("diff")
        self.setHorizontalHeaderLabels(["#", "기대 (output.txt)", "실제 (실행 결과)"])
        self.horizontalHeader().setStretchLastSection(True)
        self.setColumnWidth(0, 44)
        self.setColumnWidth(1, 280)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(tokens.CONTROL_H_SM)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)  # 선택·복사 가능 (스펙 §10)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setShowGrid(False)
        self.setItemDelegate(_BackgroundDelegate(self))

    def keyPressEvent(self, e) -> None:  # noqa: N802
        """Ctrl+C = 선택 행의 '실제' 열 텍스트를 줄바꿈으로 이어 클립보드에."""
        if e.matches(QKeySequence.StandardKey.Copy):
            rows = sorted({i.row() for i in self.selectedIndexes()})
            lines = [(self.item(r, 2).text() if self.item(r, 2) else "") for r in rows]
            QApplication.clipboard().setText("\n".join(l for l in lines if l != "—"))
            return
        super().keyPressEvent(e)

    def set_rows(self, rows: list[tuple[str, str | None, str | None]]) -> int:
        """행을 채우고 첫 불일치 행 인덱스(없으면 -1)를 돌려준다. 첫 불일치 행으로 스크롤·선택."""
        p = tokens.LIGHT
        colors = {"same": QColor(p.diff_same), "changed": QColor(p.diff_changed), "missing": QColor(p.diff_missing), "extra": QColor(p.diff_extra)}
        shown = rows[: self.MAX_ROWS]
        self.setRowCount(len(shown) + (1 if len(rows) > self.MAX_ROWS else 0))
        first_bad = -1
        for i, (kind, e, a) in enumerate(shown):
            mark = self._MARK[kind]
            num_txt = f"{i + 1} {mark}".strip()
            exp_txt = e if e is not None else "—"
            act_txt = a if a is not None else "—"
            for col, val in enumerate((num_txt, exp_txt, act_txt)):
                item = QTableWidgetItem(val)
                item.setBackground(colors[kind])
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setForeground(QColor(p.text_3))
                    item.setToolTip(kind)
                elif (col == 1 and e is None) or (col == 2 and a is None):
                    item.setForeground(QColor(p.text_3))
                elif col == 2 and kind == "changed":
                    item.setForeground(QColor(p.warning_text))
                self.setItem(i, col, item)
            if kind != "same" and first_bad < 0:
                first_bad = i
        if len(rows) > self.MAX_ROWS:
            r = len(shown)
            item = QTableWidgetItem(f"…이하 {len(rows) - self.MAX_ROWS}행 생략")
            item.setForeground(QColor(p.text_3))
            self.setItem(r, 1, item)
        if first_bad >= 0:
            self.scrollToItem(self.item(first_bad, 0), QTableWidget.ScrollHint.PositionAtCenter)
        return first_bad


# --- 외부 프로그램 -------------------------------------------------------------------------


def open_in_explorer(path: Path) -> bool:
    """폴더 열기 (Windows: 탐색기). 실패는 False."""
    return _start(path)


def open_with_default_app(path: Path) -> bool:
    """기본 연결 프로그램으로 파일 열기 (.py → PyCharm 등)."""
    return _start(path)


def _start(path: Path) -> bool:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607
        return True
    except OSError:
        return False
