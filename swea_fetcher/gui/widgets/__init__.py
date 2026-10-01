"""공용 위젯 — design/design-spec.md §5 의 컴포넌트를 Qt 로. 색·간격은 tokens 만 참조한다.

셀렉터 계약(theme/tokens.build_qss): objectName(#nav #log #diff #busy #page) + 동적 속성 class / state.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QEasingCurve, QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QGuiApplication, QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QStyledItemDelegate,
    QStyle,
    QHBoxLayout,
    QLabel,
    QMenu,
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
from .. import motion
from ..theme import tokens
from ..theme.bus import bus
from ..theme.tokens import ICON_BASE_COLOR

ICON_DIR = Path(__file__).resolve().parent.parent / "theme" / "icons"
POPUP_TRANSLUCENT = True  # 콤보·메뉴 팝업 창을 투명 창으로 만들어 둥근 모서리 바깥 회색을 없앤다. 환경에 따라 검게 보이면 False (스펙 §17.16 X3)


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


def set_size(w: QWidget, size: str) -> None:
    """동적 속성 size ("lg" = 52px 페이지 CTA). QSS `QPushButton[size="lg"]`. 바꾼 뒤 스타일을 다시 적용한다."""
    w.setProperty("size", size)
    w.style().unpolish(w)
    w.style().polish(w)


def set_invalid(w: QWidget, invalid: bool) -> None:
    """입력 검증 실패 표시 (QLineEdit[state="invalid"])."""
    set_state(w, "invalid" if invalid else "")


_ICON_CACHE: dict[tuple, QIcon] = {}


def _dpr() -> float:
    scr = QGuiApplication.primaryScreen()
    return float(scr.devicePixelRatio()) if scr is not None else 1.0


def svg_icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    """theme/icons/{name}.svg → QIcon. 기본 스트로크 색은 현재 팔레트의 text_2, color 를 주면 그 색으로 재착색한다.

    상태 아이콘의 색은 success·warning·error, 안쪽 흰 글리프는 on_primary 로 치환 (tokens.icon_recolor_pairs).
    결과는 (name, color, size, dpr, tokens.version()) 키로 캐시한다 — 테마·모드가 바뀌면 version 이 달라져 자동 무효화.
    """
    key = (name, color, size, _dpr(), tokens.version())
    hit = _ICON_CACHE.get(key)
    if hit is not None:
        return hit
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        return QIcon()
    pal = tokens.current()
    data = path.read_text(encoding="utf-8")
    data = data.replace(ICON_BASE_COLOR, color or pal.text_2)
    for old, new in tokens.icon_recolor_pairs(pal):
        data = data.replace(old, new)
    renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    icon = QIcon(pm)
    if len(_ICON_CACHE) > 400:  # 테마를 여러 번 바꿔도 무한히 늘지 않게
        _ICON_CACHE.clear()
    _ICON_CACHE[key] = icon
    return icon


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


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    """RGBA 선형 보간 (hover 색 전환용)."""
    t = max(0.0, min(1.0, t))
    return QColor.fromRgb(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class Button(QPushButton):
    """면·포커스 링을 직접 그리는 버튼. 글자·패딩·크기는 QSS(class 속성), 색은 현재 테마 팔레트에서 읽는다.

    class → 면: primary(주색 면) / tonal(연한 주색) / danger(투명, hover 시 연한 빨강) / link(투명) / 기본(회색 secondary).
    배너 안 버튼은 흰 면. 키보드 포커스일 때만 2px 링 (마우스 클릭 포커스에는 그리지 않는다).
    모션(M21-C): hover 면 색 120ms 보간, 눌림 시 면만 0.97 배 축소(80ms) 후 복귀(120ms), busy 시 왼쪽 스피너. 모션이 꺼져 있으면 모두 즉시.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._busy = False
        self._kb_focus = False
        self._hover_t: float | None = None  # None = 보간 중 아님 (underMouse 로 즉시 판정)
        self._press_scale = 1.0
        self._spinner: Spinner | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.pressed.connect(self._on_pressed)
        self.released.connect(self._on_released)

    # busy: 작업 중에는 비활성으로 보이고 눌러도 반응하지 않는다. 왼쪽에 16px 스피너 (스펙 §16.5·A8)
    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.setEnabled(not self._busy)
        if self._busy:
            if self._spinner is None:
                self._spinner = Spinner(self)
                self._spinner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._place_spinner()
            self._spinner.show()
            self._spinner.raise_()
        elif self._spinner is not None:
            self._spinner.hide()
        self.update()

    def is_busy(self) -> bool:
        return self._busy

    def set_trailing_icon(self, name: str, size: int = 14) -> None:
        """글자 오른쪽 아이콘 (↗ 같은 글리프는 Pretendard 에 없어 SVG). 테마가 바뀌면 refresh_icon() 으로 다시 칠한다."""
        self._trail = (name, size)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setIconSize(QSize(size, size))
        self.refresh_icon()

    def refresh_icon(self) -> None:
        trail = self.__dict__.get("_trail")
        if trail:
            self.setIcon(svg_icon(trail[0], tokens.current().primary_soft_text, trail[1]))

    def _place_spinner(self) -> None:
        if self._spinner is None:
            return
        text_w = self.fontMetrics().horizontalAdvance(self.text())
        x = max(int((self.width() - text_w) / 2) - self._spinner.width() - 8, 8)
        self._spinner.move(x, (self.height() - self._spinner.height()) // 2)

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self._place_spinner()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._place_spinner()

    def _on_banner(self) -> bool:
        w = self.parent()
        while w is not None:
            if w.property("class") == "banner":
                return True
            w = w.parent()
        return False

    def _state_color(self, hover: bool, down: bool) -> QColor | None:
        """상태(class·hover·pressed·disabled)별 면 색. 면이 없으면(투명) None."""
        p = tokens.current()
        cls = str(self.property("class") or "")
        enabled = self.isEnabled()
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

    def face_color(self) -> QColor | None:
        """현재 상태의 면 색. 면이 없으면(투명) None. hover 보간 중에는 중간색. 테스트·캡처에서도 쓴다."""
        down = self.isDown()
        if self._hover_t is None or down or not self.isEnabled():
            return self._state_color(self.underMouse(), down)
        rest, hov = self._state_color(False, False), self._state_color(True, False)
        if rest is None and hov is None:
            return None
        if rest is None:  # 투명 → 면: 같은 색의 알파만 보간
            rest = QColor(hov)
            rest.setAlpha(0)
        if hov is None:
            hov = QColor(rest)
            hov.setAlpha(0)
        return _lerp_color(rest, hov, self._hover_t)

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
                sx = r.width() * (1.0 - self._press_scale) / 2  # 눌림: 면만 중심 기준 축소 (글자는 그대로)
                sy = r.height() * (1.0 - self._press_scale) / 2
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(face)
                painter.drawRoundedRect(r.adjusted(inset + sx, inset + sy, -inset - sx, -inset - sy), radius, radius)
            if ring:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(p.primary), 2))
                painter.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius + 1, radius + 1)
            painter.end()
        super().paintEvent(e)  # 글자·아이콘 (QSS 배경은 투명)

    # --- 모션 (A3 hover 색 보간 · A4 눌림 축소) ---
    def _set_hover_t(self, v: float) -> None:
        self._hover_t = v
        self.update()

    def _animate_hover(self, to: float) -> None:
        if not self.isEnabled():
            self._hover_t = None
            self.update()
            return
        cur = self._hover_t if self._hover_t is not None else (1.0 - to)
        anim = motion.tween(self, cur, to, motion.MOTION_FAST, self._set_hover_t, motion.EASE_IN, on_finished=self._end_hover, key="hover")
        if anim is None:
            self._hover_t = None
            self.update()
        else:
            self._set_hover_t(cur)

    def _end_hover(self) -> None:
        self._hover_t = None  # 보간 끝 → underMouse 로 판정 (최종 상태와 같다)
        self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        super().enterEvent(e)
        self._animate_hover(1.0)

    def leaveEvent(self, e) -> None:  # noqa: N802
        super().leaveEvent(e)
        self._animate_hover(0.0)

    def _set_scale(self, v: float) -> None:
        self._press_scale = v
        self.update()

    def _on_pressed(self) -> None:
        anim = motion.tween(self, self._press_scale, motion.PRESS_SCALE, motion.PRESS_DOWN_MS, self._set_scale, QEasingCurve.Type.OutQuad, key="press")
        if anim is None:
            self._press_scale = 1.0

    def _on_released(self) -> None:
        anim = motion.tween(self, self._press_scale, 1.0, motion.PRESS_UP_MS, self._set_scale, QEasingCurve.Type.OutQuad, key="press")
        if anim is None:
            self._press_scale = 1.0
            self.update()

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
        self._t: float | None = None  # 손잡이 위치 0..1 (None = 보간 중 아님 → isChecked 로 판정)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggled.connect(self._on_toggled)

    def _set_t(self, v: float) -> None:
        self._t = v
        self.update()

    def _on_toggled(self, on: bool) -> None:
        """손잡이 이동 + 트랙 색 보간 180ms (A7). 보이지 않거나 모션이 꺼져 있으면 즉시."""
        target = 1.0 if on else 0.0
        cur = self._t if self._t is not None else (1.0 - target)
        anim = motion.tween(self, cur, target, motion.MOTION_TOGGLE, self._set_t, motion.EASE_IN, on_finished=self._end_anim, key="toggle") if self.isVisible() else None
        if anim is None:
            self._t = None
            self.update()
        else:
            self._set_t(cur)

    def _end_anim(self) -> None:
        self._t = None
        self.update()

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
        t = self._t if self._t is not None else (1.0 if self.isChecked() else 0.0)
        painter.setOpacity(1.0 if enabled else 0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_lerp_color(QColor(p.toggle_off), QColor(p.primary), t))
        painter.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)
        pad = (self.TRACK_H - self.KNOB) / 2
        kx = track.left() + pad + (track.width() - 2 * pad - self.KNOB) * t
        painter.setBrush(_lerp_color(QColor(p.toggle_knob), QColor(p.on_primary), t))  # OFF 손잡이 → ON 손잡이 보간
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


