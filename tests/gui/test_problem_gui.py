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
    assert [k for _l, k, _i in PAGES] == ["fetch", "problem", "check", "history", "growth", "settings"]
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
    assert "아직 연 문제가 없습니다" in [c.text() for c in pp.empty.findChildren(type(pp.title))][0]
    keys = []
    pp.goto_requested.connect(keys.append)
    pp.empty.button.click()
    assert keys == ["history"]


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


def _statement_outcome(problem_info, content, topic="sim"):
    return service.FetchOutcome(problem_info, None, {}, [], topic, content)


def test_recent_view_without_cache_fetches_statement_only(main_window, qtbot, monkeypatch, problem_info, content):
    """캐시에 없으면 지문만 가져온다: dry_run + skeleton_only (저장·첨부 없음), 결과는 캐시에 기록 후 문제 탭."""
    w = main_window
    d = w.settings.root / "sim" / str(problem_info.num)
    d.mkdir(parents=True)
    (d / f"{problem_info.num}.py").write_text("", encoding="utf-8")
    calls = []

    def fake(settings, target, topic, opts, progress):
        calls.append((target, topic, opts))
        return _statement_outcome(problem_info, content)

    monkeypatch.setattr(service, "fetch_problem", fake)
    w.history_page.problem_requested.emit("sim", problem_info.num)
    qtbot.waitUntil(lambda: w._stmt_worker is None, timeout=WAIT)
    (target, topic, opts), = calls
    assert target == str(problem_info.num) and topic == "sim"
    assert opts.dry_run and opts.skeleton_only and opts.with_content and not opts.force
    assert w.stack.currentWidget() is w.problem_page and w.problem_page.badge.text() == "최신"
    assert content_cache.has(w.settings, problem_info.num)
    assert not w.problem_page.open_py_btn.isHidden() and not w.problem_page.open_dir_btn.isHidden()
    assert sorted(p.name for p in d.iterdir()) == [f"{problem_info.num}.py"]  # 폴더에 아무것도 안 씀


def test_recent_view_cached_skips_network(main_window, qtbot, monkeypatch, content):
    w = main_window
    content_cache.save(w.settings, 25730, "sim", "항아리 게임", content)
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: pytest.fail("캐시가 있으면 네트워크를 쓰지 않아야 함"))
    w.history_page.problem_requested.emit("sim", 25730)
    assert w._stmt_worker is None
    assert w.stack.currentWidget() is w.problem_page and w.problem_page.badge.text() == "캐시"
    assert w.problem_page.open_py_btn.isHidden()  # 폴더가 없으면 열기 버튼 숨김


def test_recent_view_fetch_failure_flashes_and_stays(main_window, qtbot, monkeypatch):
    from swea_fetcher.errors import NetworkError

    w = main_window
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: (_ for _ in ()).throw(NetworkError("네트워크 오류")))
    w.history_page.problem_requested.emit("sim", 999)
    qtbot.waitUntil(lambda: w._stmt_worker is None, timeout=WAIT)
    assert w.stack.currentWidget() is w.fetch_page
    assert "지문을 가져오지 못했습니다" in w.statusBar().currentMessage()


def test_recent_view_cache_off_does_not_write(main_window, qtbot, monkeypatch, problem_info, content):
    w = main_window
    w.qs.setValue("problem/cache_enabled", False)
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: _statement_outcome(problem_info, content))
    w.history_page.problem_requested.emit("sim", problem_info.num)
    qtbot.waitUntil(lambda: w._stmt_worker is None, timeout=WAIT)
    assert w.stack.currentWidget() is w.problem_page
    assert not content_cache.has(w.settings, problem_info.num)


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


def test_conflict_banner_view_shows_samples_with_folder(main_window, qtbot, monkeypatch, content):
    """충돌 배너 [문제 보기] 도 폴더를 넘겨 지문 아래 입력 | 출력과 폴더/에디터 버튼이 나온다."""
    content_cache.save(main_window.settings, 25730, "sim", "항아리 게임", content)
    fp, d = _conflict_in_saved_dir(main_window, qtbot, monkeypatch)
    (d / "output.txt").write_text("#1 7\n", encoding="utf-8")
    view = next(b for b in fp.banner._buttons if b.text() == "문제 보기")
    view.click()
    pp = main_window.problem_page
    assert main_window.stack.currentWidget() is pp
    assert pp._problem_dir is not None and pp._problem_dir.name == "25730"
    assert "#1 7" in pp.browser.toPlainText() and not pp.open_py_btn.isHidden()


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


# --- 지문 아래 입력 | 출력 (M15) ---------------------------------------------------------


