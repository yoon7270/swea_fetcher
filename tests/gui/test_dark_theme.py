"""M22: 12 팔레트(6 테마 × 라이트·다크) 구조·대비, QSS, 모드 해석, 전환 재적용, 세그먼트·색 패널·팝업."""

from __future__ import annotations

import re

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from swea_fetcher.gui.theme import tokens
from swea_fetcher.gui.theme.qt_palette import qt_palette
from swea_fetcher.gui.widgets import AppMenu, ColorPicker, ComboBox, SegmentedControl, parse_hex_input

COMBOS = [(t, mode) for t in tokens.THEMES for mode in ("light", "dark")]
IDS = [f"{t.key}-{m}" for t, m in COMBOS]


def pal_of(theme, mode):
    return theme.dark if mode == "dark" else theme.light


def lum(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a: str, b: str) -> float:
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


# (전경 필드, 배경 필드들, 하한) — 스펙 §17.6
CONTRAST_PAIRS = [
    ("text", ("bg", "surface", "surface_alt", "bg_subtle", "primary_soft"), 7.0),
    ("text_2", ("bg", "surface", "surface_alt"), 4.5),
    ("text_3", ("bg", "surface", "surface_alt", "hover_fill"), 4.5),
    ("primary_text", ("primary_action", "primary_hover", "primary_pressed"), 4.5),
    ("primary_soft_text", ("primary_soft", "primary_soft_hover", "primary_soft_pressed"), 4.5),
    ("success_text", ("success_bg",), 4.5),
    ("warning_text", ("warning_bg",), 4.5),
    ("error_text", ("error_bg", "danger_pressed"), 4.5),
    ("secondary_text", ("secondary", "secondary_hover", "secondary_pressed"), 4.5),
    ("toast_text", ("toast_bg",), 7.0),
    ("link", ("bg_subtle", "surface"), 4.5),
    ("primary", ("surface", "bg"), 3.0),
    ("on_primary", ("primary",), 3.0),
    ("control_border", ("surface",), 3.0),
    ("error", ("surface",), 3.0),
    ("success", ("surface",), 3.0),
    ("warning", ("surface",), 3.0),
]


@pytest.mark.parametrize("theme,mode", COMBOS, ids=IDS)
def test_contrast_table(theme, mode):
    p = pal_of(theme, mode)
    fails = []
    for fg, bgs, floor in CONTRAST_PAIRS:
        for bg in bgs:
            r = ratio(getattr(p, fg), getattr(p, bg))
            if r < floor:
                fails.append(f"{theme.key}/{mode}/{fg} on {bg}: {r:.2f} < {floor}")
    assert not fails, fails


@pytest.mark.parametrize("theme,mode", COMBOS, ids=IDS)
def test_all_fields_are_hex_and_dark_flag(theme, mode):
    p = pal_of(theme, mode)
    for name, value in vars(p).items():
        if name == "is_dark":
            assert value is (mode == "dark")
        else:
            assert re.fullmatch(r"#[0-9A-F]{6}", value), (theme.key, mode, name, value)


@pytest.mark.parametrize("theme", tokens.THEMES, ids=lambda t: t.key)
def test_dark_layers_are_monotonic(theme):
    d, li = theme.dark, theme.light
    assert lum(d.bg) < lum(li.bg)
    assert lum(d.bg) < lum(d.sidebar) < lum(d.surface) < lum(d.surface_alt)
    assert lum(d.surface) <= lum(d.bg_subtle) <= lum(d.surface_alt)


def test_current_follows_theme_and_mode():
    tokens.set_theme("green")
    tokens.set_color_mode("dark")
    assert tokens.current() is tokens.get_theme("green").dark and tokens.is_dark()
    tokens.set_color_mode("light")
    assert tokens.current() is tokens.get_theme("green").light
    tokens.set_color_mode("system")
    tokens.set_system_dark(True)
    assert tokens.is_dark() and tokens.current().is_dark
    tokens.set_system_dark(False)
    assert not tokens.is_dark()
    assert tokens.set_color_mode("엉뚱") == "system"
    assert tokens.LIGHT is tokens.get_theme("blue").light and tokens.DARK is tokens.get_theme("blue").dark


def test_version_bumps_only_on_real_change():
    v = tokens.version()
    tokens.set_theme(tokens.current_theme_key())
    tokens.set_color_mode(tokens.color_mode())
    tokens.set_system_dark(False)
    assert tokens.version() == v
    tokens.set_theme("rose")
    assert tokens.version() == v + 1
    tokens.set_color_mode("dark")
    tokens.set_system_dark(True)
    assert tokens.version() == v + 3


