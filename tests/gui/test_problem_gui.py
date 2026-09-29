"""문제 탭 GUI (M12, offscreen). 네트워크 경계(service.fetch_problem)는 스텁, 지문은 픽스처에서 파싱."""

from __future__ import annotations

import base64
import dataclasses
from pathlib import Path

import pytest

from swea_fetcher.opener import OpenResult
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextDocument

from swea_fetcher import content_cache, parser, service
from swea_fetcher.gui.main_window import PAGES
from swea_fetcher.models import ImageRef, ProblemContent, SaveResult
from swea_fetcher.service import FetchOutcome

WAIT = 5000
IMG = QTextDocument.ResourceType.ImageResource


def _png_bytes(w: int = 40, h: int = 20) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(0xFF3366CC)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


@pytest.fixture
def content(solver_html) -> ProblemContent:
    return parser.parse_content(solver_html)


def _outcome(root: Path, info, content, saved: bool = True) -> FetchOutcome:
    if not saved:
        return FetchOutcome(info, None, {"problem_dir": root / "sim" / "25730", "files": [], "needs_force": False}, [], "sim", content)
    d = root / "sim" / "25730"
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for name in ("input.txt", "output.txt", "25730.py"):
        (d / name).write_text("x", encoding="utf-8")
        files.append(d / name)
    return FetchOutcome(info, SaveResult(d, files, []), None, [], "sim", content)


def _run_fetch(w, qtbot, monkeypatch, outcome, dry_run=False):
    fp = w.fetch_page
    monkeypatch.setattr(service, "fetch_problem", lambda settings, target, topic, opts, progress: outcome)
    fp.target.setText("25730")
    fp.topic.setCurrentText("sim")
    with qtbot.waitSignal(fp.problem_ready, timeout=WAIT):
        fp.start(dry_run=dry_run)
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)


# --- 내비 ------------------------------------------------------------------------


def test_nav_order_and_ctrl2_opens_problem_tab(main_window):
    w = main_window
    assert [k for _l, k, _i in PAGES] == ["fetch", "problem", "check", "history", "settings"]
    w.nav.setCurrentRow(3)
    from PySide6.QtGui import QShortcut

    sc = [s for s in w.findChildren(QShortcut) if s.key().toString() == "Ctrl+2"]
    assert sc
    sc[0].activated.emit()
    assert w.stack.currentWidget() is w.problem_page


def test_last_page_saved_by_key_and_restored(qtbot, valid_config):
    from swea_fetcher.gui.main_window import MainWindow

    w = MainWindow(config_dir=valid_config)
    qtbot.addWidget(w)
    w.goto("history")
    assert w.qs.value("window/last_page_key", type=str) == "history"
    w.qs.sync()
    w2 = MainWindow(config_dir=valid_config)
    qtbot.addWidget(w2)
    assert w2.stack.currentWidget() is w2.history_page


def test_old_row_based_last_page_is_ignored(qtbot, valid_config):
    from PySide6.QtCore import QSettings
    from swea_fetcher.gui import main_window

    qs = main_window.QSettings("swea-fetch", "gui")
    qs.setValue("window/last_page", 3)  # 옛 형식 (행 번호)
    qs.sync()
    w = main_window.MainWindow(config_dir=valid_config)
    qtbot.addWidget(w)
    assert w.stack.currentWidget() is w.fetch_page


# --- 자동 전환 -------------------------------------------------------------------


def test_save_success_switches_to_problem_tab_and_shows_statement(main_window, qtbot, monkeypatch, problem_info, content):
    w = main_window
    _run_fetch(w, qtbot, monkeypatch, _outcome(w.settings.root, problem_info, content))
    assert w.stack.currentWidget() is w.problem_page
    pp = w.problem_page
    text = pp.browser.toPlainText()
    assert "플레이어는 1번 구역에서 출발" in text and "256MB" in text
    assert "25730. 항아리 게임" in pp.title.text()
    assert pp.badge.text() == "저장됨"
    assert pp.open_dir_btn.isVisibleTo(pp) and pp.open_py_btn.isVisibleTo(pp)
    assert pp.browser.hasFocus() or pp.browser.isVisibleTo(pp)


