"""M21 1단계: 테마(색 조합) 정의·대비, 전환 시 QSS 재적용·저장, Pretendard 등록·폴백, 기본 창 크기, 공용 컴포넌트."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt, qInstallMessageHandler
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton

from swea_fetcher.gui.theme import fonts, tokens
from swea_fetcher.gui.widgets import Button, EmptyState, PageColumn, ThemeChip, Toast, Toggle, set_class


def _lum(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


@pytest.fixture(autouse=True)
def _restore_theme(qapp):
    yield
    tokens.set_theme(tokens.DEFAULT_THEME)
    qapp.setStyleSheet("")


# --- 테마 정의 ------------------------------------------------------------------------


def test_theme_list_shape():
    keys = tokens.theme_keys()
    assert len(keys) >= 5 and len(set(keys)) == len(keys)
    assert keys[0] == tokens.DEFAULT_THEME == "blue"
    assert tokens.LIGHT is tokens.get_theme("blue").palette
    assert all(t.label for t in tokens.THEMES)
    assert tokens.get_theme("blue").palette.primary_action == "#1F6FE8" and tokens.get_theme("blue").palette.primary == "#3182F6"


@pytest.mark.parametrize("theme", tokens.THEMES, ids=lambda t: t.key)
def test_theme_contrast(theme):
    p = theme.palette
    assert contrast(p.primary_text, p.primary_action) >= 4.5  # 버튼 면 위 흰 글자
    assert contrast(p.primary_text, p.primary_hover) >= 4.5
    assert contrast(p.primary_text, p.primary_pressed) >= 4.5
    for face in (p.primary_soft, p.primary_soft_hover, p.primary_soft_pressed):  # tonal 버튼·내비 알약 위 글자
        assert contrast(p.primary_soft_text, face) >= 4.5
    assert contrast(p.primary, p.surface) >= 3.0  # 글자 없는 면(링·토글·차트)은 그래픽 3:1


@pytest.mark.parametrize("theme", tokens.THEMES, ids=lambda t: t.key)
def test_neutral_text_contrast_shared(theme):
    p = theme.palette
    assert contrast(p.text_3, p.bg) >= 4.5 and contrast(p.text_2, p.surface) >= 4.5
    assert contrast(p.toast_text, p.toast_bg) >= 4.5
    assert contrast(p.secondary_text, p.secondary) >= 4.5


def test_unknown_theme_key_falls_back():
    assert tokens.get_theme("없는-테마").key == tokens.DEFAULT_THEME
    assert tokens.get_theme(None).key == tokens.DEFAULT_THEME
    assert tokens.set_theme("zzz").key == tokens.DEFAULT_THEME and tokens.current() is tokens.LIGHT


@pytest.mark.parametrize("theme", tokens.THEMES, ids=lambda t: t.key)
def test_qss_parses_for_every_theme(qapp, theme):
    """Qt 가 QSS 를 파싱하지 못하면 경고를 낸다 — 어느 테마에서도 경고가 없어야 한다."""
    msgs: list[str] = []
    prev = qInstallMessageHandler(lambda _t, _c, m: msgs.append(m))
    try:
        qapp.setStyleSheet(tokens.build_qss(theme.palette))
    finally:
        qInstallMessageHandler(prev)
    assert not [m for m in msgs if "parse" in m.lower()], msgs
    assert theme.palette.primary_action in qapp.styleSheet() or theme.palette.primary_text in qapp.styleSheet()


def test_statement_css_uses_relative_headings():
    css = tokens.build_statement_css()
    assert "line-height: 150%" in css and "h1 { font-size: 16px; }" in css.replace("{{", "{").replace("}}", "}")


# --- 전환·저장 ------------------------------------------------------------------------


def test_theme_chips_in_settings(main_window):
    chips = main_window.settings_page.theme_chips
    assert list(chips) == tokens.theme_keys()
    assert chips["blue"].isChecked() and sum(c.isChecked() for c in chips.values()) == 1
    assert all(isinstance(c, ThemeChip) and c.text() for c in chips.values())


def test_theme_switch_reapplies_qss_and_saves(main_window, qapp):
    qapp.setStyleSheet(tokens.build_qss())
    before = qapp.styleSheet()
    green = tokens.get_theme("green").palette
    assert green.primary_soft_text not in before
    main_window.settings_page.theme_chips["green"].click()
    after = qapp.styleSheet()
    assert after != before and green.primary_soft_text in after
    assert tokens.current_theme_key() == "green" and tokens.current() is green
    assert str(main_window.qs.value("ui/theme")) == "green"
    assert main_window.settings_page.theme_chips["green"].isChecked()
    assert main_window.statusBar().currentMessage().startswith("테마를 바꿨습니다")
    # 내비 아이콘도 새 색으로 다시 만들어진다 (선택 상태 그림이 바뀜)
    assert not main_window.nav.item(0).icon().isNull()


def test_theme_loaded_from_settings_on_start(main_window, valid_config, qtbot):
    from swea_fetcher.gui.main_window import MainWindow

    main_window.qs.setValue("ui/theme", "rose")
    win = MainWindow(config_dir=valid_config)
    qtbot.addWidget(win)
    assert tokens.current_theme_key() == "rose"
    assert win.settings_page.theme_chips["rose"].isChecked()
    main_window.qs.setValue("ui/theme", "깨진값")
    win2 = MainWindow(config_dir=valid_config)
    qtbot.addWidget(win2)
    assert tokens.current_theme_key() == tokens.DEFAULT_THEME


# --- 글꼴 ----------------------------------------------------------------------------


def test_pretendard_files_bundled_unmodified():
    for name in (*fonts.FONT_FILES, "Pretendard-LICENSE.txt"):
        assert (fonts.FONT_DIR / name).is_file(), name
    lic = (fonts.FONT_DIR / "Pretendard-LICENSE.txt").read_text(encoding="utf-8")
    assert "SIL Open Font License" in lic and "Pretendard" in lic
    assert tokens.FONT_FAMILY.startswith('"Pretendard", "Malgun Gothic"')


def test_load_fonts_registers_pretendard(qapp):
    assert fonts.load_fonts() == list(fonts.FONT_FILES)
    assert fonts.is_available()
    assert "Bold" in QFontDatabase.styles("Pretendard")


def test_load_fonts_fallback_never_raises(qapp, tmp_path: Path):
    assert fonts.load_fonts(tmp_path / "없는-폴더") == []  # 파일 없음
    (tmp_path / fonts.FONT_FILES[0]).write_bytes(b"not a font")  # 깨진 파일: 등록 실패
    assert fonts.load_fonts(tmp_path) == []


# --- 창 크기 -------------------------------------------------------------------------


def test_default_window_size_and_minimum(main_window):
    assert tokens.WINDOW_DEFAULT == (960, 680) and tokens.WINDOW_MIN == (720, 480)
    assert (main_window.width(), main_window.height()) == (960, 680)
    assert (main_window.minimumWidth(), main_window.minimumHeight()) == (720, 480)


def test_saved_geometry_is_kept(main_window, valid_config, qtbot):
    from swea_fetcher.gui.main_window import MainWindow

    main_window.resize(777, 555)
    main_window.qs.setValue("window/geometry", main_window.saveGeometry())
    win = MainWindow(config_dir=valid_config)
    qtbot.addWidget(win)
    assert (win.width(), win.height()) == (777, 555)


# --- Button ---------------------------------------------------------------------------


def test_button_is_qpushbutton_and_face_by_class(qtbot):
    p = tokens.current()
    b = Button("저장")
    qtbot.addWidget(b)
    assert isinstance(b, QPushButton)
    assert b.face_color().name().upper() == p.secondary.upper()  # 기본(회색)
    set_class(b, "primary")
    assert b.face_color().name().upper() == p.primary_action.upper()
    set_class(b, "tonal")
    assert b.face_color().name().upper() == p.primary_soft.upper()
    set_class(b, "danger")
    assert b.face_color() is None  # 투명 (hover 시 연한 빨강)
    set_class(b, "link")
    assert b.face_color() is None
    set_class(b, "primary")
    b.setEnabled(False)
    assert b.face_color().name().upper() == p.border.upper()  # 비활성도 면은 유지
    set_class(b, "tonal")
    assert b.face_color().name().upper() == p.bg_subtle.upper()


def test_button_face_follows_current_theme(qtbot):
    b = Button("확인")
    set_class(b, "primary")
    qtbot.addWidget(b)
    tokens.set_theme("orange")
    assert b.face_color().name().upper() == tokens.get_theme("orange").palette.primary_action.upper()


def test_button_busy_blocks_clicks(qtbot):
    b = Button("저장")
    qtbot.addWidget(b)
    clicks: list[int] = []
    b.clicked.connect(lambda: clicks.append(1))
    b.show()
    b.set_busy(True)
    assert b.is_busy() and not b.isEnabled()
    qtbot.mouseClick(b, Qt.MouseButton.LeftButton)
    assert clicks == []
    b.set_busy(False)
    qtbot.mouseClick(b, Qt.MouseButton.LeftButton)
    assert clicks == [1] and b.isEnabled()


def test_button_in_banner_has_white_face(main_window):
    banner = main_window.fetch_page.banner
    banner.show_message("error", "제목", "본문", [("retry", "다시 시도")])
    b = banner._buttons[0]
    assert isinstance(b, Button) and b.face_color().name().upper() == tokens.current().surface.upper()


def test_all_page_buttons_are_custom_buttons(main_window):
    plain = [b for b in main_window.findChildren(QPushButton) if type(b) is QPushButton]
    # 설정의 원형 색 칩(잔디 색)만 자체 QSS 를 쓰는 일반 QPushButton
    assert all(b.objectName().startswith("Heat") for b in plain), [b.objectName() for b in plain]


# --- Toggle ---------------------------------------------------------------------------


def test_toggle_state_and_signals(qtbot):
    t = Toggle("성장 기록 사용")
    qtbot.addWidget(t)
    t.resize(400, 40)
    t.show()
    assert isinstance(t, QCheckBox) and not t.isChecked()
    seen: list[bool] = []
    t.toggled.connect(seen.append)
    qtbot.mouseClick(t, Qt.MouseButton.LeftButton, pos=QPoint(10, 20))  # 행 전체가 클릭 영역 (스위치 밖 글자 쪽)
    assert t.isChecked() and seen == [True]
    t.setChecked(False)
    assert seen == [True, False]
    qtbot.keyClick(t, Qt.Key.Key_Space)
    assert t.isChecked()
    assert t.track_rect().width() == 44 and t.track_rect().height() == 26
    t.setEnabled(False)
    qtbot.mouseClick(t, Qt.MouseButton.LeftButton)
    assert t.isChecked()  # 비활성은 반응 없음


def test_settings_toggles_keep_object_names(main_window):
    sp = main_window.settings_page
    for name, attr in (("GrowthEnabledCheck", "growth_enabled"), ("GrowthCommentCheck", "growth_comment")):
        w = sp.findChild(QCheckBox, name)
        assert isinstance(w, Toggle) and w is getattr(sp, attr)
    assert isinstance(sp.auto_push, Toggle)


# --- Toast · notify -------------------------------------------------------------------


def test_toast_show_replace_and_dismiss(qtbot):
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(600, 400)
    host.show()
    t = Toast(host)
    assert not t.isVisible() and t.focusPolicy() == Qt.FocusPolicy.NoFocus
    t.show_message("폴더를 열었습니다")
    assert t.isVisible() and t.message() == "폴더를 열었습니다" and t.kind() == "success"
    g = t.geometry()
    assert abs((g.center().x()) - host.width() / 2) <= 2  # 하단 중앙
    assert g.bottom() <= host.height() + Toast.MARGIN
    t.show_message("두 번째", "warning")  # 새 메시지가 기존 것을 교체
    assert t.message() == "두 번째" and t.kind() == "warning"
    host.resize(800, 500)  # 리사이즈 시 재배치
    assert abs(t.geometry().center().x() - 400) <= 2
    pill = t.pill_rect().center().toPoint()
    qtbot.mouseClick(t, Qt.MouseButton.LeftButton, pos=pill)  # 클릭하면 닫힘
    assert not t.isVisible()


def test_toast_auto_dismiss(qtbot):
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    t = Toast(host)
    t.show_message("곧 사라짐", ms=500)
    assert t.isVisible()
    qtbot.waitUntil(lambda: not t.isVisible(), timeout=2000)


def test_notify_shows_toast_and_status_bar(main_window):
    main_window.notify("지문 캐시를 지웠습니다")
    assert (not main_window.toast.isHidden()) and main_window.toast.message() == "지문 캐시를 지웠습니다"
    assert main_window.statusBar().currentMessage() == "지문 캐시를 지웠습니다"  # 상태바에도 항상
    main_window.notify("조심", kind="warning")
    assert main_window.toast.kind() == "warning"


def test_page_messages_route_done_vs_progress(main_window):
    main_window.fetch_page.status_message.emit("폴더를 열었습니다")
    assert (not main_window.toast.isHidden()) and main_window.toast.message() == "폴더를 열었습니다"
    main_window.toast.dismiss()
    main_window.fetch_page.status_message.emit("취소 중…")  # 진행 중 문구는 상태바만
    assert main_window.toast.isHidden() and main_window.statusBar().currentMessage() == "취소 중…"
    main_window.fetch_page.status_message.emit("폴더를 열지 못했습니다")  # 실패는 토스트 금지
    assert main_window.toast.isHidden()
    main_window.fetch_page.status_message.emit("저장 완료 · 25730")
    assert (not main_window.toast.isHidden())


# --- PageColumn · EmptyState · LogView -------------------------------------------------


def test_page_column_max_width_and_margins(qtbot):
    pc = PageColumn()
    qtbot.addWidget(pc)
    pc.resize(1400, 600)
    pc.show()
    assert pc.column.width() <= PageColumn.MAX_W + 2 * PageColumn.MARGIN
    assert pc.body.contentsMargins().left() == 32
    pc.resize(780, 600)
    assert pc.body.contentsMargins().left() == 24 and pc.body.contentsMargins().top() == 24
    assert abs(pc.column.geometry().center().x() - 390) <= 2  # 가운데 정렬


def test_empty_state_icon_optional(qtbot):
    plain = EmptyState("제목", "본문", "버튼")
    qtbot.addWidget(plain)
    assert plain.icon is None and isinstance(plain.button, Button) and plain.button.property("class") == "primary"
    iconed = EmptyState("제목", "본문", icon="nav-problem")
    qtbot.addWidget(iconed)
    assert iconed.icon is not None and iconed.icon.size().width() == 64 and iconed.button is None


def test_log_view_is_card_with_clear_link(main_window):
    log = main_window.fetch_page.log
    assert isinstance(log.clear_btn, Button) and log.clear_btn.property("class") == "link"
    assert log.toggle.objectName() == "LogToggle" and log.text.objectName() == "log"
    log.append("hello")
    assert "hello" in log.text.toPlainText()
    log.clear_btn.click()
    assert log.text.toPlainText() == ""


def test_app_font_disables_hinting(qapp):
    """Pretendard 는 기본 힌팅에서 9~10pt 의 ㅡ 획이 사라진다 → 앱 기본 글꼴의 힌팅을 끈다."""
    from PySide6.QtGui import QFont

    from swea_fetcher.gui.theme import fonts

    before = qapp.font()
    try:
        fonts.apply_app_font(qapp)
        assert qapp.font().hintingPreference() == QFont.HintingPreference.PreferNoHinting
    finally:
        qapp.setFont(before)


def test_toast_measures_with_styled_font(qtbot):
    """QSS 로 글꼴이 커져도 토스트 폭이 실제 글자 폭을 담는다 (스타일 적용 전에 재서 말줄임되던 회귀)."""
    from PySide6.QtWidgets import QWidget

    from swea_fetcher.gui.widgets import Toast

    host = QWidget()
    host.setStyleSheet("QWidget { font-size: 20pt; }")
    qtbot.addWidget(host)
    host.resize(800, 400)
    host.show()
    toast = Toast(host)
    toast.show_message("저장 완료 · 25730", "success", 5000)
    fm = toast.fontMetrics()
    pill = toast.pill_rect()
    avail = pill.right() - toast.PAD_X - (pill.left() + toast.PAD_X + toast._icon_w())
    assert fm.horizontalAdvance(toast.message()) <= avail


def test_nav_fits_inside_sidebar_and_theme_name(main_window, qapp):
    """내비 목록이 사이드바보다 넓어 선택 알약 오른쪽이 잘리던 회귀 + 기본 테마 이름에 상표명 없음."""
    from PySide6.QtWidgets import QFrame

    from swea_fetcher.gui.theme import tokens

    qapp.setStyleSheet(tokens.build_qss())
    try:
        main_window.resize(960, 680)
        main_window.show()
        qapp.processEvents()
        sidebar = main_window.findChild(QFrame, "Sidebar")
        nav = main_window.nav
        assert nav.geometry().right() < sidebar.width()
        assert nav.viewport().geometry().right() < sidebar.width()
    finally:
        qapp.setStyleSheet("")
    assert all("토스" not in t.label for t in tokens.THEMES)


def test_nav_focus_ring_only_for_keyboard_focus(main_window, qtbot):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFocusEvent

    from PySide6.QtWidgets import QApplication

    nav = main_window.nav
    delegate = nav.itemDelegate()
    send = lambda t, r: QApplication.sendEvent(nav, QFocusEvent(t, r))  # noqa: E731 — 이벤트 필터를 거치게
    send(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason)
    assert delegate._kbd_focus is False
    send(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason)
    assert delegate._kbd_focus is True
    send(QEvent.Type.FocusOut, Qt.FocusReason.MouseFocusReason)
    assert delegate._kbd_focus is False
