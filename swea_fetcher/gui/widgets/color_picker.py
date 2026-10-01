"""풀이 잔디 색 선택 (스펙 §17.10·§17.11): 인라인 색 패널 ColorPicker(SV 사각형 + 색상 슬라이더 + HEX) 와 설정 카드의 색 칩.

시스템 색 대화상자를 쓰지 않는다 — 별도 창 없이 설정 카드 안에서 한국어로 펼쳐지고 다크 팔레트를 따른다.
모든 위젯은 paintEvent 에서 tokens.current() 로 색을 읽는다 (SV·Hue 그라디언트는 색 자체라 모드와 무관).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QConicalGradient, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from ... import solved
from ..theme import tokens
from ..theme.bus import bus


def parse_hex_input(text: str | None) -> str | None:
    """HEX 입력 → 6자리 HEX 문자열(대문자, # 포함) 또는 None. '#' 자동 보충, 3자리는 6자리로 확장, 대소문자 무시."""
    t = (text or "").strip().lstrip("#").strip()
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6:
        return None
    try:
        int(t, 16)
    except ValueError:
        return None
    return "#" + t.upper()


def _hsv_of(hex_color: str) -> tuple[float, float, float]:
    c = QColor(hex_color)
    h, s, v, _a = c.getHsvF()
    return (0.0 if h < 0 else h), s, v


def _hex_of_hsv(h: float, s: float, v: float) -> str:
    return QColor.fromHsvF(max(0.0, min(h, 0.9999)), max(0.0, min(s, 1.0)), max(0.0, min(v, 1.0))).name().upper()


# --- 작은 그림 위젯 ----------------------------------------------------------------------


class Swatch(QWidget):
    """범례 칸·미리보기 점: 색 하나를 둥근 사각형(또는 원)으로 그린다."""

    def __init__(self, size: int = 11, radius: float = 2.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color: str | None = None
        self._radius = radius
        self.setFixedSize(size, size)

    def set_color(self, color: str | None) -> None:
        self._color = color
        self.update()

    def color(self) -> str | None:
        return self._color

    def paintEvent(self, e) -> None:  # noqa: N802
        if not self._color:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._color))
        painter.drawRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        painter.end()


def _draw_check(painter: QPainter, cx: float, cy: float, color: str, size: float = 14.0) -> None:
    """체크 표시(선 2px, 둥근 끝). 색 단독으로 선택을 알리지 않도록 칩 위에 항상 같이 그린다."""
    k = size / 14.0
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(color), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPolyline([QPointF(cx - 5 * k, cy), QPointF(cx - 1.5 * k, cy + 3.5 * k), QPointF(cx + 5 * k, cy - 3.5 * k)])


class ColorChip(QAbstractButton):
    """원형 색 칩(32px). 선택 시 2px text 링 + 중앙 on_primary 체크. kind="custom" 이고 색이 없으면 그라디언트 링(직접 고르기) 아이콘."""

    SIZE = 32

    def __init__(self, hex_color: str | None, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hex = hex_color
        self._label = name
        self._shown = hex_color  # 현재 모드 보정 후 색 (표시 전용)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._kb_focus = False
        self.toggled.connect(lambda _on: self._sync_name())
        self._sync_name()

    @property
    def hex(self) -> str | None:
        return self._hex

    def set_color(self, hex_color: str | None, shown: str | None = None) -> None:
        """저장 hex(툴팁·접근성)와 표시색(모드 보정 후)을 따로 받는다."""
        self._hex = hex_color
        self._shown = shown or hex_color
        self._sync_name()
        self.update()

    def set_label(self, name: str) -> None:
        self._label = name
        self._sync_name()

    def _sync_name(self) -> None:
        self.setAccessibleName(f"풀이 잔디 색: {self._label}{', 선택됨' if self.isChecked() else ''}")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.SIZE, self.SIZE)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = tokens.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        on = self.isChecked()
        painter.setPen(Qt.PenStyle.NoPen)
        if self._shown:
            painter.setBrush(QColor(self._shown))
            painter.drawEllipse(r)
        else:  # 직접 고르기: 색상환 그라디언트 링
            grad = QConicalGradient(r.center(), 90)
            for i in range(7):
                grad.setColorAt(i / 6, QColor.fromHsvF(((i % 6) / 6) % 1.0, 0.85, 0.95))
            painter.setBrush(grad)
            painter.drawEllipse(r)
            painter.setBrush(QColor(p.surface))
            painter.drawEllipse(r.adjusted(5, 5, -5, -5))
        if on:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.text), 2))
            painter.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
            if self._shown:
                _draw_check(painter, self.width() / 2, self.height() / 2, p.on_primary)
        elif self.underMouse():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.border_strong), 2))
            painter.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        if self._kb_focus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.primary), 2))
            painter.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        painter.end()

    def focusInEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = False
        super().focusOutEvent(e)
        self.update()