@pytest.mark.parametrize("theme,mode", COMBOS, ids=IDS)
def test_qss_builds_without_leaks(theme, mode, tmp_path):
    p = pal_of(theme, mode)
    qss = tokens.build_qss(p, icon_dir=tmp_path)
    assert "None" not in qss and "{p." not in qss and "{{" not in qss
    allowed = {v.upper() for v in vars(p).values() if isinstance(v, str)}
    used = {m.upper() for m in re.findall(r"#[0-9A-Fa-f]{6}\b", qss)}
    assert used <= allowed, used - allowed
    if mode == "dark":  # 라이트 전용 값이 다크 QSS 에 새지 않는다
        assert theme.light.bg.upper() not in qss.upper() or theme.light.bg.upper() in allowed
    assert p.sidebar in qss and p.hover_fill in qss and "QMenu::item:selected" in qss


@pytest.mark.parametrize("theme,mode", COMBOS, ids=IDS)
def test_recolored_check_icon_uses_on_primary(theme, mode, tmp_path):
    p = pal_of(theme, mode)
    tokens.build_qss(p, icon_dir=tmp_path)
    svgs = [f.read_text(encoding="utf-8") for f in tmp_path.glob("check-white-*.svg")]
    assert svgs and p.on_primary in svgs[0]


def test_qt_palette_roles():
    p = tokens.get_theme("blue").dark
    pal = qt_palette(p)
    from PySide6.QtGui import QPalette

    R = QPalette.ColorRole
    assert pal.color(R.Window) == QColor(p.bg) and pal.color(R.Base) == QColor(p.surface)
    assert pal.color(R.Highlight) == QColor(p.primary) and pal.color(R.HighlightedText) == QColor(p.on_primary)
    assert pal.color(R.ToolTipBase) == QColor(p.toast_bg) and pal.color(R.Link) == QColor(p.link)
    assert pal.color(QPalette.ColorGroup.Disabled, R.Text) == QColor(p.text_disabled)


# --- 전환 재적용 -------------------------------------------------------------------------------


def test_apply_appearance_roundtrip(main_window, qapp):
    w = main_window
    font_before = qapp.font().toString()
    w.apply_appearance("dark", "green")
    dark = tokens.get_theme("green").dark
    assert qapp.styleSheet() == tokens.build_qss(dark) and tokens.current() is dark
    assert qapp.palette().color(qapp.palette().ColorRole.Window) == QColor(dark.bg)
    assert str(w.qs.value("ui/color_mode")) == "dark" and str(w.qs.value("ui/theme")) == "green"
    w.apply_appearance("light", None)
    light = tokens.get_theme("green").light
    assert qapp.styleSheet() == tokens.build_qss(light)
    assert qapp.font().toString() == font_before  # 앱 기본 글꼴(힌팅 끔)은 전환이 덮어쓰지 않는다
    qapp.setStyleSheet("")


def test_appearance_recolors_document_table_and_diff(main_window, qapp):
    w = main_window
    cp = w.check_page
    cp.diff.set_rows([("same", "a", "a"), ("changed", "b", "c")])
    w.apply_appearance("dark", "blue")
    d = tokens.get_theme("blue").dark
    assert cp.diff.item(1, 0).background().color() == QColor(d.diff_changed)
    assert cp.diff.item(1, 2).foreground().color() == QColor(d.warning_text)
    for pane in cp.coach_tab.findChildren(type(cp.coach_tab.pane("codex").browser)):
        assert d.text in pane.document().defaultStyleSheet()
    w.apply_appearance("light", None)
    assert cp.diff.item(1, 0).background().color() == QColor(tokens.get_theme("blue").light.diff_changed)
    qapp.setStyleSheet("")


def test_log_view_rerenders_with_class_colors(main_window):
    w = main_window
    log = w.fetch_page.log
    log.append("정상 줄")
    log.append("오류 줄", error=True)
    w.apply_appearance("dark", "blue")
    assert tokens.get_theme("blue").dark.error_text in log.text.document().defaultStyleSheet()
    assert "정상 줄" in log.text.toPlainText() and "오류 줄" in log.text.toPlainText()