# --- StatusDot (상태바 로그인 표시) ------------------------------------------------------------------


class StatusDot(QLabel):
    """왼쪽에 8px 점을 그리는 라벨 (● ○ 글리프 대신). state 속성 "ok" 면 success 채움 점, 그 외 text_3 속 빈 링.
    색 단독 전달이 아니라 항상 옆 글자("로그인됨"/"세션 없음")가 함께 있다. 점 자리는 QSS padding-left 가 확보한다."""

    DOT = 8

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        p = tokens.current()
        ok = self.property("state") == "ok"
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        r = QRectF(1.0, cy - self.DOT / 2, self.DOT, self.DOT)
        if ok:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.success))
        else:
            painter.setPen(QPen(QColor(p.text_3), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = r.adjusted(0.75, 0.75, -0.75, -0.75)
        painter.drawEllipse(r)
        painter.end()


# --- ThemeChip (설정 > 화면) ------------------------------------------------------------


class ThemeChip(QAbstractButton):
    """테마 선택 칩: 그 테마의 색 원 + 이름. 점·선택 면·링은 그 테마의 "현재 모드" 팔레트 색이다 (스펙 §17.9)."""

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
        theme = tokens.get_theme(self.key)
        pal = theme.dark if tokens.is_dark() else theme.light
        on = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(pal.primary), 2) if on else Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal.primary_soft if on else (cur.secondary_hover if self.underMouse() else cur.secondary)))
        painter.drawRoundedRect(r, tokens.RADIUS_MD, tokens.RADIUS_MD)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal.primary_action))  # 버튼 면 색 = 앱에서 가장 많이 보이는 주색
        cy = self.height() / 2
        painter.drawEllipse(QPointF(26, cy), 10, 10)
        painter.setPen(QColor(pal.primary_soft_text if on else cur.text))
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
        self._opacity = 1.0
        self._dy = 0.0
        self._exiting = False
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
        """새 메시지는 기존 것을 즉시 교체한다. ms 뒤 자동으로 사라진다. 등장: 불투명도 0→1 + 아래 12px→0 (200ms, A6)."""
        was_visible = (not self.isHidden()) and not self._exiting
        motion.finish_now(self, "toast")
        self._exiting = False
        self._text, self._kind = text, kind
        self.setAccessibleName(text)
        self._relayout()
        self._opacity, self._dy = 1.0, 0.0
        self.show()
        self.raise_()
        self._timer.start(max(ms, 500))
        if not was_visible:
            self._enter()

    def _set_phase(self, v: float) -> None:
        self._opacity = v
        self._dy = 12.0 * (1.0 - v)
        self.update()

    def _enter(self) -> None:
        anim = motion.tween(self, 0.0, 1.0, motion.MOTION_BASE, self._set_phase, motion.EASE_IN, key="toast")
        if anim is None:
            self._opacity, self._dy = 1.0, 0.0
        else:
            self._set_phase(0.0)

    def dismiss(self) -> None:
        """사라짐: 불투명도 1→0 + 아래 8px (150ms, InCubic). 모션이 꺼져 있으면 즉시 숨김."""
        self._timer.stop()
        if self.isHidden() or self._exiting:
            return
        self._exiting = True

        def _set(v: float) -> None:
            self._opacity = 1.0 - v
            self._dy = 8.0 * v
            self.update()

        def _done() -> None:
            self._exiting = False
            self.hide()

        anim = motion.tween(self, 0.0, 1.0, motion.MOTION_EXIT, _set, motion.EASE_OUT, on_finished=_done, key="toast")
        if anim is None:
            self._exiting = False
            self.hide()

    def _icon_w(self) -> int:
        return 24 if self._kind == "success" else 0

    def _relayout(self) -> None:
        self.ensurePolished()  # QSS 글꼴이 적용되기 전에 재면 실제로 그릴 글자보다 좁게 나와 말줄임된다 ("저장 완료 · 257…")
        fm = self.fontMetrics()
        text_w = min(fm.horizontalAdvance(self._text) + 2, self.MAX_W - 2 * self.PAD_X - self._icon_w())  # +2: 반올림 여유
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
        painter.setOpacity(self._opacity)
        painter.translate(0, self._dy)
        pill = self.pill_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        for grow, alpha in (() if p.is_dark else ((18, 4), (10, 6), (4, 9))):  # 바깥 → 안쪽, 겹칠수록 진해짐 (§16.4). 다크는 그림자 없음 (§17.7)
            c = QColor(0, 0, 0, alpha)  # noqa-color — 중립 그림자(알파만)
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
        self._icon_name: str | None = None
        self.close_btn = QToolButton()
        self.close_btn.setIcon(svg_icon("close", tokens.current().text_2, 16))  # Pretendard 에 ✕ 글리프가 없어 SVG
        self.close_btn.setIconSize(QSize(16, 16))
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
        self.btn_row.setSpacing(tokens.BTN_GAP_SM)
        self.btn_row.addStretch(1)
        self._buttons: list[QPushButton] = []
        outer.addLayout(self.btn_row)
        self.hide()
        bus().changed.connect(self.refresh_theme)

    def refresh_theme(self) -> None:
        """테마·모드가 바뀌면 SVG 아이콘(상태 아이콘·닫기)을 새 팔레트 색으로 다시 칠한다."""
        self.close_btn.setIcon(svg_icon("close", tokens.current().text_2, 16))
        if self._icon_name:
            self.icon.setPixmap(svg_icon(self._icon_name, None, 16).pixmap(16, 16))

    def show_message(
        self, state: str, title: str, body: str = "", actions: list[tuple[str, str]] | None = None, max_actions: int = 2
    ) -> None:
        """actions: [(key, label), ...] 기본 최대 2개 (스펙 §8, "이미 저장된 문제" 만 3개). 클릭 시 action_clicked(key)."""
        set_class(self, "banner", state)
        set_class(self.title, "banner-title")
        icon_name = self._ICONS.get(state)
        self._icon_name = icon_name
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
        was_visible = self.isVisible()
        self.show()
        if not was_visible:
            motion.fade_in(self)  # 등장 페이드 180ms (A5)

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
    """가로 정책 Ignored + 생략. 긴 경로가 가로 스크롤을 만들지 않는다. 툴팁 = 전문.

    mode: 기본은 가운데 생략(경로용). 메타 줄처럼 앞이 중요한 글은 ElideRight.
    set_parts(parts): 부분 목록(예: ["코드 평가", "14:02", "16.2초"])을 " · " 로 잇되, 안 들어가면 가운데 부분부터
    통째로 빼고(시각 생략) 그래도 안 되면 오른쪽 말줄임 — 글자 한가운데가 "…" 로 잘려 읽히지 않는 일이 없게 한다.
    """

    def __init__(self, parent=None, mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle) -> None:
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self._parts: list[str] | None = None
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self._parts = None
        self.setToolTip(text)
        self._refresh()

    def set_parts(self, parts: list[str], sep: str = " · ") -> None:
        self._parts = [p for p in parts if p]
        self._full = sep.join(self._parts)
        self._sep = sep
        self.setToolTip(self._full)
        self._refresh()

    def fullText(self) -> str:  # noqa: N802
        return self._full

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._refresh()

    def _refresh(self) -> None:
        w = max(self.width() - 4, 40)
        fm = self.fontMetrics()
        if self._parts:
            n = len(self._parts)
            sep = getattr(self, "_sep", " · ")
            for drop in range(n):  # drop = 가운데에서 빼는 부분 수 (0 = 전부)
                keep = self._parts[:1] + self._parts[1 + drop :] if drop < n - 1 else self._parts[:1]
                text = sep.join(keep)
                if fm.horizontalAdvance(text) <= w:
                    super().setText(text)
                    return
            super().setText(fm.elidedText(self._parts[0], Qt.TextElideMode.ElideRight, w))
            return
        super().setText(fm.elidedText(self._full, self._mode, w))


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
    """접기 가능한 로그. 한 줄 형식 `HH:MM:SS  메시지`. traceback 은 error_text 로.

    색은 인라인 style 이 아니라 문서 기본 스타일시트의 클래스(.ts·.err)로만 준다 — 테마가 바뀌면 최근 N줄의 원본을 다시 렌더한다 (스펙 §17.7).
    """

    KEEP_LINES = 500  # 테마 전환 때 다시 그릴 원본 줄 수

    def __init__(self, qsettings=None, key: str = "log/expanded", parent=None) -> None:
        super().__init__(parent)
        self.qs, self.key = qsettings, key
        self._lines: list[tuple[str, str, bool]] = []  # (HH:MM:SS, 메시지, error) 최근 KEEP_LINES 줄
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
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setIconSize(QSize(16, 16))
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
        self.text.document().setDefaultStyleSheet(tokens.build_log_css(tokens.current()))
        # 창이 작을 때 결과 카드 대신 로그가 줄어들도록 최소 높이는 0, 선호 높이만 LOG_H_DEFAULT
        self.text.setMinimumHeight(tokens.LOG_H_MIN)
        self.text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.text.sizeHint = lambda: QSize(400, tokens.LOG_H_DEFAULT)  # type: ignore[method-assign]
        lay.addWidget(self.text)
        self._n = 0
        if self.qs is not None:
            self.toggle.setChecked(bool(self.qs.value(self.key, True, type=bool)))
        self._toggled(self.toggle.isChecked())
        bus().changed.connect(self.refresh_theme)

    def _toggled(self, on: bool) -> None:
        self.text.setVisible(on)
        self.toggle.setIcon(svg_icon("caret-down" if on else "caret-right", tokens.current().text_2, 16))  # ▼▶ 글리프 대신 SVG
        self.toggle.setText("로그" if on else f"로그 ({self._n}줄)")
        if self.qs is not None:
            self.qs.setValue(self.key, on)

    @staticmethod
    def _line_html(stamp: str, msg: str, error: bool) -> str:
        ts = f"<span class='ts'>{stamp}</span>"
        return f"<span class='err'>{ts}  {_esc(msg)}</span>" if error else f"{ts}  {_esc(msg)}"

    def append(self, msg: str, error: bool = False) -> None:
        self._n += 1
        stamp = datetime.now().strftime("%H:%M:%S")
        self._lines.append((stamp, msg, error))
        del self._lines[: -self.KEEP_LINES]
        self.text.appendHtml(self._line_html(stamp, msg, error))
        if not self.toggle.isChecked():
            self.toggle.setText(f"로그 ({self._n}줄)")

    def refresh_theme(self) -> None:
        """새 팔레트의 문서 CSS 로 교체하고 보관한 최근 줄을 다시 만든다 (스크롤 위치 유지)."""
        bar = self.text.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 2
        pos = bar.value()
        doc = self.text.document()
        doc.setDefaultStyleSheet(tokens.build_log_css(tokens.current()))
        self.text.clear()
        for stamp, msg, error in self._lines:
            self.text.appendHtml(self._line_html(stamp, msg, error))
        bar.setValue(bar.maximum() if at_end else pos)
        self.toggle.setIcon(svg_icon("caret-down" if self.toggle.isChecked() else "caret-right", tokens.current().text_2, 16))

    def clear(self) -> None:
        self.text.clear()
        self._lines.clear()
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
        self._meta: list[tuple[str, str | None, str | None]] = []
        bus().changed.connect(self.refresh_theme)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        """Ctrl+C = 선택 행의 '실제' 열 텍스트를 줄바꿈으로 이어 클립보드에."""
        if e.matches(QKeySequence.StandardKey.Copy):
            rows = sorted({i.row() for i in self.selectedIndexes()})
            lines = [(self.item(r, 2).text() if self.item(r, 2) else "") for r in rows]
            QApplication.clipboard().setText("\n".join(l for l in lines if l != "—"))
            return
        super().keyPressEvent(e)

    def _style_item(self, item: QTableWidgetItem, col: int, kind: str, e: str | None, a: str | None) -> None:
        """한 셀의 배경·글자색을 현재 팔레트로 칠한다 (set_rows·refresh_theme 공용)."""
        p = tokens.current()
        colors = {"same": p.diff_same, "changed": p.diff_changed, "missing": p.diff_missing, "extra": p.diff_extra}
        item.setBackground(QColor(colors[kind]))
        if col == 0:
            item.setForeground(QColor(p.text_3))
        elif (col == 1 and e is None) or (col == 2 and a is None):
            item.setForeground(QColor(p.text_3))
        elif col == 2 and kind == "changed":
            item.setForeground(QColor(p.warning_text))
        else:
            item.setForeground(QColor(p.text))

    def set_rows(self, rows: list[tuple[str, str | None, str | None]]) -> int:
        """행을 채우고 첫 불일치 행 인덱스(없으면 -1)를 돌려준다. 첫 불일치 행으로 스크롤·선택."""
        p = tokens.current()
        shown = rows[: self.MAX_ROWS]
        self._meta = list(shown)
        self.setRowCount(len(shown) + (1 if len(rows) > self.MAX_ROWS else 0))
        first_bad = -1
        for i, (kind, e, a) in enumerate(shown):
            mark = self._MARK[kind]
            num_txt = f"{i + 1} {mark}".strip()
            exp_txt = e if e is not None else "—"
            act_txt = a if a is not None else "—"
            for col, val in enumerate((num_txt, exp_txt, act_txt)):
                item = QTableWidgetItem(val)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setToolTip(kind)
                self._style_item(item, col, kind, e, a)
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

    def refresh_theme(self) -> None:
        """테마·모드가 바뀌면 기존 행의 배경·글자색을 새 팔레트로 다시 칠한다 (행 데이터·스크롤·선택 유지)."""
        for i, (kind, e, a) in enumerate(getattr(self, "_meta", [])):
            for col in range(3):
                item = self.item(i, col)
                if item is not None:
                    self._style_item(item, col, kind, e, a)
        extra = self.item(len(getattr(self, "_meta", [])), 1) if self.rowCount() > len(getattr(self, "_meta", [])) else None
        if extra is not None:
            extra.setForeground(QColor(tokens.current().text_3))
        self.viewport().update()