def test_toggle_off_does_not_switch(main_window, qtbot, monkeypatch, problem_info, content):
    w = main_window
    w.qs.setValue("fetch/auto_open_problem", False)
    _run_fetch(w, qtbot, monkeypatch, _outcome(w.settings.root, problem_info, content))
    assert w.stack.currentWidget() is w.fetch_page
    assert "플레이어는" in w.problem_page.browser.toPlainText()  # 내용은 로드됨


def test_dry_run_loads_without_switching_and_offers_view_button(main_window, qtbot, monkeypatch, problem_info, content):
    w = main_window
    _run_fetch(w, qtbot, monkeypatch, _outcome(w.settings.root, problem_info, content, saved=False), dry_run=True)
    assert w.stack.currentWidget() is w.fetch_page
    pp = w.problem_page
    assert pp.badge.text().startswith("미리보기") and not pp.open_dir_btn.isVisibleTo(pp)
    fp = w.fetch_page
    assert fp.view_btn.isVisibleTo(fp)
    fp.view_btn.click()
    assert w.stack.currentWidget() is pp


def test_failure_keeps_previous_statement(main_window, qtbot, monkeypatch, problem_info, content):
    w = main_window
    _run_fetch(w, qtbot, monkeypatch, _outcome(w.settings.root, problem_info, content))
    w.goto("fetch")
    from swea_fetcher.errors import NetworkError

    def boom(*a, **k):
        raise NetworkError("네트워크 오류")

    monkeypatch.setattr(service, "fetch_problem", boom)
    w.fetch_page.start(dry_run=False)
    qtbot.waitUntil(lambda: w.fetch_page._worker is None, timeout=WAIT)
    assert w.stack.currentWidget() is w.fetch_page
    assert "플레이어는" in w.problem_page.browser.toPlainText()


def test_fetch_page_requests_content_and_cache_options(main_window, qtbot, monkeypatch, problem_info, content):
    w = main_window
    seen = {}

    def fake(settings, target, topic, opts, progress):
        seen["opts"] = opts
        return _outcome(settings.root, problem_info, content)

    monkeypatch.setattr(service, "fetch_problem", fake)
    w.fetch_page.target.setText("25730")
    w.fetch_page.topic.setCurrentText("sim")
    with qtbot.waitSignal(w.fetch_page.problem_ready, timeout=WAIT):
        w.fetch_page.start(dry_run=False)
    assert seen["opts"].with_content is True and seen["opts"].cache_content is True  # 캐시 기본 ON
    qtbot.waitUntil(lambda: w.fetch_page._worker is None, timeout=WAIT)
    w.qs.setValue("problem/cache_enabled", False)
    w.goto("fetch")
    with qtbot.waitSignal(w.fetch_page.problem_ready, timeout=WAIT):
        w.fetch_page.start(dry_run=False)
    assert seen["opts"].cache_content is False


def test_no_content_outcome_does_not_emit_problem_ready(main_window, qtbot, monkeypatch, problem_info):
    w = main_window
    monkeypatch.setattr(service, "fetch_problem", lambda s, t, tp, o, p: _outcome(s.root, problem_info, None))
    w.fetch_page.target.setText("25730")
    w.fetch_page.topic.setCurrentText("sim")
    with qtbot.assertNotEmitted(w.fetch_page.problem_ready):
        with qtbot.waitSignal(w.fetch_page.saved, timeout=WAIT):
            w.fetch_page.start(dry_run=False)
        qtbot.waitUntil(lambda: w.fetch_page._worker is None, timeout=WAIT)
    assert w.stack.currentWidget() is w.fetch_page


# --- 문제 페이지 ------------------------------------------------------------------


def test_empty_state(main_window):
    pp = main_window.problem_page
    assert not pp.has_content()
    assert pp.empty.button is not None
    assert "아직 가져온 문제가 없습니다" in [c.text() for c in pp.empty.findChildren(type(pp.title))][0]


def test_missing_content_shows_warning_banner(main_window, problem_info):
    pp = main_window.problem_page
    pp.show_outcome(_outcome(main_window.settings.root, problem_info, None))
    assert pp.banner.isVisibleTo(pp) and "지문 영역을 찾지 못했습니다" in pp.banner.title.text()
    keys = []
    pp.goto_requested.connect(keys.append)
    pp.banner._buttons[0].click()
    assert keys == ["fetch"]