class FollowChip(QAbstractButton):
    """"테마 색 따르기" 알약 칩(높이 36): 현재 primary 점 16px + 글자. 선택 시 primary_soft 면 + 2px primary 링 + 체크."""

    H = 36
    LABEL = "테마 색 따르기"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(self.LABEL)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(self.H)
        self.setObjectName("HeatFollow")
        self._kb_focus = False
        self.toggled.connect(lambda _on: self._sync_name())
        self._sync_name()

    def _sync_name(self) -> None:
        self.setAccessibleName(f"풀이 잔디 색: {self.LABEL}{', 선택됨' if self.isChecked() else ''}")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(14 + 16 + 8 + self.fontMetrics().horizontalAdvance(self.LABEL) + 12 + 14 + 8, self.H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = tokens.current()
        on = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(p.primary), 2) if on else Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.primary_soft if on else (p.secondary_hover if self.underMouse() else p.secondary)))
        painter.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.primary))
        painter.drawEllipse(QRectF(14, (self.height() - 16) / 2, 16, 16))
        painter.setPen(QColor(p.primary_soft_text if on else p.text))
        font = self.font()
        font.setBold(on)
        painter.setFont(font)
        tw = self.fontMetrics().horizontalAdvance(self.LABEL) + 4
        painter.drawText(QRectF(38, 0, tw, self.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.LABEL)
        if on:
            _draw_check(painter, 38 + tw + 12, self.height() / 2, p.primary_soft_text, 12.0)
        if self._kb_focus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.primary), 2))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), self.height() / 2, self.height() / 2)
        painter.end()

    def focusInEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = False
        super().focusOutEvent(e)
        self.update()


# --- SV 사각형 · 색상 슬라이더 -------------------------------------------------------------


def _handle(painter: QPainter, c: QPointF, fill: str | None, d: float = 14.0) -> None:
    """이중 링 손잡이: ring_light 2px 바깥 + ring_dark 1px 안쪽선 (임의 색 위라 흑백 고정)."""
    p = tokens.current()
    r = d / 2
    painter.setBrush(QColor(fill) if fill else Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(p.ring_dark), 1))
    painter.drawEllipse(c, r + 1.5, r + 1.5)
    painter.setPen(QPen(QColor(p.ring_light), 2))
    painter.drawEllipse(c, r, r)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(p.ring_dark), 1))
    painter.drawEllipse(c, r - 1.5, r - 1.5)