# --- Spinner · Skeleton (§16.7 A8·A9) ----------------------------------------------------------------


class _LoopWidget(QWidget):
    """보일 때(+창이 최소화되지 않고 앱이 활성일 때)만 무한 애니메이션을 돌리는 베이스. 모션이 꺼져 있으면 정적 그림.

    유휴 상태에서 타이머가 0개여야 하므로 hideEvent·창 비활성에서 반드시 멈춘다.
    """

    LOOP_MS = 900

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._sync_loop)

    def _set_phase(self, v: float) -> None:
        self._phase = v
        self.update()

    def is_animating(self) -> bool:
        return motion.loop_running(self)

    def _should_run(self) -> bool:
        if not self.isVisible():
            return False
        if motion.forced_on():
            return True
        win = self.window()
        if win is not None and win.isMinimized():
            return False
        return QApplication.applicationState() == Qt.ApplicationState.ApplicationActive

    def _sync_loop(self, *_a) -> None:
        if self._should_run():
            if not motion.loop_running(self):
                if motion.loop(self, self.LOOP_MS, self._set_phase) is None:
                    self._phase = 0.0
        else:
            motion.stop_loop(self)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self._sync_loop()

    def hideEvent(self, e) -> None:  # noqa: N802
        super().hideEvent(e)
        motion.stop_loop(self)


