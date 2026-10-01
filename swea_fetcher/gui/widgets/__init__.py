"""공용 위젯 — design/design-spec.md §5 의 컴포넌트를 Qt 로. 색·간격은 tokens 만 참조한다.

셀렉터 계약(theme/tokens.build_qss): objectName(#nav #log #diff #busy #page) + 동적 속성 class / state.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
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

from ...opener import OpenResult, editor_tooltip, open_folder, open_in_editor  # noqa: F401 — 재노출 (M13)
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
    p = tokens.current()
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


# --- Button (§16.5) -------------------------------------------------------------------


class Button(QPushButton):
    """면·포커스 링을 직접 그리는 버튼. 글자·패딩·크기는 QSS(class 속성), 색은 현재 테마 팔레트에서 읽는다.

    class → 면: primary(주색 면) / tonal(연한 주색) / danger(투명, hover 시 연한 빨강) / link(투명) / 기본(회색 secondary).
    배너 안 버튼은 흰 면. 키보드 포커스일 때만 2px 링 (마우스 클릭 포커스에는 그리지 않는다).
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._busy = False
        self._kb_focus = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    # busy: 작업 중에는 비활성으로 보이고 눌러도 반응하지 않는다 (스피너는 M21-C)
    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.setEnabled(not self._busy)
        self.update()

    def is_busy(self) -> bool:
        return self._busy

    def _on_banner(self) -> bool:
        w = self.parent()
        while w is not None:
            if w.property("class") == "banner":
                return True
            w = w.parent()
        return False

    def face_color(self) -> QColor | None:
        """현재 상태(class·hover·pressed·disabled)의 면 색. 면이 없으면(투명) None. 테스트·캡처에서도 쓴다."""
        p = tokens.current()
        cls = str(self.property("class") or "")
        enabled, down, hover = self.isEnabled(), self.isDown(), self.underMouse()
        if self._on_banner():
            if not enabled:
                return QColor(p.bg_subtle)
            return QColor(p.secondary if down else p.bg_subtle if hover else p.surface)
        if cls == "primary":
            if not enabled:
                return QColor(p.border)
            return QColor(p.primary_pressed if down else p.primary_hover if hover else p.primary_action)
        if cls == "tonal":
            if not enabled:
                return QColor(p.bg_subtle)
            return QColor(p.primary_soft_pressed if down else p.primary_soft_hover if hover else p.primary_soft)
        if cls == "danger":
            if not enabled:
                return None
            return QColor(p.danger_pressed if down else p.error_bg) if (down or hover) else None
        if cls == "link":
            if not enabled:
                return None
            return QColor(p.secondary_hover if down else p.secondary) if (down or hover) else None
        if not enabled:
            return QColor(p.bg_subtle)
        return QColor(p.secondary_pressed if down else p.secondary_hover if hover else p.secondary)

    def paintEvent(self, e) -> None:  # noqa: N802
        face = self.face_color()
        ring = self._kb_focus and self.isEnabled()
        if face is not None or ring:
            p = tokens.current()
            cls = str(self.property("class") or "")
            radius = tokens.RADIUS_SM if cls in ("sm", "link") or self._on_banner() else tokens.RADIUS_MD
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = QRectF(self.rect())
            inset = (3.0 if r.height() >= tokens.CONTROL_H_SM else 2.0) if ring else 0.0
            if face is not None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(face)
                painter.drawRoundedRect(r.adjusted(inset, inset, -inset, -inset), radius, radius)
            if ring:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(p.primary), 2))
                painter.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius + 1, radius + 1)
            painter.end()
        super().paintEvent(e)  # 글자·아이콘 (QSS 배경은 투명)

    def focusInEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = e.reason() in (
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason,
        )
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = False
        super().focusOutEvent(e)
        self.update()


# --- Toggle (§16.5) -------------------------------------------------------------------