def test_browser_blocks_all_external_resources(main_window):
    b = main_window.problem_page.browser
    for u in ("http://example.com/a.png", "https://swexpertacademy.com/a.png", "file:///C:/Windows/win.ini", "qrc:/x.png", "swea-img:0"):
        assert b.loadResource(IMG, QUrl(u)) is None
        assert b.loadResource(QTextDocument.ResourceType.HtmlResource, QUrl(u)) is None
    assert b.openLinks() is False and b.openExternalLinks() is False and b.isReadOnly()


def test_images_registered_and_failures_shown(main_window, problem_info):
    pp = main_window.problem_page
    good, bad_data = _png_bytes(), b"not an image"
    c = ProblemContent(
        body_html='<p>본문</p><img src="swea-img:0"/><img src="swea-img:1"/><img src="swea-img:2"/>',
        images={
            "swea-img:0": ImageRef(data=good, alt="그림"),
            "swea-img:1": ImageRef(data=bad_data, alt="깨짐"),
            "swea-img:2": ImageRef(url="https://swexpertacademy.com/x.png", error="다운로드 실패: 404"),
        },
    )
    pp.show_outcome(_outcome(main_window.settings.root, problem_info, c))
    doc = pp.browser.document()
    assert doc.resource(IMG, QUrl("swea-img:0")) is not None
    assert doc.resource(IMG, QUrl("swea-img:1")) is None
    text = pp.browser.toPlainText()
    assert "이미지 불러오기 실패: 다운로드 실패: 404" in text and "이미지 불러오기 실패: 이미지 디코드 실패" in text
    assert pp.banner.isVisibleTo(pp) and "이미지 2개를 불러오지 못했습니다" in pp.banner.title.text()


def test_wide_image_is_scaled_to_viewport(main_window, problem_info):
    pp = main_window.problem_page
    pp.resize(600, 500)
    pp.show()
    big = _png_bytes(2000, 50)
    c = ProblemContent(body_html='<img src="swea-img:0"/>', images={"swea-img:0": ImageRef(data=big)})
    pp.show_outcome(_outcome(main_window.settings.root, problem_info, c))
    assert f'width="{2000}"' not in pp.browser.toHtml()
    assert pp.browser.document().size().width() <= pp.browser.viewport().width() + 4


def test_zoom_persists_and_changes_layout(main_window, problem_info, content):
    main_window.show()  # 레이아웃이 계산되려면 보여야 한다
    main_window.goto("problem")
    pp = main_window.problem_page
    pp.show_outcome(_outcome(main_window.settings.root, problem_info, content))
    h0 = pp.browser.document().size().height()
    assert h0 > 0
    pp.zoom_in_btn.click()
    pp.zoom_in_btn.click()
    assert pp.browser.document().size().height() > h0
    assert int(pp.qs.value("problem/zoom", 0, type=int)) == 2


def test_statement_css_uses_only_palette_tokens():
    from swea_fetcher.gui.theme import tokens

    css = tokens.build_statement_css(tokens.LIGHT)
    assert tokens.LIGHT.border in css and tokens.LIGHT.surface_alt in css
    import re

    hexes = {h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}", css)}
    palette = {v.upper() for v in dataclasses.asdict(tokens.LIGHT).values() if isinstance(v, str) and v.startswith("#")}
    assert hexes <= palette


# --- 캐시 (P1) ---------------------------------------------------------------------


def test_history_context_menu_view_enabled_only_when_cached(main_window, problem_info, content, monkeypatch):
    w = main_window
    settings = w.settings
    content_cache.save(settings, 25730, "sim", "항아리 게임", content)
    w.history_page.problem_requested.emit("sim", 25730)
    assert w.stack.currentWidget() is w.problem_page
    assert w.problem_page.badge.text() == "캐시" and "플레이어는" in w.problem_page.browser.toPlainText()
    assert not w.problem_page.open_dir_btn.isVisibleTo(w.problem_page)


def test_view_missing_cache_stays_and_flashes(main_window):
    w = main_window
    w.history_page.problem_requested.emit("sim", 999)
    assert w.stack.currentWidget() is w.fetch_page
    assert "저장된 지문이 없습니다" in w.statusBar().currentMessage()