class Spinner(_LoopWidget):
    """16px 회전 호. 선형 900ms/회전. 모션이 꺼져 있으면 3/4 호 정적 그림."""

    LOOP_MS = motion.SPINNER_MS
    SIZE = 16

    def __init__(self, parent=None, color: str | None = None) -> None:
        super().__init__(parent)
        self._color = color  # None = 현재 테마 primary
        self.setFixedSize(self.SIZE, self.SIZE)

    def paintEvent(self, e) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(self._color or tokens.current().primary)
        track = QColor(c)
        track.setAlpha(50)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(track, 2.2))
        painter.drawEllipse(r)
        painter.setPen(QPen(c, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        start = 90 - self._phase * 360  # 12 시에서 시계 방향
        painter.drawArc(r, int(start * 16), int(-270 * 16))
        painter.end()


class Skeleton(_LoopWidget):
    """로딩 자리표시 막대 3줄(100/92/64% 폭, 높이 14, 라운드 7). 하이라이트가 좌→우로 1200ms 선형 반복.
    모션이 꺼져 있으면 기본색 막대만 그린다."""

    LOOP_MS = motion.SKELETON_MS
    BAR_H, GAP = 14, 10
    WIDTHS = (1.0, 0.92, 0.64)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(len(self.WIDTHS) * self.BAR_H + (len(self.WIDTHS) - 1) * self.GAP)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = tokens.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        w = self.width()
        for i, frac in enumerate(self.WIDTHS):
            bar = QRectF(0, i * (self.BAR_H + self.GAP), w * frac, self.BAR_H)
            painter.setBrush(QColor(p.surface_alt))
            painter.drawRoundedRect(bar, self.BAR_H / 2, self.BAR_H / 2)
            if self.is_animating():
                cx = -0.3 * w + self._phase * 1.6 * w  # 하이라이트 중심 (전체 폭 기준, 막대 밖은 클립)
                grad = QLinearGradient(cx - 0.3 * w, 0, cx + 0.3 * w, 0)
                grad.setColorAt(0.0, QColor(p.surface_alt))
                grad.setColorAt(0.5, QColor(p.hover_fill))
                grad.setColorAt(1.0, QColor(p.surface_alt))
                painter.save()
                clip = QPainterPath()
                clip.addRoundedRect(bar, self.BAR_H / 2, self.BAR_H / 2)
                painter.setClipPath(clip)
                painter.setBrush(QBrush(grad))
                painter.drawRect(bar)
                painter.restore()
        painter.end()


# --- NavDelegate (내비 알약 슬라이드, §16.5·A2) ---------------------------------------------


class NavDelegate(QStyledItemDelegate):
    """사이드 내비 항목을 직접 그린다. 선택 알약(primary_soft)은 항목 사이를 200ms 로 미끄러져 이동하고,
    각 항목은 '알약 사각형 ∩ 항목 사각형' 만 칠한다 (이동 중에도 끊기지 않음). 모션이 꺼져 있으면 즉시 현재 항목에.
    키보드(Tab) 포커스일 때만 2px primary 링. 아이콘·글자는 QListWidget 항목 데이터를 그대로 쓴다."""

    PAD_X = 12
    ICON = 20
    ICON_GAP = 10

    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self._anim_y: float | None = None  # 이동 중인 알약의 위쪽 y (viewport 좌표). None = 현재 항목에 정지
        self._prev_row: int | None = None
        view.currentRowChanged.connect(self._on_row_changed)

    def _pill_for(self, row: int) -> QRectF:
        r = QRectF(self._view.visualRect(self._view.model().index(row, 0)))
        gap = tokens.NAV_GAP / 2
        return r.adjusted(0, gap, 0, -gap)

    def pill_rect(self) -> QRectF | None:
        row = self._view.currentRow()
        if row < 0:
            return None
        base = self._pill_for(row)
        if self._anim_y is not None:
            base.moveTop(self._anim_y)
        return base

    def is_animating(self) -> bool:
        return motion.is_running(self, "pill")

    def _set_y(self, y: float) -> None:
        self._anim_y = y
        self._view.viewport().update()

    def _end(self) -> None:
        self._anim_y = None
        self._view.viewport().update()

    def _on_row_changed(self, row: int) -> None:
        prev, self._prev_row = self._prev_row, row
        if row < 0 or prev is None or prev < 0 or not self._view.isVisible():
            self._anim_y = None
            self._view.viewport().update()
            return
        start = self._anim_y if self._anim_y is not None else self._pill_for(prev).top()
        end = self._pill_for(row).top()
        anim = motion.tween(self, start, end, motion.MOTION_BASE, self._set_y, motion.EASE_IN, on_finished=self._end, key="pill")
        if anim is None:
            self._anim_y = None
        self._view.viewport().update()

    def paint(self, painter, option, index) -> None:  # noqa: N802
        p = tokens.current()
        rect = QRectF(option.rect)
        gap = tokens.NAV_GAP / 2
        slot = rect.adjusted(0, gap, 0, -gap)  # 항목 하나의 알약 자리
        selected = index.row() == self._view.currentRow()
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = tokens.RADIUS_MD
        if hover and not selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.secondary))
            painter.drawRoundedRect(slot, radius, radius)
        pill = self.pill_rect()
        if pill is not None and pill.intersects(rect):
            painter.save()
            painter.setClipRect(rect)  # 알약 ∩ 이 항목
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.primary_soft))
            painter.drawRoundedRect(pill, radius, radius)
            painter.restore()
        # 아이콘 + 글자
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            mode = QIcon.Mode.Selected if selected else QIcon.Mode.Normal
            ir = QRectF(slot.left() + self.PAD_X, slot.center().y() - self.ICON / 2, self.ICON, self.ICON)
            icon.paint(painter, ir.toRect(), Qt.AlignmentFlag.AlignCenter, mode, QIcon.State.Off)
        font = painter.font()
        font.setBold(selected)
        painter.setFont(font)
        painter.setPen(QColor(p.primary_soft_text if selected else (p.text if hover else p.text_2)))
        tr = QRectF(slot.left() + self.PAD_X + self.ICON + self.ICON_GAP, slot.top(), slot.width() - self.PAD_X * 2 - self.ICON - self.ICON_GAP, slot.height())
        painter.drawText(tr, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
        if selected and (option.state & QStyle.StateFlag.State_HasFocus):  # 키보드 포커스 링 (§10)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.primary), 2))
            painter.drawRoundedRect(slot.adjusted(1, 1, -1, -1), radius, radius)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        sh = index.data(Qt.ItemDataRole.SizeHintRole)
        return sh if isinstance(sh, QSize) else QSize(0, tokens.NAV_ITEM_H + tokens.NAV_GAP)


# --- 팝업 가장자리 (스펙 §17.8(b)) ----------------------------------------------------------


def style_popup(window: QWidget | None) -> None:
    """팝업 창(콤보 목록 컨테이너·메뉴)을 프레임 없는 투명 창으로 만들어 둥근 모서리 바깥·패딩 틈에 팔레트 회색이 비치지 않게 한다.

    플래그 변경은 창이 처음 보이기 전에만 한다 (이미 보이면 아무 것도 하지 않는다).
    """
    if window is None or window.isVisible():
        return
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    window.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    if POPUP_TRANSLUCENT:
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)


