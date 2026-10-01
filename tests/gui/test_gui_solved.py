"""GUI 풀이 잔디 (M20, offscreen): 격자·오늘 강조·툴팁·클릭 → 목록 → 문제 탭, 설정 색 저장·반영, 720px 가로 스크롤 없음, 성장 기록 꺼짐.

시간은 growth.now 를 고정한다. 네트워크·AI 호출 0 (지문 캐시에 넣어 두거나 신호만 확인).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QColorDialog

from swea_fetcher import content_cache, growth, service, solved
from swea_fetcher.gui import growth_widgets
from swea_fetcher.gui.growth_widgets import HeatLegend, HeatmapWidget
from swea_fetcher.gui.pages import settings_page as settings_page_mod
from swea_fetcher.gui.theme import tokens
from swea_fetcher.models import ProblemContent

NOW = datetime(2026, 10, 1, 12, 0, 0)  # 목요일
TODAY = NOW.date()
D1 = date(2026, 9, 30)  # 수
D2 = date(2026, 9, 29)
EMPTY_DAY = date(2026, 9, 28)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(growth, "now", lambda: NOW)


@pytest.fixture
def gw(main_window):
    main_window.resize(1300, 800)
    main_window.show()
    return main_window


def put(settings, num, at, via="swea", title=None, topic="sim"):
    assert solved.record(settings, num, topic, title if title is not None else f"문제{num}", via, at=at)


def seed(settings):
    put(settings, 101, datetime(2026, 9, 30, 9))
    put(settings, 102, datetime(2026, 9, 30, 10), via="local", topic="dp")
    put(settings, 103, datetime(2026, 9, 30, 11))
    put(settings, 104, datetime(2026, 9, 29, 9))
    put(settings, 105, datetime(2026, 10, 1, 8))


def page_of(w):
    w.goto("growth")
    return w.growth_page


def center(hm: HeatmapWidget, d: date) -> QPoint:
    return hm.cell_rect(d).center().toPoint()


# --- 격자 · 제목 -------------------------------------------------------------------------------


def test_heat_card_on_top_with_title_and_53_weeks(gw):
    seed(gw.settings)
    p = page_of(gw)
    hm = p.heatmap
    assert p.heat_card.isVisible() and p.heat_title.text() == "지난 1년간 5문제 해결"
    assert p.heat_card.mapTo(p, QPoint(0, 0)).y() < p.stack.parentWidget().mapTo(p, QPoint(0, 0)).y()  # 리포트 영역보다 위
    assert hm.visible_weeks() == 53
    first, today_rect = hm.cell_rect(hm.first_day()), hm.cell_rect(TODAY)
    assert hm.first_day().weekday() == 6 and hm.first_day() == solved.grid_start(TODAY)  # 일요일 시작
    assert first.topLeft().y() == growth_widgets.HEAT_TOP_PAD  # 첫 열 첫 행 = 일요일
    assert today_rect.left() > first.left() + 52 * 8  # 오늘은 맨 오른쪽 열
    assert today_rect.top() == first.top() + 4 * (today_rect.width() + growth_widgets.HEAT_GAP)  # 목요일 = 5번째 행
    assert hm.cell_rect(TODAY + timedelta(days=1)) is None  # 미래 칸은 없다
    assert hm.cell_rect(hm.first_day() - timedelta(days=1)) is None


def test_empty_state_shows_zero_title_and_empty_grid(gw):
    p = page_of(gw)
    assert p.heat_card.isVisible() and p.heat_title.text() == "지난 1년간 0문제 해결"
    assert p.day_list.isHidden() and not p.heat_hint.isHidden()


def test_cell_colors_follow_levels_and_today_is_outlined(gw):
    seed(gw.settings)
    p = page_of(gw)
    hm = p.heatmap
    img = hm.grab().toImage()
    cols = [QColor(c) for c in hm.level_colors()]
    assert len({c.name() for c in cols}) == 5  # 0~4단계 모두 다른 색
    assert QColor(img.pixel(center(hm, D1))).name() == cols[3].name()  # 3문제 → 3단계
    assert QColor(img.pixel(center(hm, D2))).name() == cols[1].name()
    assert QColor(img.pixel(center(hm, EMPTY_DAY))).name() == cols[0].name()  # 0칸은 surface_alt
    assert cols[0].name() == QColor(tokens.LIGHT.surface_alt).name()
    r = hm.cell_rect(TODAY)
    edge = QColor(img.pixel(int(r.left()), int(r.center().y())))
    plain = hm.cell_rect(EMPTY_DAY)
    plain_edge = QColor(img.pixel(int(plain.left()), int(plain.center().y())))
    assert edge.lightness() < plain_edge.lightness() - 40  # 오늘 칸만 진한 테두리


def test_month_and_weekday_labels_do_not_crash_and_legend_matches(gw):
    p = page_of(gw)
    leg = p.heat_legend
    assert isinstance(leg, HeatLegend) and len(leg.swatches) == 5 and leg.colors == p.heatmap.level_colors()
    assert leg.findChildren(type(leg.swatches[0]))  # 적게/많이 라벨 + 5칸
    texts = {lab.text() for lab in leg.findChildren(type(leg.swatches[0]))}
    assert {"적게", "많이"} <= texts


# --- 툴팁 · 클릭 -------------------------------------------------------------------------------


def test_tooltip_text(gw):
    seed(gw.settings)
    hm = page_of(gw).heatmap
    assert hm.tooltip_for(D1) == "2026-09-30 (수) · 3문제"
    assert hm.tooltip_for(EMPTY_DAY) == "2026-09-28 (월) · 0문제"
    assert hm.tooltip_for(TODAY) == "2026-10-01 (목) · 1문제"
    assert hm.cell_at(center(hm, D1)) == D1
    assert hm.cell_at(QPoint(1, 1)) is None  # 라벨 영역


def test_click_cell_lists_problems(gw):
    seed(gw.settings)
    p = page_of(gw)
    QTest.mouseClick(p.heatmap, Qt.MouseButton.LeftButton, pos=center(p.heatmap, D1))
    assert p.heat_selected == D1 and p.heatmap.selected == D1
    assert p.day_title.text() == "2026-09-30 (수) · 3문제" and p.day_list.isVisible()
    rows = [p.day_list.item(i).text() for i in range(p.day_list.count())]
    assert rows == ["101 · 문제101 · sim · SWEA", "102 · 문제102 · dp · 로컬", "103 · 문제103 · sim · SWEA"]


def test_click_empty_day_says_no_problems(gw):
    seed(gw.settings)
    p = page_of(gw)
    QTest.mouseClick(p.heatmap, Qt.MouseButton.LeftButton, pos=center(p.heatmap, EMPTY_DAY))
    assert "이날은 푼 문제가 없어요" in p.day_title.text() and p.day_list.isHidden()


def test_selection_survives_refresh_and_follows_new_records(gw):
    seed(gw.settings)
    p = page_of(gw)
    p._heat_day_clicked(TODAY)
    assert p.day_list.count() == 1
    put(gw.settings, 106, datetime(2026, 10, 1, 9))
    p.refresh()
    assert p.day_list.count() == 2 and p.heat_title.text() == "지난 1년간 6문제 해결"


def test_list_item_click_opens_problem_tab(gw, qtbot):
    seed(gw.settings)
    content_cache.save(gw.settings, 101, "sim", "문제101", ProblemContent(body_html="<p>잔디 지문</p>"))
    p = page_of(gw)
    p._heat_day_clicked(D1)
    with qtbot.waitSignal(p.problem_requested) as sig:
        p._day_item_clicked(p.day_list.item(0))
    assert sig.args == ["sim", 101]
    assert gw.stack.currentWidget() is gw.problem_page and "잔디 지문" in gw.problem_page.browser.toPlainText()  # MainWindow._open_recent_problem 재사용


def test_list_item_click_with_real_mouse_emits(gw, qtbot):
    seed(gw.settings)
    p = page_of(gw)
    p._heat_day_clicked(D2)
    rect = p.day_list.visualItemRect(p.day_list.item(0))
    with qtbot.waitSignal(p.problem_requested) as sig:
        QTest.mouseClick(p.day_list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert sig.args == ["sim", 104]


# --- 좁은 창 -----------------------------------------------------------------------------------


def test_no_horizontal_scroll_at_720_and_latest_weeks_visible(gw):
    seed(gw.settings)
    p = page_of(gw)
    p._heat_day_clicked(D1)
    gw.resize(720, 480)
    p.refresh()
    hm = p.heatmap
    assert p.scroll.horizontalScrollBar().maximum() == 0
    assert hm.width() <= p.scroll.viewport().width()
    assert 6 <= hm.visible_weeks() < 53  # 오래된 주부터 잘리고
    assert hm.cell_rect(TODAY) is not None and hm.cell_rect(D1) is not None  # 최신 주는 항상 보인다
    assert hm.cell_rect(TODAY).right() <= hm.width()
    assert p.heat_title.text() == "지난 1년간 5문제 해결"  # 제목은 1년 전체


# --- 설정: 색 -----------------------------------------------------------------------------------


def test_default_color_is_github_green(gw):
    p = page_of(gw)
    assert p.heat_base() == solved.DEFAULT_HEAT_COLOR == "#2DA44E"
    assert gw.settings_page.heat_buttons["#2DA44E"].isChecked()


def test_preset_saves_to_qsettings_and_applies_instantly(gw):
    seed(gw.settings)
    p = page_of(gw)
    before = p.heatmap.level_colors()
    sp = gw.settings_page
    sp.heat_buttons["#8250DF"].click()
    assert gw.qs.value("growth/heat_color") == "#8250DF"
    assert sp.heat_buttons["#8250DF"].isChecked() and not sp.heat_buttons["#2DA44E"].isChecked()
    after = p.heatmap.level_colors()  # 성장 탭이 닫혀 있어도 신호로 즉시 반영
    assert after != before and after[3] == "#8250DF" and p.heat_legend.colors == after and after[0] == before[0]


def test_custom_color_dialog(gw, monkeypatch):
    sp = gw.settings_page
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a, **k: QColor("#12AB34")))
    sp.heat_custom_btn.click()
    assert gw.qs.value("growth/heat_color") == "#12AB34" and gw.growth_page.heatmap.level_colors()[3] == "#12AB34"
    assert not any(b.isChecked() for b in sp.heat_buttons.values())
    # 직접 고른 색은 프리셋과 같은 원형 칩으로 (버튼에 색 띠를 두르지 않는다)
    assert not sp.heat_custom_swatch.isHidden() and "#12AB34" in sp.heat_custom_swatch.styleSheet()
    assert sp.heat_custom_btn.styleSheet() == ""
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a, **k: QColor()))  # 취소 = 유효하지 않은 색
    sp.heat_custom_btn.click()
    assert gw.qs.value("growth/heat_color") == "#12AB34"
    sp.heat_buttons["#2DA44E"].click()  # 프리셋으로 돌아가면 직접 고른 칩은 숨김
    assert sp.heat_custom_swatch.isHidden()


def test_invalid_saved_color_falls_back_to_default(gw):
    gw.qs.setValue("growth/heat_color", "zzz")
    assert page_of(gw).heat_base() == solved.DEFAULT_HEAT_COLOR


def test_color_survives_new_page_and_shows_in_grid(gw):
    put(gw.settings, 1, datetime(2026, 10, 1, 8))
    gw.settings_page.heat_buttons["#D6336C"].click()
    p = page_of(gw)
    img = p.heatmap.grab().toImage()
    assert QColor(img.pixel(center(p.heatmap, EMPTY_DAY))).name() == QColor(tokens.LIGHT.surface_alt).name()
    hm = p.heatmap
    lvl1 = QColor(solved.heat_colors("#D6336C", tokens.LIGHT.surface)[0])
    assert QColor(img.pixel(center(hm, D2))).name() == QColor(tokens.LIGHT.surface_alt).name()
    r = hm.cell_rect(TODAY)
    assert QColor(img.pixel(int(r.center().x()), int(r.center().y()))).name() == lvl1.name()


# --- 꺼짐 · 지우기 -----------------------------------------------------------------------------


def test_growth_off_hides_heatmap_and_records_nothing(gw):
    seed(gw.settings)
    service.set_env_values(gw.config_dir, SWEA_GROWTH="0")
    gw.reload_settings(stay=True)
    p = page_of(gw)
    assert not p.heat_card.isVisible() and p.stack.currentWidget() is p.off_state  # 기존 꺼짐 안내만
    service._record_solved(gw.settings, "sim", 999, "local")
    assert 999 not in [i.num for v in solved.load(gw.settings).values() for i in v]
    service.set_env_values(gw.config_dir, SWEA_GROWTH="1")
    gw.reload_settings(stay=True)
    assert page_of(gw).heat_card.isVisible()


def test_clear_growth_button_empties_heatmap(gw, monkeypatch):
    from tests.gui.test_gui_growth import FakeBox

    seed(gw.settings)
    p = page_of(gw)
    assert p.heat_title.text() == "지난 1년간 5문제 해결"
    monkeypatch.setattr(settings_page_mod, "QMessageBox", FakeBox)
    FakeBox.choose = "지우기"
    gw.settings_page.growth_clear_btn.click()
    p.refresh()
    assert p.heat_title.text() == "지난 1년간 0문제 해결"
    assert not (gw.config_dir / "coach" / "profile" / "solved.json").exists()