def test_conflict_banner_offers_view_when_cached(main_window, qtbot, monkeypatch, content):
    from swea_fetcher.errors import AlreadyExists

    w = main_window
    content_cache.save(w.settings, 25730, "sim", "항아리 게임", content)

    def boom(*a, **k):
        raise AlreadyExists("이미 저장된 파일이 있습니다: x", existing=[Path("x")])

    monkeypatch.setattr(service, "fetch_problem", boom)
    fp = w.fetch_page
    fp.target.setText("25730")
    fp.topic.setCurrentText("sim")
    fp.start(dry_run=False)
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)
    labels = [b.text() for b in fp.banner._buttons]
    assert labels == ["문제 보기", "덮어쓰고 다시 저장"]
    fp.banner._buttons[0].click()
    assert w.stack.currentWidget() is w.problem_page and w.problem_page.badge.text() == "캐시"


def test_conflict_banner_has_no_view_when_cache_off(main_window, qtbot, monkeypatch, content):
    from swea_fetcher.errors import AlreadyExists

    w = main_window
    content_cache.save(w.settings, 25730, "sim", "항아리 게임", content)
    w.qs.setValue("problem/cache_enabled", False)
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: (_ for _ in ()).throw(AlreadyExists("이미 저장된 파일이 있습니다: x", existing=[Path("x")])))
    fp = w.fetch_page
    fp.target.setText("25730")
    fp.topic.setCurrentText("sim")
    fp.start(dry_run=False)
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)
    assert [b.text() for b in fp.banner._buttons] == ["덮어쓰고 다시 저장"]


def _conflict_in_saved_dir(w, qtbot, monkeypatch, target="25730", with_py=True):
    """sim/25730 에 저장된 문제가 있는 상태에서 다시 저장 → 충돌 배너."""
    from swea_fetcher.errors import AlreadyExists

    d = w.settings.root / "sim" / "25730"
    d.mkdir(parents=True)
    (d / "input.txt").write_text("1\n", encoding="utf-8")
    if with_py:
        (d / "25730.py").write_text("", encoding="utf-8")
    msg = f"이미 저장된 파일이 있습니다: {d / 'input.txt'} (덮어쓰려면 --force)"
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: (_ for _ in ()).throw(AlreadyExists(msg, existing=[d / "input.txt"])))
    fp = w.fetch_page
    fp.target.setText(target)
    fp.topic.setCurrentText("sim")
    fp.start(dry_run=False)
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)
    return fp, d


def test_conflict_banner_offers_editor(main_window, qtbot, monkeypatch, content):
    from swea_fetcher.gui.pages import fetch_page as fp_mod

    opened = []
    monkeypatch.setattr(fp_mod, "open_in_editor", lambda d, py, setting: opened.append((d, py)) or OpenResult(True, "vscode"))
    content_cache.save(main_window.settings, 25730, "sim", "항아리 게임", content)
    fp, d = _conflict_in_saved_dir(main_window, qtbot, monkeypatch)
    assert [b.text() for b in fp.banner._buttons] == ["에디터에서 열기", "문제 보기", "덮어쓰고 다시 저장"]
    fp.banner._buttons[0].click()
    assert opened == [(d.resolve(), d.resolve() / "25730.py")]


def test_conflict_banner_url_input_uses_path_from_message(main_window, qtbot, monkeypatch):
    fp, d = _conflict_in_saved_dir(main_window, qtbot, monkeypatch, target="AV140YnqAIECFAYD")
    assert fp._existing_dir == d
    assert [b.text() for b in fp.banner._buttons][0] == "에디터에서 열기"


def test_conflict_banner_no_editor_without_py(main_window, qtbot, monkeypatch):
    fp, _d = _conflict_in_saved_dir(main_window, qtbot, monkeypatch, with_py=False)
    assert [b.text() for b in fp.banner._buttons] == ["덮어쓰고 다시 저장"]


# --- 설정 --------------------------------------------------------------------------


def test_settings_toggles_persist_and_clear_cache(main_window, content):
    w = main_window
    sp = w.settings_page
    assert sp.auto_open_problem.isChecked() and sp.cache_enabled.isChecked()  # 기본값 ON
    sp.auto_open_problem.setChecked(False)
    sp.cache_enabled.setChecked(False)
    assert w.qs.value("fetch/auto_open_problem", True, type=bool) is False
    assert w.qs.value("problem/cache_enabled", True, type=bool) is False
    content_cache.save(w.settings, 1, "t", "x", content)
    assert content_cache.has(w.settings, 1)
    sp.cache_clear_btn.click()
    assert not content_cache.has(w.settings, 1)
    assert "지문 캐시를 지웠습니다" in sp.banner.title.text()