class ComboBox(QComboBox):
    """앱 공용 콤보. 생성 직후 목록 팝업 컨테이너를 style_popup 으로 투명 처리하고 뷰포트의 자동 배경을 끈다."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        view = self.view()
        view.viewport().setAutoFillBackground(False)
        view.setFrameShape(QFrame.Shape.NoFrame)
        style_popup(view.window())


class AppMenu(QMenu):
    """앱 공용 메뉴(우클릭 등). 생성자에서 style_popup 을 적용한다. 색·모양은 QSS 의 QMenu 규칙."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        style_popup(self)


# --- SegmentedControl (스펙 §17.13) ---------------------------------------------------------


class _SegButton(QAbstractButton):
    """세그먼트 한 칸. 면·글자·아이콘을 직접 그린다 (색은 그릴 때 tokens.current())."""

    def __init__(self, key: str, label: str, icon: str, owner: "SegmentedControl") -> None:
        super().__init__(owner)
        self.key = key
        self._icon = icon
        self._owner = owner
        self.setText(label)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 포커스·키보드는 SegmentedControl 이 한 번에 받는다
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setObjectName(f"Segment_{key}")

    def content_width(self, with_icon: bool) -> int:
        bold = QFont(self.font())
        bold.setBold(True)
        w = QFontMetrics(bold).horizontalAdvance(self.text()) + 2 * 14
        return w + (SegmentedControl.ICON + 6 if with_icon else 0)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = tokens.current()
        on = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if on:
            painter.setBrush(QColor(p.segment_on))
            painter.drawRoundedRect(QRectF(self.rect()), tokens.RADIUS_SM, tokens.RADIUS_SM)
        elif self.underMouse() and self.isEnabled():
            painter.setBrush(QColor(p.hover_fill))
            painter.drawRoundedRect(QRectF(self.rect()), tokens.RADIUS_SM, tokens.RADIUS_SM)
        color = p.text if on else p.text_2
        font = QFont(self.font())
        font.setBold(on)
        painter.setFont(font)
        painter.setPen(QColor(color))
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(self.text())
        show_icon = self._owner.icons_visible()
        total = text_w + (SegmentedControl.ICON + 6 if show_icon else 0)
        x = (self.width() - total) / 2
        if show_icon:
            pm = svg_icon(self._icon, color, SegmentedControl.ICON).pixmap(SegmentedControl.ICON, SegmentedControl.ICON)
            painter.drawPixmap(int(x), int((self.height() - SegmentedControl.ICON) / 2), pm)
            x += SegmentedControl.ICON + 6
        painter.drawText(QRectF(x, 0, text_w + 2, self.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        painter.end()


class SegmentedControl(QWidget):
    """3칸(라이트 · 다크 · 시스템 따르기) 라디오 세그먼트. 트랙 surface_alt, 선택 칸 segment_on.

    키보드: 포커스 후 ←→(↑↓)·Home/End 로 이동하며 선택(라디오 그룹 방식), Space/Enter 는 현재 칸 재선택.
    선택이 바뀌면 selected_changed(key). set_value 는 신호 없이 표시만 바꾼다(emit=True 면 보냄).
    """

    selected_changed = Signal(str)
    ICON = 16
    TRACK_H, CELL_H, PAD, CELL_MIN_W = 44, 36, 4, 96
    ITEMS = (("light", "라이트", "mode-light"), ("dark", "다크", "mode-dark"), ("system", "시스템 따르기", "mode-system"))

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SegmentedControl")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(self.TRACK_H)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("화면 모드")
        self._kb_focus = False
        self._icons = True
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, _SegButton] = {}
        for key, label, icon in self.ITEMS:
            b = _SegButton(key, label, icon, self)
            self.buttons[key] = b
            self.group.addButton(b)
            b.toggled.connect(lambda on, k=key: self._on_toggled(k, on))
        self.buttons["system"].setChecked(True)
        self._sync_names()

    # --- 값 ---
    def value(self) -> str:
        for k, b in self.buttons.items():
            if b.isChecked():
                return k
        return "system"

    def set_value(self, key: str, emit: bool = False) -> None:
        b = self.buttons.get(key) or self.buttons["system"]
        if b.isChecked():
            return
        self.blockSignals(not emit)
        try:
            b.setChecked(True)
        finally:
            self.blockSignals(False)
        self._sync_names()
        self.update()

    def _on_toggled(self, key: str, on: bool) -> None:
        self._sync_names()
        self.update()
        if on:
            self.selected_changed.emit(key)

    def _sync_names(self) -> None:
        for key, label, _icon in self.ITEMS:
            b = self.buttons[key]
            b.setAccessibleName(f"화면 모드: {label}{', 선택됨' if b.isChecked() else ''}")

    # --- 기하 ---
    def icons_visible(self) -> bool:
        return self._icons

    def _needed(self, with_icon: bool) -> int:
        return 2 * self.PAD + sum(max(self.CELL_MIN_W, b.content_width(with_icon)) for b in self.buttons.values())

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._needed(True), self.TRACK_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._needed(False), self.TRACK_H)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._icons = self.width() >= self._needed(True)  # 좁으면(720px 창) 아이콘을 숨기고 글자만
        inner = self.width() - 2 * self.PAD
        keys = list(self.buttons)
        widths = [max(self.CELL_MIN_W, self.buttons[k].content_width(self._icons)) for k in keys]
        total = sum(widths) or 1
        x = self.PAD
        for i, k in enumerate(keys):
            w = round(inner * widths[i] / total) if i < len(keys) - 1 else self.width() - self.PAD - x
            self.buttons[k].setGeometry(x, self.PAD, w, self.CELL_H)
            x += w

    # --- 그리기 ---
    def paintEvent(self, e) -> None:  # noqa: N802
        p = tokens.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.surface_alt))
        painter.drawRoundedRect(QRectF(self.rect()), tokens.RADIUS_MD, tokens.RADIUS_MD)
        if self._kb_focus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.primary), 2))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), tokens.RADIUS_MD, tokens.RADIUS_MD)
        painter.end()

    # --- 키보드 ---
    def keyPressEvent(self, e) -> None:  # noqa: N802
        keys = list(self.buttons)
        cur = keys.index(self.value())
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.buttons[keys[max(cur - 1, 0)]].setChecked(True)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.buttons[keys[min(cur + 1, len(keys) - 1)]].setChecked(True)
        elif k == Qt.Key.Key_Home:
            self.buttons[keys[0]].setChecked(True)
        elif k == Qt.Key.Key_End:
            self.buttons[keys[-1]].setChecked(True)
        elif k in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.buttons[keys[cur]].setChecked(True)
        else:
            super().keyPressEvent(e)

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


