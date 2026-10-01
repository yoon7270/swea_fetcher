"""GUI 모션 헬퍼 (M21-C, 스펙 §16.7~§16.9). 모든 애니메이션은 이 모듈을 통해서만 만든다.

핵심 계약: `motion_enabled()` 가 False 이면 **애니메이션 객체를 만들지 않고** 호출자가 즉시 최종 상태를 적용한다.
(헬퍼는 None 을 돌려주거나 최종 상태를 바로 적용한다 — 호출자는 반환값이 None 인지 보고 분기하면 된다.)

켜짐 판정 순서 (`motion_enabled`):
  1. 환경변수 SWEA_GUI_MOTION = off/0/false → False, on/1/true → True (아래 조건 무시 — 모션 테스트 전용)
  2. QT_QPA_PLATFORM == offscreen → False (테스트 안전망)
  3. 사용자 설정 "동작 줄이기" (`set_user_reduce`) → False
  4. Windows: '애니메이션 효과' 꺼짐 또는 원격 세션 → False (조회 실패는 무시)
  5. MotionGuard 가 성능 문제로 이 세션에서 끔 → False
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QObject, QPoint, QPropertyAnimation, QVariantAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

from .theme import tokens

# --- 토큰 (스펙 §16.7) ---------------------------------------------------------------------
MOTION_FAST = tokens.MOTION_FAST  # 120ms: hover 색
MOTION_BASE = tokens.MOTION_BASE  # 200ms: 페이지·내비 알약·등장
MOTION_EXIT = tokens.MOTION_EXIT  # 150ms: 퇴장
MOTION_FADE = 180  # 카드·배너·결과 등장
MOTION_TOGGLE = 180
MOTION_NUMBER = 600  # 카운트업
MOTION_HEAT = 700  # 잔디 전체
MOTION_BAR = 400  # 차트 막대
PRESS_DOWN_MS, PRESS_UP_MS, PRESS_SCALE = 80, 120, 0.97
SPINNER_MS = 900
SKELETON_MS = 1200
PAGE_SLIDE_PX = 8

EASE_IN = QEasingCurve.Type.OutCubic  # 진입 (토스풍 감속)
EASE_OUT = QEasingCurve.Type.InCubic  # 퇴장

GUARD_FRAME_MS = 50  # 이보다 긴 프레임 간격이
GUARD_STREAK = 3  # 연속 이 횟수면 세션 동안 모션을 끈다

# --- 상태 -----------------------------------------------------------------------------------
_user_reduce = False
_guard_off = False
_os_off: bool | None = None  # OS 조회 결과 캐시 (한 번만)
_created = 0  # 만들어진 애니메이션 수 (테스트용 계측)


def _env_override() -> bool | None:
    v = os.environ.get("SWEA_GUI_MOTION", "").strip().lower()
    if v in ("off", "0", "false", "no"):
        return False
    if v in ("on", "1", "true", "yes"):
        return True
    return None


def _os_animations_off() -> bool:
    """Windows 에서 '애니메이션 효과' 가 꺼져 있거나 원격 세션이면 True. 조회 실패·비 Windows 는 False(= 무시)."""
    global _os_off
    if _os_off is not None:
        return _os_off
    off = False
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            if user32.GetSystemMetrics(0x1000):  # SM_REMOTESESSION
                off = True
            else:
                flag = ctypes.c_int(1)
                ok = user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)  # SPI_GETCLIENTAREAANIMATION
                if ok and flag.value == 0:
                    off = True
        except Exception:  # noqa: BLE001 — 조회 실패는 무시
            off = False
    _os_off = off
    return off


def motion_enabled() -> bool:
    env = _env_override()
    if env is not None:
        return env
    if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen":
        return False
    if _user_reduce or _guard_off:
        return False
    return not _os_animations_off()


def set_user_reduce(reduce: bool) -> None:
    """설정 "동작 줄이기". 켜는 순간 이후의 애니메이션이 모두 즉시 최종 상태가 된다."""
    global _user_reduce
    _user_reduce = bool(reduce)


def user_reduce() -> bool:
    return _user_reduce


def created_count() -> int:
    return _created


def _reset_for_tests() -> None:
    global _user_reduce, _guard_off, _os_off, _created
    _user_reduce = False
    _guard_off = False
    _os_off = None
    _created = 0
    MotionGuard.reset()
    _opacity_owner.clear()


class MotionGuard:
    """프레임 간격이 50ms 를 넘는 일이 연속 3번이면 세션 동안 모션을 끈다 (원격 데스크톱·소프트웨어 렌더링 방어).

    유한 애니메이션의 프레임만 센다 (스피너·스켈레톤 같은 무한 반복은 GUI 스레드가 잠깐 막혀도 느려 보이므로 제외).
    """

    _streak = 0

    @classmethod
    def reset(cls) -> None:
        cls._streak = 0

    @classmethod
    def frame(cls, gap_ms: float) -> bool:
        """한 프레임의 간격(ms)을 기록. 이번 호출로 모션이 꺼졌으면 True."""
        global _guard_off
        if gap_ms > GUARD_FRAME_MS:
            cls._streak += 1
            if cls._streak >= GUARD_STREAK and not _guard_off:
                _guard_off = True
                return True
        else:
            cls._streak = 0
        return False


# --- 공통 도우미 ------------------------------------------------------------------------------


def _registry(owner: QObject) -> dict:
    reg = owner.__dict__.get("_motion_anims")
    if reg is None:
        reg = {}
        owner.__dict__["_motion_anims"] = reg
    return reg


def finish_now(owner: QObject, key: str | None = None) -> None:
    """진행 중인 애니메이션을 끝상태로 점프시킨다 (연타 대비). key 가 없으면 owner 의 전부."""
    reg = owner.__dict__.get("_motion_anims")
    if not reg:
        return
    for k in ([key] if key is not None else list(reg)):
        anim = reg.pop(k, None)
        if anim is None:
            continue
        try:
            running = anim.state() == QAbstractAnimation.State.Running
            anim.setCurrentTime(anim.duration())
            anim.stop()
            if not running:  # 지연 시작 대기·일시 정지도 끝값과 정리 콜백 적용
                anim.finished.emit()
        except RuntimeError:  # 이미 파괴됨
            pass


def is_running(owner: QObject, key: str) -> bool:
    anim = owner.__dict__.get("_motion_anims", {}).get(key)
    try:
        return anim is not None and anim.state() == QAbstractAnimation.State.Running
    except RuntimeError:
        return False


def tween(
    owner: QObject,
    start: float,
    end: float,
    ms: int,
    setter: Callable[[float], None],
    easing: QEasingCurve.Type = EASE_IN,
    on_finished: Callable[[], None] | None = None,
    key: str = "default",
    delay_ms: int = 0,
) -> QVariantAnimation | None:
    """start→end 를 ms 동안 보간해 setter(value) 로 알린다. 모션이 꺼져 있으면 아무 것도 만들지 않고 None
    (호출자가 최종 상태를 직접 적용). 같은 owner·key 의 진행 중 애니메이션은 먼저 끝상태로 점프시킨다."""
    global _created
    finish_now(owner, key)
    if not motion_enabled():
        return None
    anim = QVariantAnimation(owner)
    _created += 1
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(max(int(ms), 1))
    anim.setEasingCurve(QEasingCurve(easing))
    last = [None]

    def _on_value(v) -> None:
        now = time.perf_counter()
        if last[0] is not None and MotionGuard.frame((now - last[0]) * 1000.0):
            finish_now(owner, key)  # 이 애니메이션도 즉시 끝상태로
            return
        last[0] = now
        setter(float(v))

    anim.valueChanged.connect(_on_value)

    def _done() -> None:
        reg = owner.__dict__.get("_motion_anims", {})
        if reg.get(key) is anim:
            reg.pop(key, None)
        if on_finished is not None:
            on_finished()
        anim.deleteLater()

    anim.finished.connect(_done)
    _registry(owner)[key] = anim
    if delay_ms > 0:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(delay_ms, lambda a=anim: a.start() if _alive(a) and _registry(owner).get(key) is a else None)
    else:
        anim.start()
    return anim


def _alive(anim: QVariantAnimation) -> bool:
    try:
        anim.state()
        return True
    except RuntimeError:
        return False


def loop(owner: QObject, ms: int, setter: Callable[[float], None], key: str = "loop") -> QVariantAnimation | None:
    """0→1 을 무한 반복하는 선형 애니메이션 (스피너·스켈레톤). 꺼져 있으면 None (정적 그림).
    호출자가 보이지 않을 때·창이 비활성일 때 pause()/resume() 한다. 유휴 CPU 를 위해 보일 때만 돌린다."""
    global _created
    if not motion_enabled():
        return None
    old = owner.__dict__.get("_motion_anims", {}).pop(key, None)
    if old is not None:
        try:
            old.stop()
            old.deleteLater()
        except RuntimeError:
            pass
    anim = QVariantAnimation(owner)
    _created += 1
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(max(int(ms), 1))
    anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.Linear))
    anim.setLoopCount(-1)
    anim.valueChanged.connect(lambda v: setter(float(v)))
    _registry(owner)[key] = anim
    anim.start()
    return anim


# --- 불투명도 효과 (등장) -----------------------------------------------------------------------

_opacity_owner: dict[int, QWidget] = {}  # 동시에 효과가 걸린 위젯은 1개 — 성능 규칙 (스펙 §16.7)


def _active_effect_widget() -> QWidget | None:
    for w in list(_opacity_owner.values()):
        try:
            if w.graphicsEffect() is not None:
                return w
        except RuntimeError:
            pass
    _opacity_owner.clear()
    return None


def _release_effect(w: QWidget) -> None:
    try:
        w.setGraphicsEffect(None)  # 효과 제거 → 글자 ClearType 복원
    except RuntimeError:
        pass
    _opacity_owner.pop(id(w), None)


def _begin_effect(w: QWidget) -> QGraphicsOpacityEffect | None:
    """w 에 불투명도 효과를 건다. 이미 다른 위젯에 걸려 있으면(동시 1개 규칙) None."""
    other = _active_effect_widget()
    if other is not None and other is not w:
        return None
    if w.graphicsEffect() is not None:
        return None
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(0.0)
    w.setGraphicsEffect(eff)
    _opacity_owner[id(w)] = w
    return eff


def fade_in(w: QWidget, ms: int = MOTION_FADE) -> QPropertyAnimation | QVariantAnimation | None:
    """불투명도 0→1 (이동 없음). 보이는 위젯에만. 끝나면 효과를 제거한다. 꺼져 있으면 None."""
    if not motion_enabled() or not w.isVisible():
        return None
    finish_now(w, "fade")
    eff = _begin_effect(w)
    if eff is None:
        return None

    def _set(v: float) -> None:
        try:
            eff.setOpacity(v)
        except RuntimeError:
            pass

    anim = tween(w, 0.0, 1.0, ms, _set, EASE_IN, on_finished=lambda: _release_effect(w), key="fade")
    if anim is None:
        _release_effect(w)
    return anim


def fade_slide_in(w: QWidget, ms: int = MOTION_BASE, dy: int = PAGE_SLIDE_PX) -> QVariantAnimation | None:
    """페이지 전환: 불투명도 0→1 + 아래 dy px→0. 끝나면 효과 제거·위치 확정. 연타 시 이전 것은 즉시 끝상태.
    보이지 않는 위젯(시작 복원 중 등)이나 꺼져 있으면 None."""
    if not motion_enabled() or not w.isVisible():
        return None
    finish_now(w, "page")
    other = _active_effect_widget()
    if other is not None and other is not w:  # 이전 페이지 전환 효과가 남아 있다면 먼저 정리
        finish_now(other)
        _release_effect(other)
    eff = _begin_effect(w)
    if eff is None:
        return None
    base = QPoint(w.pos())

    def _set(v: float) -> None:
        try:
            eff.setOpacity(v)
            w.move(base.x(), base.y() + round(dy * (1.0 - v)))
        except RuntimeError:
            pass

    def _done() -> None:
        try:
            w.move(base)
            lay = w.parentWidget().layout() if w.parentWidget() is not None else None
            if lay is not None:
                lay.activate()  # 레이아웃이 확정한 위치로
        except RuntimeError:
            pass
        _release_effect(w)

    anim = tween(w, 0.0, 1.0, ms, _set, EASE_IN, on_finished=_done, key="page")
    if anim is None:
        _release_effect(w)
    else:
        _set(0.0)
    return anim


# --- 숫자 카운트업 ----------------------------------------------------------------------------


def count_up(
    label: QLabel,
    to: float,
    fmt: Callable[[float], str] = lambda v: str(int(round(v))),
    start: float | None = None,
    ms: int = MOTION_NUMBER,
    accessible: str | None = None,
) -> QVariantAnimation | None:
    """label 의 표시 텍스트를 start(없으면 0)→to 로 보간. accessibleName·toolTip 은 호출자가 최종값으로 즉시 정한다
    (accessible 를 주면 즉시 그 값으로). 꺼져 있거나 start==to 이면 즉시 최종 텍스트."""
    final = fmt(to)
    if accessible is not None:
        label.setAccessibleName(accessible)
    finish_now(label, "count")
    begin = 0.0 if start is None else float(start)
    if not motion_enabled() or begin == float(to) or not label.isVisible():
        label.setText(final)
        return None
    label.setText(fmt(begin))
    anim = tween(label, begin, float(to), ms, lambda v: label.setText(fmt(v)), EASE_IN, on_finished=lambda: label.setText(final), key="count")
    if anim is None:
        label.setText(final)
    return anim


def stop_loop(owner: QObject, key: str = "loop") -> None:
    """loop() 로 시작한 무한 애니메이션을 멈추고 치운다 (숨김·창 비활성)."""
    anim = owner.__dict__.get("_motion_anims", {}).pop(key, None)
    if anim is not None:
        try:
            anim.stop()
            anim.deleteLater()
        except RuntimeError:
            pass


def loop_running(owner: QObject, key: str = "loop") -> bool:
    return is_running(owner, key)


def forced_on() -> bool:
    """환경변수로 강제로 켠 상태 (모션 테스트). 이때는 창 활성 여부와 무관하게 무한 애니메이션을 돌린다."""
    return _env_override() is True