class SVArea(QWidget):
    """가로 = 채도 0→100%, 세로 = 명도 100→0%. 키보드 ←→ 채도, ↑↓ 명도 (Shift 10%)."""

    changed = Signal(float, float)  # 이동 중 (s, v)
    released = Signal()  # 마우스 놓음
    key_moved = Signal()  # 키보드 이동(연속 입력 — 호출자가 디바운스)

    HEIGHT = 144

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ColorSV")
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("채도·명도 영역")
        self.hue, self.s, self.v = 0.0, 0.8, 0.8
        self._cache: tuple | None = None  # ((w, h, hue), QImage)
        self._kb_focus = False

    def set_hsv(self, h: float, s: float, v: float) -> None:
        self.hue, self.s, self.v = h, max(0.0, min(1.0, s)), max(0.0, min(1.0, v))
        self.update()

    def _image(self) -> QImage:
        key = (self.width(), self.height(), round(self.hue, 4))
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1]
        w, h = max(self.width(), 1), max(self.height(), 1)
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        qp = QPainter(img)
        horiz = QLinearGradient(0, 0, w, 0)  # 왼쪽 흰색(채도 0) → 오른쪽 순색
        horiz.setColorAt(0.0, QColor.fromHsvF(self.hue, 0.0, 1.0))
        horiz.setColorAt(1.0, QColor.fromHsvF(self.hue, 1.0, 1.0))
        qp.fillRect(0, 0, w, h, horiz)
        vert = QLinearGradient(0, 0, 0, h)  # 위 투명 → 아래 검정(명도 0)
        vert.setColorAt(0.0, QColor.fromHsvF(self.hue, 1.0, 0.0, 0.0))
        vert.setColorAt(1.0, QColor.fromHsvF(self.hue, 1.0, 0.0, 1.0))
        qp.fillRect(0, 0, w, h, vert)
        qp.end()
        self._cache = (key, img)
        return img

    def paintEvent(self, e) -> None:  # noqa: N802
        p = tokens.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        painter.setClipPath(path)
        painter.drawImage(0, 0, self._image())
        painter.setClipping(False)
        c = QPointF(self.s * (self.width() - 1), (1.0 - self.v) * (self.height() - 1))
        _handle(painter, c, _hex_of_hsv(self.hue, self.s, self.v))
        if self._kb_focus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.primary), 2))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(-1, -1, 1, 1), 9, 9)
        painter.end()

    def _from_pos(self, pos) -> None:
        w, h = max(self.width() - 1, 1), max(self.height() - 1, 1)
        self.s = max(0.0, min(1.0, pos.x() / w))
        self.v = max(0.0, min(1.0, 1.0 - pos.y() / h))
        self.update()
        self.changed.emit(self.s, self.v)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._from_pos(e.position())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._from_pos(e.position())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.released.emit()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        step = 0.10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.01
        ds = dv = 0.0
        k = e.key()
        if k == Qt.Key.Key_Left:
            ds = -step
        elif k == Qt.Key.Key_Right:
            ds = step
        elif k == Qt.Key.Key_Up:
            dv = step
        elif k == Qt.Key.Key_Down:
            dv = -step
        else:
            super().keyPressEvent(e)
            return
        self.s = max(0.0, min(1.0, self.s + ds))
        self.v = max(0.0, min(1.0, self.v + dv))
        self.update()
        self.changed.emit(self.s, self.v)
        self.key_moved.emit()

    def focusInEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = False
        super().focusOutEvent(e)
        self.update()


class HueSlider(QWidget):
    """색상환 무지개 트랙(높이 16) + 지름 20 손잡이. ←→ ±1°(Shift 10°)."""

    changed = Signal(float)  # 0..1 (hue / 360)
    released = Signal()
    key_moved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ColorHue")
        self.setFixedHeight(20)
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("색상 슬라이더 0~360")
        self.hue = 0.0  # 0..1
        self._kb_focus = False

    def set_hue(self, h: float) -> None:
        self.hue = max(0.0, min(0.9999, h))
        self.update()

    def degrees(self) -> int:
        return int(round(self.hue * 360)) % 360

    def _track(self) -> QRectF:
        return QRectF(10, 2, max(self.width() - 20, 1), 16)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = tokens.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tr = self._track()
        grad = QLinearGradient(tr.left(), 0, tr.right(), 0)
        for i in range(7):
            grad.setColorAt(i / 6, QColor.fromHsvF((i % 6) / 6 if i < 6 else 0.9999, 1.0, 1.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawRoundedRect(tr, 8, 8)
        cx = tr.left() + self.hue * tr.width()
        _handle(painter, QPointF(cx, self.height() / 2), QColor.fromHsvF(self.hue, 1.0, 1.0).name(), 16.0)
        if self._kb_focus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.primary), 2))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        painter.end()

    def _from_pos(self, pos) -> None:
        tr = self._track()
        self.hue = max(0.0, min(0.9999, (pos.x() - tr.left()) / tr.width()))
        self.update()
        self.changed.emit(self.hue)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._from_pos(e.position())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._from_pos(e.position())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.released.emit()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        step = (10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1) / 360.0
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self.hue = (self.hue - step) % 1.0
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self.hue = (self.hue + step) % 1.0
        else:
            super().keyPressEvent(e)
            return
        self.update()
        self.changed.emit(self.hue)
        self.key_moved.emit()

    def focusInEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._kb_focus = False
        super().focusOutEvent(e)
        self.update()


