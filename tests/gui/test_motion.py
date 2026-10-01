"""모션 (M21-C, 스펙 §16.7~§16.9). 기본은 off(conftest) — 여기서는 켜서 시작·종료 상태만 검증한다 (타이밍 의존 최소).

애니메이션 결과를 기다릴 때는 finish_now 로 끝상태로 점프시키거나 짧게 waitUntil 한다.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel, QWidget

from swea_fetcher.gui import motion
from swea_fetcher.gui.widgets import Button, NavDelegate, Skeleton, Spinner, Toast, Toggle


@pytest.fixture(autouse=True)
def _reset_motion():
    motion._reset_for_tests()
    yield
    motion._reset_for_tests()


@pytest.fixture
def motion_on(monkeypatch):
    monkeypatch.setenv("SWEA_GUI_MOTION", "on")


@pytest.fixture
def shown(qtbot):
    host = QWidget()
    host.resize(400, 300)
    qtbot.addWidget(host)
    host.show()
    return host


# (a) 꺼져 있으면 애니메이션 객체를 만들지 않고 즉시 최종 상태
def test_off_creates_no_animation_and_applies_final_state(shown):
    assert not motion.motion_enabled()  # conftest 기본 off
    before = motion.created_count()
    lab = QLabel("0", shown)
    lab.show()
    assert motion.fade_in(shown) is None and motion.fade_slide_in(shown) is None
    assert motion.count_up(lab, 42, lambda v: f"{v:.0f}") is None and lab.text() == "42"
    assert motion.tween(shown, 0, 1, 100, lambda v: None) is None
    assert motion.loop(shown, 100, lambda v: None) is None
    assert shown.graphicsEffect() is None
    assert motion.created_count() == before


# 판정 순서: 환경변수 > offscreen > 동작 줄이기
def test_enabled_precedence(monkeypatch):
    monkeypatch.delenv("SWEA_GUI_MOTION", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert not motion.motion_enabled()  # offscreen 안전망
    monkeypatch.setenv("SWEA_GUI_MOTION", "on")
    assert motion.motion_enabled()  # on 은 아래 조건을 무시
    motion.set_user_reduce(True)
    assert motion.motion_enabled()
    monkeypatch.setenv("SWEA_GUI_MOTION", "off")
    assert not motion.motion_enabled()


# (e) 설정 토글이 motion_enabled 에 반영
def test_reduce_motion_setting_disables(monkeypatch):
    monkeypatch.delenv("SWEA_GUI_MOTION", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "windows")
    monkeypatch.setattr(motion, "_os_animations_off", lambda: False)
    assert motion.motion_enabled()
    motion.set_user_reduce(True)
    assert not motion.motion_enabled()
    motion.set_user_reduce(False)
    monkeypatch.setattr(motion, "_os_animations_off", lambda: True)  # Windows 애니메이션 효과 꺼짐/원격 세션
    assert not motion.motion_enabled()


def test_settings_toggle_applies_and_persists(main_window):
    sp = main_window.settings_page
    assert sp.reduce_motion.objectName() == "ReduceMotionToggle" and not sp.reduce_motion.isChecked()
    sp.reduce_motion.setChecked(True)
    assert motion.user_reduce() and main_window.qs.value("ui/reduce_motion", False, type=bool) is True
    sp.reduce_motion.setChecked(False)
    assert not motion.user_reduce()


# (b) fade_in 후 효과 제거
def test_fade_in_removes_effect_at_end(motion_on, shown):
    w = QWidget(shown)
    w.show()
    anim = motion.fade_in(w)
    assert anim is not None and w.graphicsEffect() is not None  # 시작 상태: 효과가 걸림
    motion.finish_now(w, "fade")
    assert w.graphicsEffect() is None  # 종료 상태: 제거


def test_only_one_opacity_effect_at_a_time(motion_on, shown):
    a, b = QWidget(shown), QWidget(shown)
    a.show()
    b.show()
    assert motion.fade_in(a) is not None
    assert motion.fade_in(b) is None and b.graphicsEffect() is None  # 동시 1개 규칙
    motion.finish_now(a, "fade")


# (d) 연타 시 진행 중 애니메이션이 끝상태로 점프
def test_page_transition_rapid_calls_jump_to_end(motion_on, shown):
    page = QWidget(shown)
    page.setGeometry(10, 20, 100, 100)
    page.show()
    pos = page.pos()
    assert motion.fade_slide_in(page) is not None
    assert page.pos() != pos  # 시작: 아래로 밀려 있음
    motion.fade_slide_in(page)  # 연타: 이전 것은 즉시 끝, 새로 시작
    motion.finish_now(page, "page")
    assert page.pos() == pos and page.graphicsEffect() is None


def test_fade_slide_skips_hidden_widget(motion_on):
    w = QWidget()
    assert motion.fade_slide_in(w) is None  # 보이지 않으면(시작 복원 중 등) 생략


# (c) count_up: 접근성 이름은 시작 즉시 최종값, 끝나면 텍스트 = 최종값
def test_count_up_accessible_name_immediate(motion_on, shown):
    lab = QLabel("0", shown)
    lab.show()
    anim = motion.count_up(lab, 12, lambda v: f"{v:.0f}문제", start=0, accessible="12문제")
    assert anim is not None and lab.accessibleName() == "12문제"
    motion.finish_now(lab, "count")
    assert lab.text() == "12문제"


def test_count_up_same_value_is_static(motion_on, shown):
    lab = QLabel("5", shown)
    lab.show()
    assert motion.count_up(lab, 5, lambda v: f"{v:.0f}", start=5) is None and lab.text() == "5"


# Button hover/눌림, Toggle, Toast
def test_button_hover_and_press_end_states(motion_on, shown):
    b = Button("확인", shown)
    b.show()
    b._animate_hover(1.0)
    assert b._hover_t is not None  # 보간 중
    motion.finish_now(b, "hover")
    assert b._hover_t is None
    b._on_pressed()
    motion.finish_now(b, "press")
    assert b._press_scale == pytest.approx(motion.PRESS_SCALE)
    b._on_released()
    motion.finish_now(b, "press")
    assert b._press_scale == pytest.approx(1.0)


def test_toggle_animates_and_ends_at_state(motion_on, shown):
    t = Toggle("옵션", shown)
    t.show()
    t.setChecked(True)
    assert t._t is not None
    motion.finish_now(t, "toggle")
    assert t._t is None and t.isChecked()


def test_toast_enter_and_exit(motion_on, shown):
    toast = Toast(shown)
    toast.show_message("저장했습니다", ms=5000)
    assert toast._opacity == 0.0 and toast._dy > 0  # 등장 시작: 투명 + 아래
    motion.finish_now(toast, "toast")
    assert toast._opacity == 1.0 and toast._dy == 0.0
    toast.dismiss()
    assert not toast.isHidden()  # 퇴장 애니메이션 중
    motion.finish_now(toast, "toast")
    assert toast.isHidden()


# (f) 무한 애니메이션은 hide() 후 정지, 모션 off 면 정적
def test_spinner_and_skeleton_stop_when_hidden(motion_on, shown):
    for cls in (Spinner, Skeleton):
        w = cls(shown)
        w.show()
        assert w.is_animating()
        w.hide()
        assert not w.is_animating()
        w.show()
        assert w.is_animating()


def test_spinner_static_when_motion_off(shown):
    s = Spinner(shown)
    s.show()
    assert not s.is_animating()


def test_replaced_delayed_tween_cannot_restart(motion_on, shown, qtbot):
    values, finished = [], []
    motion.tween(shown, 0, 1, 100, values.append, delay_ms=20, on_finished=lambda: finished.append(True))
    motion.finish_now(shown)
    assert values[-1] == 1 and finished == [True]
    qtbot.wait(40)
    assert values == [1] and not motion.is_running(shown, "default")


def test_turning_motion_off_finishes_previous_tween(motion_on, shown, monkeypatch):
    values = []
    motion.tween(shown, 0, 1, 100, values.append)
    monkeypatch.setenv("SWEA_GUI_MOTION", "off")
    assert motion.tween(shown, 1, 2, 100, values.append) is None
    assert values[-1] == 1 and not motion.is_running(shown, "default")


def test_button_busy_shows_spinner(shown):
    b = Button("저장", shown)
    b.show()
    b.set_busy(True)
    assert b.is_busy() and not b.isEnabled() and b._spinner is not None and not b._spinner.isHidden()
    b.set_busy(False)
    assert b.isEnabled() and b._spinner.isHidden()


# 내비 알약
def test_nav_pill_moves_to_selected_row(motion_on, main_window):
    w = main_window
    w.show()
    d = w.nav.itemDelegate()
    assert isinstance(d, NavDelegate)
    w.nav.setCurrentRow(3)
    assert d.is_animating()
    motion.finish_now(d, "pill")
    pill = d.pill_rect()
    assert pill is not None and pill.top() == pytest.approx(d._pill_for(3).top())


def test_nav_pill_static_when_off(main_window):
    main_window.show()
    d = main_window.nav.itemDelegate()
    main_window.nav.setCurrentRow(2)
    assert not d.is_animating() and d._anim_y is None


# 페이지 전환은 시작 복원 중에는 하지 않고, 켜져 있으면 효과가 끝나면 제거된다
def test_page_switch_fades_then_clears_effect(motion_on, main_window):
    w = main_window
    w.show()
    w.goto("history")
    page = w.stack.currentWidget()
    motion.finish_now(page, "page")
    assert page.graphicsEffect() is None


# 보조 위젯 단위
def test_elided_label_parts_drop_time_first(qtbot):
    from swea_fetcher.gui.widgets import ElidedLabel

    lab = ElidedLabel()
    qtbot.addWidget(lab)
    lab.resize(400, 20)
    lab.show()
    lab.set_parts(["코드 평가", "14:02", "16.2초"])
    assert lab.text() == "코드 평가 · 14:02 · 16.2초"
    lab.resize(95, 20)
    assert lab.text() == "코드 평가 · 16.2초" or lab.text() == "코드 평가"  # 시각이 먼저 빠진다
    assert "14:02" not in lab.text() and lab.fullText() == "코드 평가 · 14:02 · 16.2초"