class Toggle(QCheckBox):
    """즉시 저장되는 켜기/끄기 스위치 (QCheckBox 서브클래스 — isChecked/setChecked/toggled/objectName 그대로).

    왼쪽 글자 + 오른쪽 44×26 스위치. 행 전체가 클릭 영역이다.
    """

    TRACK_W, TRACK_H, KNOB, GAP = 44, 26, 20, 12

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._kb_focus = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        text_w = self.fontMetrics().horizontalAdvance(self.text()) if self.text() else 0
        return QSize(text_w + (self.GAP if text_w else 0) + self.TRACK_W + 4, max(self.fontMetrics().height() + 12, 36))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.TRACK_W + 4 + 80, 36)

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def track_rect(self) -> QRectF:
        h = self.height()
        return QRectF(self.width() - self.TRACK_W - 2, (h - self.TRACK_H) / 2, self.TRACK_W, self.TRACK_H)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = tokens.current()
        enabled = self.isEnabled()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self.track_rect()
        # 글자
        painter.setPen(QColor(p.text if enabled else p.text_disabled))
        avail = max(int(track.left()) - self.GAP, 10)
        elided = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, avail)
        painter.drawText(QRectF(0, 0, avail, self.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided)
        # 트랙·손잡이
        on = self.isChecked()
        painter.setOpacity(1.0 if enabled else 0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.primary if on else p.toggle_off))
        painter.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)
        pad = (self.TRACK_H - self.KNOB) / 2
        kx = track.right() - pad - self.KNOB if on else track.left() + pad
        painter.setBrush(QColor(p.surface))
        painter.drawEllipse(QRectF(kx, track.top() + pad, self.KNOB, self.KNOB))
        painter.setOpacity(1.0)
        if self._kb_focus and enabled:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.primary), 2))
            painter.drawRoundedRect(track.adjusted(-1, -1, 1, 1), (self.TRACK_H + 2) / 2, (self.TRACK_H + 2) / 2)
        painter.end()

    def focusInEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = e.reason() in (
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason,
        )
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = False
        super().focusOutEvent(e)
        self.update()

    def nextCheckState(self) -> None:  # noqa: N802
        super().nextCheckState()
        self.update()


# --- ThemeChip (설정 > 화면) ------------------------------------------------------------


class ThemeChip(QAbstractButton):
    """테마 선택 칩: 그 테마의 색 원 + 이름. 칩 자체의 색은 해당 테마 팔레트로 고정 (미리보기), 선택 링만 현재 테마를 따른다."""

    W, H = 150, 44

    def __init__(self, key: str, label: str, palette: tokens.Palette, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self._pal = palette
        self.setText(label)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedSize(self.W, self.H)
        self.setObjectName(f"ThemeChip_{key}")
        self.setAccessibleName(f"테마: {label}")
        self._kb_focus = False

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.W, self.H)

    def paintEvent(self, e) -> None:  # noqa: N802
        cur = tokens.current()
        pal = self._pal
        on = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(cur.primary), 2) if on else Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal.primary_soft if on else (cur.secondary_hover if self.underMouse() else cur.secondary)))
        painter.drawRoundedRect(r, tokens.RADIUS_MD, tokens.RADIUS_MD)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal.primary_action))  # 버튼 면 색 = 앱에서 가장 많이 보이는 주색
        cy = self.height() / 2
        painter.drawEllipse(QPointF(26, cy), 10, 10)
        painter.setPen(QColor(cur.text))
        f = self.font()
        f.setBold(on)
        painter.setFont(f)
        painter.drawText(QRectF(46, 0, self.width() - 54, self.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        if self._kb_focus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(cur.primary), 2))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), tokens.RADIUS_MD, tokens.RADIUS_MD)
        painter.end()

    def focusInEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = e.reason() in (
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason,
        )
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = False
        super().focusOutEvent(e)
        self.update()


# --- Toast (§16.5) --------------------------------------------------------------------