# --- 색 선택 패널 ------------------------------------------------------------------------------


class _Dot(QWidget):
    """미리보기 원(28px)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color: str | None = None
        self.setFixedSize(28, 28)

    def set_color(self, c: str) -> None:
        self._color = c
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        if not self._color:
            return
        p = tokens.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(p.border_strong), 1))
        painter.setBrush(QColor(self._color))
        painter.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        painter.end()


class ColorPicker(QFrame):
    """설정 카드 안에서 펼쳐지는 색 선택 패널 (tile 면, 내용 최대 폭 320 왼쪽 정렬). 확인/취소 없이 즉시 적용.

    - 이동 중에는 패널 안 미리보기만 갱신(color_changed). 놓을 때·HEX Enter/포커스 아웃·키보드 이동 150ms 뒤에 color_committed(hex).
    - HEX: '#' 자동 보충, 3자리 확장, 대소문자 무시. 잘못된 값은 적용하지 않고 오류 문구.
    - reset_requested: "테마 색 따르기로 되돌리기", close_requested: 닫기.
    """

    color_changed = Signal(str)
    color_committed = Signal(str)
    reset_requested = Signal()
    close_requested = Signal()

    DEBOUNCE_MS = 150
    ERROR_TEXT = f"색 코드는 #과 영문·숫자 6자리예요 (예: {solved.DEFAULT_HEAT_COLOR})"
    MAX_BODY_W = 320

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ColorPicker")
        self.setProperty("class", "tile")
        self._color = solved.DEFAULT_HEAT_COLOR
        self._last_committed = self._color
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        body = QWidget()
        body.setMaximumWidth(self.MAX_BODY_W)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(body, 100)
        outer.addStretch(1)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("색 직접 고르기")
        title.setProperty("class", "section")
        head.addWidget(title, 1)
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("ColorPickerClose")
        self.close_btn.setToolTip("색 선택 닫기")
        self.close_btn.setAccessibleName("색 선택 닫기")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setIconSize(QSize(16, 16))
        self.close_btn.clicked.connect(self.close_requested.emit)
        head.addWidget(self.close_btn)
        lay.addLayout(head)

        self.sv = SVArea()
        self.hue = HueSlider()
        lay.addWidget(self.sv)
        lay.addWidget(self.hue)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.dot = _Dot()
        row.addWidget(self.dot)
        self.hex_edit = QLineEdit()
        self.hex_edit.setObjectName("ColorHex")
        self.hex_edit.setProperty("class", "mono")
        self.hex_edit.setProperty("size", "md")
        self.hex_edit.setFixedWidth(120)
        self.hex_edit.setMaxLength(8)
        self.hex_edit.setAccessibleName("HEX 색 코드")
        self.hex_edit.setPlaceholderText(solved.DEFAULT_HEAT_COLOR)
        row.addWidget(self.hex_edit)
        self.applied = QLabel("")
        self.applied.setProperty("class", "hint")
        row.addWidget(self.applied)
        row.addStretch(1)
        lay.addLayout(row)
        self.error = QLabel(self.ERROR_TEXT)
        self.error.setObjectName("ColorHexError")
        self.error.setProperty("class", "error")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)

        prev = QHBoxLayout()
        prev.setSpacing(4)
        lo = QLabel("적게")
        lo.setProperty("class", "hint")
        prev.addWidget(lo)
        self.levels = [Swatch(14, 3) for _ in range(5)]
        for sw in self.levels:
            prev.addWidget(sw)
        hi = QLabel("많이")
        hi.setProperty("class", "hint")
        prev.addWidget(hi)
        prev.addStretch(1)
        lay.addLayout(prev)

        foot = QHBoxLayout()
        foot.addStretch(1)
        from . import Button  # 지연 import — widgets/__init__ 가 이 모듈을 마지막에 import 한다

        self.reset_btn = Button("테마 색 따르기로 되돌리기")
        self.reset_btn.setObjectName("ColorPickerReset")
        self.reset_btn.setProperty("class", "link")
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        foot.addWidget(self.reset_btn)
        lay.addLayout(foot)

        # 연결
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.DEBOUNCE_MS)
        self._timer.timeout.connect(self._commit)
        self.sv.changed.connect(self._on_sv)
        self.hue.changed.connect(self._on_hue)
        self.sv.released.connect(self._commit)  # 마우스 release 는 즉시
        self.hue.released.connect(self._commit)
        self.sv.key_moved.connect(self._commit_soon)  # 키보드는 150ms 디바운스
        self.hue.key_moved.connect(self._commit_soon)
        self.hex_edit.returnPressed.connect(self._on_hex_return)  # Enter: 같은 색이어도 적용(되돌아가기 포함)
        self.hex_edit.editingFinished.connect(self._on_hex_enter)  # 포커스 아웃: 바뀐 경우만
        self.hex_edit.textEdited.connect(self._on_hex_edited)
        bus().changed.connect(self.refresh_theme)
        self.set_color(self._color)
        self.refresh_theme()

    # --- 값 ---
    def color(self) -> str:
        return self._color

    def set_color(self, hex_color: str, emit: bool = False) -> None:
        """표시만 바꾼다(SV·Hue·HEX·미리보기 동기화). emit=True 면 color_changed·committed 도 보낸다."""
        c = parse_hex_input(hex_color) or self._color
        self._color = c
        h, s, v = _hsv_of(c)
        if s > 0 and v > 0:  # 무채색·검정이면 기존 hue 유지 (슬라이더가 0 으로 튀지 않게)
            self.hue.set_hue(h)
        self.sv.set_hsv(self.hue.hue, s, v)
        self.dot.set_color(c)
        if not self.hex_edit.hasFocus() or emit:
            self.hex_edit.setText(c)
        self._show_error(False)
        if not emit:
            self._last_committed = c
            self.applied.setText("")
        if emit:
            self.color_changed.emit(c)
            self.color_committed.emit(c)

    def set_levels(self, colors: list[str]) -> None:
        for sw, c in zip(self.levels, colors):
            sw.set_color(c)

    def refresh_theme(self) -> None:
        from . import svg_icon

        self.close_btn.setIcon(svg_icon("close", tokens.current().text_2, 16))
        self.update()

    # --- 내부 ---
    def _show_error(self, on: bool) -> None:
        self.error.setVisible(on)
        self.hex_edit.setProperty("state", "invalid" if on else "")
        self.hex_edit.style().unpolish(self.hex_edit)
        self.hex_edit.style().polish(self.hex_edit)

    def _live(self) -> None:
        c = _hex_of_hsv(self.hue.hue, self.sv.s, self.sv.v)
        self._color = c
        self.dot.set_color(c)
        self.hex_edit.setText(c)
        self.applied.setText("")
        self._show_error(False)
        self.color_changed.emit(c)

    def _on_sv(self, _s: float, _v: float) -> None:
        self._live()

    def _on_hue(self, h: float) -> None:
        self.sv.set_hsv(h, self.sv.s, self.sv.v)
        self._live()

    def _on_hex_edited(self, _text: str) -> None:
        self._show_error(False)

    def _on_hex_return(self) -> None:
        self._on_hex_enter(force=True)

    def _on_hex_enter(self, force: bool = False) -> None:
        text = self.hex_edit.text()
        c = parse_hex_input(text)
        if c is None:
            if text.strip():
                self._show_error(True)
            return
        changed = force or c != self._last_committed
        self.set_color(c)
        self.hex_edit.setText(c)
        if changed:
            self._commit()

    def _commit_soon(self) -> None:
        self._timer.start()

    def _commit(self) -> None:
        self._timer.stop()
        self._last_committed = self._color
        self.applied.setText("적용됨")
        self.color_committed.emit(self._color)

    def commit_now(self) -> None:
        """대기 중인 디바운스를 즉시 확정 (테스트용)."""
        if self._timer.isActive():
            self._commit()