def test_dark_statement_images_get_paper(qtbot):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage

    from swea_fetcher.gui.pages.problem_page import _StatementBrowser
    from swea_fetcher.models import ImageRef, ProblemContent

    img = QImage(10, 10, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    b = _StatementBrowser()
    qtbot.addWidget(b)
    b.set_statement(ProblemContent("", '<p>x</p><img src="swea-img:0"/>', {"swea-img:0": ImageRef(data=bytes(buf.data()))}))
    assert "<table" not in b.document().toHtml()
    tokens.set_color_mode("dark")
    b.refresh_theme()
    assert "<table" in b.document().toHtml()  # 종이 표로 감쌌다
    assert tokens.current().text in b.document().defaultStyleSheet()


# --- 세그먼트 ----------------------------------------------------------------------------------


def test_segmented_control_keyboard_and_signal(qtbot):
    seg = SegmentedControl()
    qtbot.addWidget(seg)
    seg.resize(420, 44)
    seg.show()
    seen: list[str] = []
    seg.selected_changed.connect(seen.append)
    assert seg.value() == "system"
    seg.setFocus()
    QTest.keyClick(seg, Qt.Key.Key_Left)
    QTest.keyClick(seg, Qt.Key.Key_Left)
    QTest.keyClick(seg, Qt.Key.Key_Left)  # 끝에서 멈춘다
    assert seen == ["dark", "light"] and seg.value() == "light"
    QTest.keyClick(seg, Qt.Key.Key_End)
    assert seg.value() == "system"
    seg.set_value("dark")  # 신호 없이 표시만
    assert seg.value() == "dark" and seen[-1] == "system"
    assert "선택됨" in seg.buttons["dark"].accessibleName()
    qtbot.mouseClick(seg.buttons["light"], Qt.MouseButton.LeftButton)
    assert seg.value() == "light" and seen[-1] == "light"


def test_settings_mode_segment_applies_instantly(main_window, qapp):
    w = main_window
    sp = w.settings_page
    assert sp.mode_seg.value() == "light"
    sp.mode_seg.buttons["dark"].click()
    assert tokens.is_dark() and str(w.qs.value("ui/color_mode")) == "dark"
    assert qapp.styleSheet() == tokens.build_qss()
    sp.theme_chips["rose"].click()
    assert tokens.current() is tokens.get_theme("rose").dark
    qapp.setStyleSheet("")


# --- 색 선택 패널 ------------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [("#2da44e", "#2DA44E"), ("abc", "#AABBCC"), ("#abc", "#AABBCC"), (" 12AB34 ", "#12AB34"), ("#12AB3", None), ("zzzzzz", None), ("", None)])
def test_parse_hex_input(text, expected):
    assert parse_hex_input(text) == expected


def test_color_picker_hex_enter_commits_and_invalid_shows_error(qtbot):
    cp = ColorPicker()
    qtbot.addWidget(cp)
    cp.show()
    got: list[str] = []
    cp.color_committed.connect(got.append)
    cp.hex_edit.setText("#8250df")
    QTest.keyClick(cp.hex_edit, Qt.Key.Key_Return)
    assert got == ["#8250DF"] and cp.color() == "#8250DF" and cp.error.isHidden()
    cp.hex_edit.setText("12")
    QTest.keyClick(cp.hex_edit, Qt.Key.Key_Return)
    assert got == ["#8250DF"] and not cp.error.isHidden() and cp.hex_edit.property("state") == "invalid"
    cp.set_color("#112233")
    assert cp.hex_edit.text() == "#112233" and cp.error.isHidden()


def test_color_picker_mouse_and_keyboard(qtbot):
    cp = ColorPicker()
    qtbot.addWidget(cp)
    cp.resize(360, 420)
    cp.show()
    got: list[str] = []
    cp.color_committed.connect(got.append)
    sv = cp.sv
    QTest.mouseClick(sv, Qt.MouseButton.LeftButton, pos=QPoint(sv.width() - 1, 0))  # 오른쪽 위 = 채도·명도 최대
    assert got and QColor(got[-1]).saturationF() > 0.95 and QColor(got[-1]).valueF() > 0.95
    n = len(got)
    cp.hue.setFocus()
    QTest.keyClick(cp.hue, Qt.Key.Key_Right)
    assert len(got) == n  # 키보드 이동은 디바운스
    qtbot.waitUntil(lambda: len(got) == n + 1, timeout=2000)


def test_no_qcolordialog_in_gui_source():
    from pathlib import Path

    import swea_fetcher.gui as g

    for f in Path(g.__file__).parent.rglob("*.py"):
        assert "QColorDialog" not in f.read_text(encoding="utf-8"), f


# --- 팝업·메뉴 가장자리 --------------------------------------------------------------------------


@pytest.mark.parametrize("theme,mode", [(tokens.get_theme(k), m) for k in ("blue", "green", "mono") for m in ("light", "dark")], ids=lambda x: getattr(x, "key", x))
def test_combo_popup_and_menu_are_translucent_and_surface(qapp, qtbot, theme, mode):
    tokens.set_theme(theme.key)
    tokens.set_color_mode(mode)
    qapp.setPalette(qt_palette(tokens.current()))
    qapp.setStyleSheet(tokens.build_qss())
    try:
        cb = ComboBox()
        qtbot.addWidget(cb)
        cb.addItems(["a", "b", "c"])
        win = cb.view().window()
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert win.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert not cb.view().viewport().autoFillBackground()
        m = AppMenu()
        qtbot.addWidget(m)
        m.addAction("x")
        assert m.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    finally:
        qapp.setStyleSheet("")


# --- 상태 칩 델리게이트 ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_status_delegate_paints_chip_and_band(qtbot, mode):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionViewItem

    from swea_fetcher.gui.pages import history_page as hp

    tokens.set_color_mode(mode)
    p = tokens.current()
    page = hp.HistoryPage()
    qtbot.addWidget(page)
    table = page.table
    table.setRowCount(5)
    keys = ["pass", "wrong", "timeout", "runtime_error", "none"]
    for r, k in enumerate(keys):
        item = hp.QTableWidgetItem(k)
        item.setData(hp.ROLE_STATUS, k)
        table.setItem(r, 0, item)
    expect = {"pass": (p.success_bg, p.success), "wrong": (p.error_bg, p.error), "timeout": (p.warning_bg, p.warning),
              "runtime_error": (p.error_bg, p.error), "none": (p.surface_alt, None)}
    for r, k in enumerate(keys):
        img = QImage(128, 36, QImage.Format.Format_ARGB32)
        img.fill(QColor(p.surface))
        painter = QPainter(img)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 128, 36)
        opt.widget = table
        opt.font = table.font()
        page._delegate.paint(painter, opt, table.model().index(r, 0))
        painter.end()
        chip_bg, band = expect[k]
        assert QColor(img.pixel(21, 18)).name().upper() == chip_bg.upper(), (mode, k)  # 칩 왼쪽 안쪽 면
        if band:
            assert QColor(img.pixel(9, 18)).name().upper() == band.upper(), (mode, k)  # 왼쪽 띠
        else:
            assert QColor(img.pixel(9, 18)).name().upper() == p.surface.upper()