class Toast(QWidget):
    """끝난 일의 확인 알림 (하단 중앙, 한 번에 1개). 오류·선택 필요·결과에는 쓰지 않는다 (배너/카드).

    부모(중앙 위젯) 위에 떠 있고 리사이즈 때 다시 배치한다. 클릭하면 닫히고 포커스를 가져가지 않는다.
    그림자는 paintEvent 로 3겹 (QGraphicsDropShadowEffect 금지 — 글자가 흐려진다).
    """

    MAX_W = 480
    MARGIN = 24  # 그림자가 번질 여백
    BOTTOM = 24  # 중앙 위젯 하단에서 띄우는 거리
    PAD_X, PAD_Y = 20, 14

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._text = ""
        self._kind = "success"
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        parent.installEventFilter(self)
        self.hide()

    def message(self) -> str:
        return self._text

    def kind(self) -> str:
        return self._kind

    def show_message(self, text: str, kind: str = "success", ms: int = 2400) -> None:
        """새 메시지는 기존 것을 즉시 교체한다. ms 뒤 자동으로 사라진다."""
        self._text, self._kind = text, kind
        self.setAccessibleName(text)
        self._relayout()
        self.show()
        self.raise_()
        self._timer.start(max(ms, 500))

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()

    def _icon_w(self) -> int:
        return 24 if self._kind == "success" else 0

    def _relayout(self) -> None:
        fm = self.fontMetrics()
        text_w = min(fm.horizontalAdvance(self._text), self.MAX_W - 2 * self.PAD_X - self._icon_w())
        w = text_w + 2 * self.PAD_X + self._icon_w() + 2 * self.MARGIN
        h = fm.height() + 2 * self.PAD_Y + 2 * self.MARGIN
        self.resize(w, h)
        self._reposition()

    def _reposition(self) -> None:
        par = self.parentWidget()
        if par is None:
            return
        x = (par.width() - self.width()) // 2
        y = par.height() - self.height() + self.MARGIN - self.BOTTOM
        self.move(max(x, 0), max(y, 0))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self._reposition()
        return super().eventFilter(obj, event)

    def pill_rect(self) -> QRectF:
        m = self.MARGIN
        return QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = tokens.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pill = self.pill_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        for grow, alpha in ((18, 4), (10, 6), (4, 9)):  # 바깥 → 안쪽, 겹칠수록 진해짐 (스펙 §16.4 의 3겹 근사)
            c = QColor(0, 0, 0, alpha)
            painter.setBrush(c)
            r = pill.adjusted(-grow, -grow + 6, grow, grow + 6)
            painter.drawRoundedRect(r, tokens.RADIUS + grow, tokens.RADIUS + grow)
        painter.setBrush(QColor(p.toast_bg))
        painter.drawRoundedRect(pill, tokens.RADIUS, tokens.RADIUS)
        painter.setPen(QColor(p.toast_text))
        x = pill.left() + self.PAD_X
        if self._kind == "success":  # 흰 체크 글리프 (색 단독이 아니라 글자와 함께)
            painter.setPen(QPen(QColor(p.toast_text), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            cy = pill.center().y()
            painter.drawPolyline([QPointF(x, cy), QPointF(x + 5, cy + 5), QPointF(x + 14, cy - 5)])
            painter.setPen(QColor(p.toast_text))
            x += self._icon_w()
        text_w = pill.right() - self.PAD_X - x
        elided = self.fontMetrics().elidedText(self._text, Qt.TextElideMode.ElideRight, int(text_w))
        painter.drawText(QRectF(x, pill.top(), text_w, pill.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided)
        painter.end()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if self.pill_rect().contains(e.position()):
            self.dismiss()
            e.accept()
        else:
            e.ignore()


# --- PageColumn (§16.4 간격) ----------------------------------------------------------


class PageColumn(QWidget):
    """페이지 본문을 최대 폭(840)으로 제한하고 가운데 정렬하는 컨테이너. 내용은 `body`(QVBoxLayout)에 넣는다.

    폭이 800 미만이면 좌우 여백을 32 → 24 로 줄인다 (resizeEvent).
    """

    MAX_W = 840
    NARROW_W = 800
    MARGIN = 32
    MARGIN_NARROW = 24
    BOTTOM = 24

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        self.column = QWidget()
        self.column.setObjectName("page")
        self.column.setMaximumWidth(self.MAX_W + 2 * self.MARGIN)
        self.column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(self.column, 100)
        outer.addStretch(1)
        self.body = QVBoxLayout(self.column)
        self._apply_margins(self.MARGIN)

    def _apply_margins(self, m: int) -> None:
        self.body.setContentsMargins(m, m, m, self.BOTTOM)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._apply_margins(self.MARGIN_NARROW if self.width() < self.NARROW_W else self.MARGIN)


# --- Banner (§5.6) ------------------------------------------------------------------


class Banner(QFrame):
    """상태 아이콘 + 제목 + 본문 + 조치 버튼(최대 2) + 닫기. 페이지당 1개, 새 배너가 이전 것을 대체."""

    action_clicked = Signal(str)  # 버튼 key

    _ICONS = {"error": "status-error", "warning": "status-warning", "success": "status-success"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        set_class(self, "banner", "info")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
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

    def show_message(
        self, state: str, title: str, body: str = "", actions: list[tuple[str, str]] | None = None, max_actions: int = 2
    ) -> None:
        """actions: [(key, label), ...] 기본 최대 2개 (스펙 §8, "이미 저장된 문제" 만 3개). 클릭 시 action_clicked(key)."""
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
        for key, label in (actions or [])[:max_actions]:
            b = Button(label)
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


class _IconCircle(QWidget):
    """64px 원형 배경(primary_soft) + 28px 아이콘(primary_soft_text 로 재착색). 색은 그릴 때 현재 테마에서 읽는다."""

    def __init__(self, icon_name: str, parent=None) -> None:
        super().__init__(parent)
        self._icon = icon_name
        self.setFixedSize(64, 64)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = tokens.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.primary_soft))
        painter.drawEllipse(self.rect())
        pm = svg_icon(self._icon, p.primary_soft_text, 28).pixmap(28, 28)
        painter.drawPixmap(18, 18, pm)
        painter.end()


class EmptyState(QWidget):
    def __init__(self, title: str, body: str = "", button: str | None = None, parent=None, icon: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        self.icon: _IconCircle | None = None
        if icon:
            self.icon = _IconCircle(icon)
            lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignCenter)
            lay.addSpacing(tokens.SPACE * 2)
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
        self.button: Button | None = None
        if button:
            self.button = Button(button)
            set_class(self.button, "primary")
            lay.addSpacing(tokens.SPACE * 3)
            lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addStretch(1)


# --- LogView (§5.8) -------------------------------------------------------------------


class LogView(QWidget):
    """접기 가능한 로그. 한 줄 형식 `HH:MM:SS  메시지`. traceback 은 danger_text 로."""

    def __init__(self, qsettings=None, key: str = "log/expanded", parent=None) -> None:
        super().__init__(parent)
        self.qs, self.key = qsettings, key
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()  # 로그 전체를 카드로 (스펙 §16.5): 머리글 행 + 회색 필드
        set_class(card, "card")
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        lay.setSpacing(tokens.SPACE)
        head = QHBoxLayout()
        self.toggle = QToolButton()
        self.toggle.setObjectName("LogToggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.toggled.connect(self._toggled)
        head.addWidget(self.toggle)
        head.addStretch(1)
        self.clear_btn = Button("지우기")
        set_class(self.clear_btn, "link")
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
            self.text.appendHtml(f"<span style='color:{tokens.current().error_text}'>{ts}  {_esc(msg)}</span>")
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
            painter.fillRect(r.left(), r.top(), 2, r.height(), QColor(tokens.current().primary))


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
        p = tokens.current()
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
    """폴더 열기 (Windows: 탐색기, 가상 데스크톱 전환 없이). 실패는 False."""
    return open_folder(path)


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