def test_read_sample_truncates_lines_and_bytes(tmp_path):
    from swea_fetcher.gui.pages.problem_page import SAMPLE_MAX_BYTES, SAMPLE_MAX_LINES, read_sample

    assert read_sample(tmp_path / "none.txt") is None
    (tmp_path / "empty.txt").write_text("\n\n", encoding="utf-8")
    assert read_sample(tmp_path / "empty.txt") is None
    (tmp_path / "short.txt").write_bytes("3\r\n1 2\r\n".encode("cp949"))
    assert read_sample(tmp_path / "short.txt") == ("3\n1 2", 0)
    (tmp_path / "long.txt").write_text("\n".join(str(i) for i in range(100)) + "\n", encoding="utf-8")
    text, hidden = read_sample(tmp_path / "long.txt")
    assert text.split("\n") == [str(i) for i in range(SAMPLE_MAX_LINES)] and hidden == 100 - SAMPLE_MAX_LINES
    (tmp_path / "huge.txt").write_text("1 2 3 4 5 6 7\n" * (SAMPLE_MAX_BYTES // 10), encoding="utf-8")
    text, hidden = read_sample(tmp_path / "huge.txt")
    assert len(text.split("\n")) == SAMPLE_MAX_LINES and hidden > 0


def test_problem_tab_shows_samples_below_statement(main_window, qtbot, monkeypatch, problem_info, content):
    w = main_window
    oc = _outcome(w.settings.root, problem_info, content)
    d = oc.result.problem_dir
    (d / "input.txt").write_text("2\n<5>\n", encoding="utf-8")
    (d / "output.txt").write_text("#1 7\n", encoding="utf-8")
    _run_fetch(w, qtbot, monkeypatch, oc)
    htm = w.problem_page.browser.toHtml()
    text = w.problem_page.browser.toPlainText()
    assert "&lt;5&gt;" in htm and "#1 7" in text  # HTML 이스케이프
    assert text.rstrip().endswith("#1 7")  # 지문 뒤, 문서 맨 아래


def test_problem_tab_no_samples_without_folder(main_window, content):
    from swea_fetcher.content_cache import CachedStatement

    pp = main_window.problem_page
    pp.show_cached(CachedStatement(25730, "sim", "항아리 게임", "2026-09-29T00:00:00", content))
    assert "samples" not in pp.browser.toHtml() and pp.browser._samples == []


def test_open_by_number_uses_saved_folder(main_window, qtbot, monkeypatch, content):
    """문제 탭 번호 입력: 저장한 문제면 그 폴더의 입출력과 함께 (캐시가 있으면 네트워크 없이)."""
    w = main_window
    d = w.settings.root / "BFS" / "25730"
    d.mkdir(parents=True)
    (d / "25730.py").write_text("print(1)\n", encoding="utf-8")
    (d / "input.txt").write_text("1 2\n", encoding="utf-8")
    content_cache.save(w.settings, 25730, "BFS", "항아리 게임", content)
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: pytest.fail("캐시가 있으면 네트워크를 쓰지 않아야 함"))
    pp = w.problem_page
    pp.num_edit.setText("25730")
    pp.open_btn.click()
    assert w.stack.currentWidget() is pp and pp.has_content()
    assert not pp.open_dir_btn.isHidden() and "1 2" in pp.browser.toPlainText()


def test_open_by_number_unsaved_fetches_statement_only(main_window, qtbot, monkeypatch, problem_info, content):
    """저장 안 한 문제: 지문만 dry-run 으로 가져와 보여 주고, 루트에 아무 폴더도 만들지 않는다. 캐시 주제는 빈 값."""
    w = main_window
    calls = []

    def fake(settings, target, topic, opts, progress):
        calls.append((target, opts))
        return _statement_outcome(problem_info, content, topic=topic)

    monkeypatch.setattr(service, "fetch_problem", fake)
    pp = w.problem_page
    pp.num_edit.setText(str(problem_info.num))
    pp.num_edit.returnPressed.emit()
    assert not pp.open_btn.isEnabled()  # 가져오는 동안 잠금
    qtbot.waitUntil(lambda: w._stmt_worker is None, timeout=WAIT)
    (target, opts), = calls
    assert target == str(problem_info.num) and opts.dry_run and opts.skeleton_only
    assert pp.open_btn.isEnabled() and pp.has_content() and pp.badge.text() == "최신"
    assert pp.open_dir_btn.isHidden()
    assert list(w.settings.root.iterdir()) == [] if w.settings.root.exists() else True
    assert content_cache.load(w.settings, problem_info.num).topic == ""


def test_open_by_number_ignores_empty_input(main_window, monkeypatch):
    w = main_window
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: pytest.fail("빈 입력은 요청하지 않음"))
    w.problem_page.open_btn.click()
    assert w._stmt_worker is None


def test_recommend_click_saves_into_type_folder_and_opens_problem(main_window, qtbot, monkeypatch, problem_info, content):
    """오늘의 추천 항목: 저장 안 한 문제는 유형 폴더(예: stack_queue)에 실제로 저장하고, 자동 전환 토글이 꺼져 있어도 문제 탭을 연다."""
    w = main_window
    w.qs.setValue("fetch/auto_open_problem", False)
    calls = []

    def fake(settings, target, topic, opts, progress):
        calls.append((target, topic, opts))
        d = settings.root / topic / target
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{target}.py").write_text("x", encoding="utf-8")
        info = dataclasses.replace(problem_info, num=int(target))
        return FetchOutcome(info, SaveResult(d, [d / f"{target}.py"], []), None, [], topic, content)

    monkeypatch.setattr(service, "fetch_problem", fake)
    w.goto("growth")
    w.growth_page.recommend_open_requested.emit(5432, "stack_queue")
    qtbot.waitUntil(lambda: w.fetch_page._worker is None and w._recommend_saving is None, timeout=WAIT)
    (target, topic, opts), = calls
    assert target == "5432" and topic == "stack_queue" and not opts.dry_run and opts.with_content
    assert (w.settings.root / "stack_queue" / "5432").is_dir()
    assert w.stack.currentWidget() is w.problem_page and w.problem_page.badge.text() == "저장됨"


def test_recommend_click_on_already_saved_problem_does_not_save_again(main_window, qtbot, monkeypatch, content):
    w = main_window
    d = w.settings.root / "BFS" / "5432"
    d.mkdir(parents=True)
    (d / "5432.py").write_text("# 5432. 이미 저장\n", encoding="utf-8")
    content_cache.save(w.settings, 5432, "BFS", "이미 저장", content)
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: pytest.fail("이미 저장한 문제는 다시 저장하지 않음"))
    w.growth_page.recommend_open_requested.emit(5432, "bfs")
    assert w.fetch_page._worker is None
    assert w.stack.currentWidget() is w.problem_page and not w.problem_page.open_dir_btn.isHidden()