# --- CollapsibleBox (색 선택 패널 펼침/접힘) ----------------------------------------------------


class CollapsibleBox(QWidget):
    """내용 위젯을 높이 트윈(MOTION_BASE)으로 펼치고 접는다. 모션이 꺼져 있으면 즉시."""

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._content = content
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(content)
        self._open = False
        content.hide()
        self.setMaximumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def is_open(self) -> bool:
        return self._open

    def _set_h(self, v: float) -> None:
        self.setMaximumHeight(max(int(v), 0))

    def set_open(self, on: bool, animate: bool = True) -> None:
        if on == self._open:
            return
        self._open = on
        full = self._content.sizeHint().height()
        if on:
            self._content.show()
            full = max(full, self._content.sizeHint().height())
        start = self.maximumHeight() if self.maximumHeight() < 16777215 else full
        end = full if on else 0

        def done() -> None:
            if on:
                self.setMaximumHeight(16777215)
            else:
                self._content.hide()
                self.setMaximumHeight(0)

        anim = motion.tween(self, start, end, motion.MOTION_BASE, self._set_h, motion.EASE_IN, on_finished=done, key="collapse") if animate and self.isVisible() else None
        if anim is None:
            done()


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


from .color_picker import ColorChip, ColorPicker, FollowChip, HueSlider, SVArea, Swatch, parse_hex_input  # noqa: E402,F401 — 재노출