def test_history_fill_status_summary_and_tooltip(main_window):
    from types import SimpleNamespace

    from swea_fetcher import coach

    w = main_window
    d = w.settings.root / "sim" / "42"
    d.mkdir(parents=True)
    (d / "42.py").write_text("# 42. 제목\n", encoding="utf-8")
    coach.record_submit(w.settings, 42, "sim", "제목", SimpleNamespace(passed=False, summary="오답", run_error="", timed_out=False))
    hp = w.history_page
    hp.refresh()
    it = hp.table.item(0, 0)
    assert it.text() == "오답" and it.data(Qt.ItemDataRole.UserRole + 1) == "wrong"
    assert "42번" in it.toolTip() and "오답" in it.toolTip()
    assert hp.count_label.text() == "오답 1" and not hp.count_label.isHidden()
    hp.table.resize(600, 300)
    hp._apply_topic_visibility()
    assert hp.table.isColumnHidden(3)
    hp.table.resize(900, 300)
    hp._apply_topic_visibility()
    assert not hp.table.isColumnHidden(3)


# --- 흰 면 누수 휴리스틱 · 잔디 숨김 토글 ---------------------------------------------------------


def _bright_ratio(img) -> float:
    n = bright = 0
    step = 3
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            c = QColor(img.pixel(x, y))
            n += 1
            if 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF() > 0.60:
                bright += 1
    return bright / max(n, 1)


@pytest.mark.parametrize("theme", tokens.THEMES, ids=lambda t: t.key)
def test_dark_pages_have_no_large_white_surfaces(main_window, qapp, theme):
    """다크 팔레트에서 각 페이지의 밝은(휘도 > 0.60) 픽셀 비율이 작다 — 글자·아이콘을 넘는 큰 흰 사각형(라이트 잔존) 탐지."""
    w = main_window
    w.resize(960, 680)
    w.apply_appearance("dark", theme.key)
    try:
        for key in ("fetch", "problem", "check", "history", "growth", "settings"):
            w.goto(key)
            qapp.processEvents()
            ratio = _bright_ratio(w.grab().toImage())
            assert ratio < 0.12, (theme.key, key, round(ratio, 3))
    finally:
        qapp.setStyleSheet("")


def test_heat_sync_row_is_hidden_until_feature_exists(main_window):
    sp = main_window.settings_page
    assert sp.heat_sync_row.isHidden() and sp.heat_sync.objectName() == "HeatSyncToggle"
