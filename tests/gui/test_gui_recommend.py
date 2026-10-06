"""GUI 오늘의 추천 카드 (M24, offscreen): 상태 8종 · 접근성/키보드 · 클릭 라우팅 · [다른 추천] · 시작 수준 선택기 · 해결 배지 · AI 안내/교체 규칙 ·
동의 흐름 · 테마 6종×라이트/다크 · 720px · 설정 토글 · 창 닫기 취소 · 실제 RecommendWorker(서비스 대체).

워커는 conftest 의 FakeRecommendWorker(스레드 없음)로 대체하고 시그널을 직접 내보내 구동한다. 네트워크·AI 호출 0.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from swea_fetcher import ai_engine, catalog, growth, recommend, service
from swea_fetcher.ai_engine import EngineInfo
from swea_fetcher.gui import recommend_card
from swea_fetcher.gui.coach_widgets import growth_consent_ok
from swea_fetcher.gui.recommend_card import RecommendCard, RecommendRow, count_text, level_state
from swea_fetcher.gui.theme import tokens
from swea_fetcher.gui.theme.bus import bus
from swea_fetcher.gui.workers import RecommendWorker
from tests.gui.conftest import FakeRecommendWorker

NOW = datetime(2026, 10, 6, 12, 0, 0)
TODAY = NOW.date()
CODEX = EngineInfo("codex", "C:/c/codex.cmd")


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(growth, "now", lambda: NOW)


@pytest.fixture(autouse=True)
def engine(monkeypatch):
    monkeypatch.setattr(service, "growth_comment_engine", lambda settings: CODEX)


def est(level=3, cold=False):
    if cold:
        return recommend.LevelEstimate(level, "cold", f"기록이 적어 D{level} 부터 시작해요", 0, 0, {}, {}, "cold")
    return recommend.LevelEstimate(level, "ok", "최근 90일 12문제 기준", 12, 0, {level: (6.0, 0.0)}, {level: 6})


def cat_status(usable=True, wait=0):
    return catalog.CatalogStatus(count=1160 if usable else 0, fetched_at=datetime(2026, 10, 6, 9) if usable else None, stale=False,
                                 usable=usable, manual_wait=wait)


def rec(num, kind="fit", level=3, solved=False, source="rule", title=None, reason="이유 문장", pr=75.8, pa=7000):
    return recommend.Recommendation(num, title or f"문제 {num}", level, pr, pa, kind, reason, source, solved)


def items(n=4, **kw):
    kinds = ["retry", "fit", "stretch", "stretch"]
    return [rec(1000 + i, kinds[i % 4], level=3 + (i >= 2), **kw) for i in range(n)]


def result(its=None, level=None, ai_status="none", source="rule", **kw):
    its = items() if its is None else its
    return recommend.RecommendResult(day=TODAY, items=its, level=level or est(), source=source, ai_status=ai_status, catalog=kw.pop("catalog", cat_status()), **kw)


@pytest.fixture
def qs(tmp_path):
    return QSettings(str(tmp_path / "rec.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def card(qtbot, qs, settings):
    c = RecommendCard(qs)
    qtbot.addWidget(c)
    c.resize(560, 700)
    c.set_settings(settings)
    c.show()
    return c


def worker():
    return FakeRecommendWorker.last()


def loaded(card, res=None, mode_done=True):
    """auto 워커를 띄우고 규칙 결과를 받은 상태로 만든다."""
    card.ensure_loaded()
    w = worker()
    w.rule_ready.emit(res if res is not None else result())
    if mode_done:
        w.finish()
    return w


def texts(card):
    return [r.objectName() for r in card.rows]


# --- 표시 · 상태 8종 ---------------------------------------------------------------------------------


def test_hidden_without_settings_or_when_disabled(qtbot, qs, settings):
    import dataclasses

    c = RecommendCard(qs)
    qtbot.addWidget(c)
    c.ensure_loaded()
    assert c.isHidden() and c.state == "hidden" and FakeRecommendWorker.instances == []
    for off in ({"growth": False}, {"recommend": False}):
        c.set_settings(dataclasses.replace(settings, **off))
        c.ensure_loaded()
        assert c.isHidden() and c.state == "hidden"
    assert FakeRecommendWorker.instances == []  # 꺼져 있으면 워커도 안 띄운다
    c.set_settings(settings)
    c.ensure_loaded()
    assert not c.isHidden()


def test_first_entry_starts_auto_worker_in_loading_state(card):
    card.ensure_loaded()
    w = worker()
    assert w.mode == "auto" and w.running and card.state == "loading"
    assert not card.skeleton.isHidden() and card.rows == []
    assert card.status_title.text() == "추천을 고르는 중…"
    assert card.shuffle_btn.isEnabled() is False  # 고르는 중에는 비활성 + 툴팁
    assert card.shuffle_btn.toolTip()


def test_ready_state_shows_rows_level_footer_and_badges(card):
    loaded(card)
    assert card.state == "ready" and len(card.rows) == 4 and card.skeleton.isHidden() and card.status_box.isHidden()
    assert card.level_label.text() == "내 수준 D3 · 최근 90일 12문제 기준" and card.level_label.toolTip().endswith("참고용입니다.")
    assert card.picker.isHidden()
    assert card.ai_badge.text() == "규칙 기반" and not card.ai_badge.isHidden()
    assert card.footer.text() == "문제 목록 2026-10-06 기준 · 1,160문제" and not card.refresh_btn.isHidden()
    assert card.shuffle_btn.isEnabled()
    first = card.rows[0]
    assert first.objectName() == "RecommendItem_1000"
    assert first.kind_badge.text() == "수준 맞춤" or first.kind_badge.text() == "다시 도전"
    assert card.rows[0].kind_badge.text() == "다시 도전" and card.rows[2].kind_badge.text() == "한 단계 위"
    assert first.level_badge.text() == "D3"
    assert first.meta.text() == "정답률 75.8% · 참여자 7K"


def test_rows_have_accessible_names_and_tooltips(card):
    loaded(card)
    for row in card.rows:
        name = row.accessibleName()
        assert str(row.rec.num) in name and row.rec.title in name and "난이도 D" in name and "정답률 75.8%" in name and "이유 문장" in name
        assert row.toolTip() == "클릭하면 문제 탭에서 지문을 봅니다 (저장되지 않아요)"
        assert row.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_level_badge_tone_and_count_text():
    assert [level_state(n) for n in (1, 2, 3, 4, 5, 8)] == ["success", "success", "running", "running", "warning", "warning"]
    assert [count_text(n) for n in (None, 12, 999, 1000, 7000, 1200, 3_000_000)] == ["-", "12", "999", "1K", "7K", "1.2K", "3M"]


def test_cold_start_shows_picker_and_saves_choice(card, qs):
    loaded(card, result(level=est(2, cold=True)))
    assert card.state == "cold_start" and not card.picker.isHidden()
    assert card.segments.value() == "2" and [k for k in card.segments.buttons] == ["1", "2", "3", "4", "5"]
    card.segments.set_value("4", emit=True)
    assert int(qs.value("recommend/start_level")) == 4
    w = worker()
    assert w.mode == "rules" and w.start_level == 4  # 선택 즉시 규칙으로 다시 계산 (셔플 아님)
    w.rule_ready.emit(result(its=[rec(4001, level=4)], level=est(4, cold=True)))
    w.finish()
    assert card.segments.value() == "4"


def test_picker_is_hidden_when_level_is_known(card):
    loaded(card)
    assert card.picker.isHidden()


def test_picker_is_narrow_enough_for_720(card):
    loaded(card, result(level=est(2, cold=True)))
    assert card.segments.width() <= 320 and card.segments.minimumSizeHint().width() <= 300


def test_empty_state(card):
    loaded(card, result(its=[]))
    assert card.state == "empty" and not card.empty.isHidden() and card.rows == []
    assert card.shuffle_btn.isEnabled() is False


def test_empty_with_cold_start_offers_level_picker(card):
    loaded(card, result(its=[], level=est(2, cold=True)))
    assert card.state == "empty" and not card.picker.isHidden()


def test_catalog_download_progress_and_cancel(card):
    card.ensure_loaded()
    w = worker()
    w.catalog_progress.emit(12, 39)
    assert card.state == "catalog_loading" and card.status_title.text() == "문제 목록을 받는 중… 12/39"
    assert not card.cancel_btn.isHidden() and not card.skeleton.isHidden()
    card.cancel_btn.click()
    assert w.cancelled


def test_error_state_for_structure_change_has_retry(card):
    card.ensure_loaded()
    w = worker()
    w.catalog_failed.emit("parse", "앱을 업데이트하세요", False)
    w.finish()
    assert card.state == "error" and card.status_title.text() == "문제 목록을 읽지 못했어요"
    assert "업데이트" in card.status_hint.text() and not card.retry_btn.isHidden()
    assert card.status_title.property("class") == "error"
    for secret in ("http", "Traceback", "SESSION", "cookie"):
        assert secret not in card.status_title.text() + card.status_hint.text()


def test_retry_after_error_restarts_with_catalog_refresh(card):
    card.ensure_loaded()
    w = worker()
    w.catalog_failed.emit("network", "", False)
    w.finish()
    assert card.state == "offline" and card.status_title.text() == "인터넷에 연결되면 문제 목록을 받아와요"
    card.retry_btn.click()
    assert worker() is not w and worker().mode == "refresh_catalog"
    assert card.state == "loading"  # 이전 실패 표시는 지우고 다시 시도


def test_failure_state_does_not_auto_retry_on_next_visit(card):
    card.ensure_loaded()
    w = worker()
    w.catalog_failed.emit("network", "", False)
    w.finish()
    n = len(FakeRecommendWorker.instances)
    card._last_start = 0.0
    card.ensure_loaded()
    assert len(FakeRecommendWorker.instances) == n and card.state == "offline"  # 요청 폭주 없음 — [다시 시도] 로만


def test_offline_with_saved_catalog_keeps_items_and_notes(card):
    loaded(card, mode_done=False)
    w = worker()
    w.catalog_failed.emit("network", "", True)
    w.finish()
    assert card.state == "offline" and len(card.rows) == 4
    assert card.note_label.text() == "오프라인이라 저장된 문제 목록으로 추천했어요" and not card.note_row.isHidden()
    assert "저장된 목록" in card.footer.text()


def test_catalog_failure_with_saved_catalog_is_footer_warning_not_error(card):
    loaded(card, mode_done=False)
    w = worker()
    w.catalog_failed.emit("parse", "", True)
    w.finish()
    assert card.state == "ready" and len(card.rows) == 4 and "새로 받지 못해" in card.footer.text()


def test_logged_out_notice_uses_app_records_only(card):
    card.ensure_loaded()
    w = worker()
    w.notice.emit("logged_out")
    w.rule_ready.emit(result())
    w.finish()
    assert card.state == "logged_out" and len(card.rows) == 4
    assert card.note_label.text() == "SWEA 풀이 기록을 읽지 못해 앱 기록만 사용했어요" and not card.note_btn.isHidden()
    emitted = []
    card.goto_requested.connect(emitted.append)
    card.note_btn.click()
    assert emitted == ["settings"]


def test_unexpected_worker_failure_shows_error(card):
    card.ensure_loaded()
    w = worker()
    w.failed.emit("내부 오류: X", "다시 시도하세요", "traceback...")
    w.finish()
    assert card.state == "error" and "traceback" not in card.status_title.text() + card.status_hint.text()


def test_same_day_reentry_refreshes_rules_quietly(card):
    loaded(card)
    card._last_start = 0.0
    card.ensure_loaded()
    w = worker()
    assert w.mode == "rules" and card.state == "ready"  # 이미 표시 중인 추천은 스켈레톤으로 바꾸지 않는다
    w.rule_ready.emit(result(its=[rec(1000, solved=True)] + items()[1:]))
    w.finish()
    assert card.rows[0].solved_badge is not None and card.rows[0].solved_badge.text() == "해결"
    assert "해결함" in card.rows[0].accessibleName()


def test_reentry_is_throttled(card):
    loaded(card)
    n = len(FakeRecommendWorker.instances)
    card.ensure_loaded()  # 방금 시작함: 3초 안에는 또 띄우지 않는다
    assert len(FakeRecommendWorker.instances) == n


def test_new_day_starts_a_fresh_auto_run(card, monkeypatch):
    loaded(card)
    monkeypatch.setattr(growth, "now", lambda: datetime(2026, 10, 7, 9, 0))
    card._last_start = 0.0
    card.ensure_loaded()
    assert worker().mode == "auto"


def test_solved_badge_rendered_from_result(card):
    loaded(card, result(its=[rec(1, solved=True), rec(2), rec(3), rec(4)]))
    assert card.rows[0].solved_badge is not None and card.rows[1].solved_badge is None


# --- 클릭 · 키보드 -------------------------------------------------------------------------------------------


def test_click_enter_and_space_emit_open_request(card, qtbot):
    loaded(card)
    got: list[int] = []
    card.recommend_open_requested.connect(got.append)
    row = card.rows[1]
    qtbot.mouseClick(row, Qt.MouseButton.LeftButton)
    row.setFocus()
    qtbot.keyClick(row, Qt.Key.Key_Return)
    qtbot.keyClick(row, Qt.Key.Key_Space)
    qtbot.keyClick(row, Qt.Key.Key_Enter)
    assert got == [1001, 1001, 1001, 1001]
    assert card._touched


def test_press_outside_row_does_not_open(card, qtbot):
    loaded(card)
    got: list[int] = []
    card.recommend_open_requested.connect(got.append)
    row = card.rows[0]
    QTest.mousePress(row, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    QTest.mouseRelease(row, Qt.MouseButton.LeftButton, pos=QPoint(row.width() + 50, row.height() + 50))
    assert got == []


def test_rows_are_reachable_by_tab_in_visual_order(card):
    loaded(card)
    chain = [card.rows[i] for i in range(4)]
    assert [r.objectName() for r in chain] == ["RecommendItem_1000", "RecommendItem_1001", "RecommendItem_1002", "RecommendItem_1003"]
    assert all(r.focusPolicy() == Qt.FocusPolicy.StrongFocus for r in chain)


def test_click_reaches_open_problem_by_number_without_saving(qtbot, main_window, monkeypatch):
    w = main_window
    w.resize(880, 600)
    w.show()
    fetched = []
    monkeypatch.setattr(w, "_fetch_statement", lambda num, topic, problem_dir, cache_topic=None: fetched.append((num, topic, cache_topic)))
    monkeypatch.setattr(service, "find_problem", lambda settings, num: None)
    page = w.growth_page
    w.goto("growth")
    card = page.recommend
    assert not card.isHidden()
    FakeRecommendWorker.last().rule_ready.emit(result(its=[rec(2072, level=1)] + items()[1:]))
    qtbot.mouseClick(card.rows[0], Qt.MouseButton.LeftButton)
    from swea_fetcher.gui.main_window import UNSAVED_TOPIC

    assert fetched == [(2072, UNSAVED_TOPIC, "")]  # 지문만 (dry-run) — 저장 안 한 문제는 미리보기 주제로 연다
    assert not any(p.is_dir() for p in w.settings.root.iterdir())  # 루트에 아무것도 만들지 않는다


def test_opening_a_saved_problem_routes_to_its_folder(qtbot, main_window, monkeypatch):
    w = main_window
    w.resize(880, 600)
    w.show()
    opened = []
    monkeypatch.setattr(w, "_open_recent_problem", lambda topic, num: opened.append((topic, num)))
    monkeypatch.setattr(service, "find_problem", lambda settings, num: type("F", (), {"topic": "sim"})())
    w.goto("growth")
    FakeRecommendWorker.last().rule_ready.emit(result())
    qtbot.mouseClick(w.growth_page.recommend.rows[1], Qt.MouseButton.LeftButton)
    assert opened == [("sim", 1001)]


# --- [다른 추천] ---------------------------------------------------------------------------------------------


def test_shuffle_replaces_rows_and_blocks_reclicks(card, qtbot):
    loaded(card)
    before = texts(card)
    n = len(FakeRecommendWorker.instances)
    card.shuffle_btn.click()
    w = worker()
    assert w.mode == "shuffle" and len(FakeRecommendWorker.instances) == n + 1 and not card.shuffle_btn.isEnabled()
    card.shuffle_btn.click()  # 요청 중 재클릭 무시
    card._shuffle_clicked()
    assert len(FakeRecommendWorker.instances) == n + 1
    w.rule_ready.emit(result(its=[rec(7000 + i) for i in range(4)], shuffle=1))
    w.finish()
    assert texts(card) != before and texts(card)[0] == "RecommendItem_7000" and card.shuffle_btn.isEnabled()


def test_shuffle_is_disabled_without_items(card):
    loaded(card, result(its=[]))
    card._shuffle_clicked()
    assert len(FakeRecommendWorker.instances) == 1


def test_interaction_marks_card_touched_and_worker_sees_it(card):
    loaded(card)
    card.shuffle_btn.click()
    assert worker().touched() is True  # R11: 이후 도착하는 AI 결과는 현재 화면을 바꾸지 않는다


# --- AI 안내 줄 · 교체 규칙 ----------------------------------------------------------------------------------------


def test_ai_pending_then_ok_replaces_items_and_shows_badge(card):
    w = loaded(card, mode_done=False)
    assert card.ai_row.isHidden() or card._ai_status in ("none",)
    w.ai_started.emit(["codex"])
    assert card.ai_note.text() == "AI 가 약점을 분석하는 중…" and not card.spinner.isHidden() and card.ai_note.accessibleName() == card.ai_note.text()
    ai_items = [rec(5000 + i, source="ai", reason=f"약점 훈련 {i}") for i in range(4)]
    w.ai_ready.emit(result(its=ai_items, source="ai", ai_status="ok", ai_engines=["codex"]))
    w.finish()
    assert texts(card)[0] == "RecommendItem_5000" and card.ai_badge.text() == "AI 분석"
    assert card.ai_note.text() == "AI 가 약점을 반영했어요 · GPT" and card.spinner.isHidden() and card.ai_btn.isHidden()
    assert card.rows[0].reason.text() == "약점 훈련 0"


def test_ai_result_after_interaction_keeps_current_rows(card):
    w = loaded(card, mode_done=False)
    card._touched = True
    current = texts(card)
    w.ai_started.emit(["codex"])
    # 서비스는 touched 일 때 items 를 그대로 둔 결과(ai_status=ok)를 돌려준다
    w.ai_ready.emit(result(its=items(), source="rule", ai_status="ok", ai_engines=["codex"]))
    w.finish()
    assert texts(card) == current and card.ai_badge.text() == "규칙 기반"
    assert card.ai_note.text().startswith("AI 가 약점을 반영했어요")


def test_ai_needs_consent_flow(card, qs, monkeypatch):
    w = loaded(card, mode_done=False)
    w.ai_ready.emit(result(ai_status="needs_consent"))
    w.finish()
    assert card.ai_note.text() == "AI 약점 분석을 쓰려면 동의가 필요해요" and card.ai_btn.text() == "동의하고 사용" and not card.ai_btn.isHidden()
    n = len(FakeRecommendWorker.instances)
    monkeypatch.setattr(recommend_card, "ask_recommend_consent", lambda *_a: False)
    card.ai_btn.click()
    assert len(FakeRecommendWorker.instances) == n and not growth_consent_ok(qs, "codex")  # 거절: 호출 0·동의 저장 없음
    seen = {}
    monkeypatch.setattr(recommend_card, "ask_recommend_consent", lambda parent, label: seen.setdefault("label", label) and True)
    card.ai_btn.click()
    assert seen["label"] == CODEX.label and growth_consent_ok(qs, "codex")
    w2 = worker()
    assert w2.mode == "retry_ai" and "codex" in w2.consented  # 동의 뒤 AI 만 다시


def test_consent_dialog_defaults_to_cancel_and_lists_what_is_sent(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    seen = {}

    def fake_exec(self):
        seen["text"] = self.text()
        seen["default"] = self.defaultButton().text()
        seen["escape"] = self.escapeButton().text()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    assert recommend_card.ask_recommend_consent(None, "GPT (Codex)") is False
    assert "약점 분류 이름·수준 숫자·후보 문제 제목만" in seen["text"] and "코드·지문·푼 문제 목록·폴더명은 보내지 않습니다" in seen["text"]
    assert seen["default"] == "취소" and seen["escape"] == "취소"


def test_ai_no_engine_and_skipped_and_failed_messages(card):
    w = loaded(card, mode_done=False)
    w.ai_ready.emit(result(ai_status="no_engine"))
    assert card.ai_note.text() == "AI 엔진을 찾지 못해 규칙 기반으로 추천했어요" and card.ai_btn.text() == "설정으로 이동"
    emitted = []
    card.goto_requested.connect(emitted.append)
    card.ai_btn.click()
    assert emitted == ["settings"]
    w.ai_ready.emit(result(ai_status="skipped_low_data", weak_tagged=2))
    assert card.ai_note.text() == "AI 코치에서 분류가 3건 쌓이면 약점 맞춤 추천을 해요 (현재 2건)" and card.ai_btn.isHidden()
    w.ai_ready.emit(result(ai_status="failed"))
    assert card.ai_note.text() == "AI 분석에 실패해 규칙 기반으로 추천했어요" and card.ai_btn.text() == "다시 시도"
    w.finish()
    card.ai_btn.click()
    assert worker().mode == "retry_ai"


def test_ai_off_shows_no_line(card):
    w = loaded(card, result(ai_status="off"))
    assert card.ai_row.isHidden()


def test_rule_refresh_keeps_needs_consent_note(card):
    w = loaded(card, mode_done=False)
    w.ai_ready.emit(result(ai_status="needs_consent"))
    w.finish()
    card._last_start = 0.0
    card.ensure_loaded()
    worker().rule_ready.emit(result(ai_status="none"))  # 규칙 새로고침은 동의 안내를 지우지 않는다
    assert card.ai_note.text() == "AI 약점 분석을 쓰려면 동의가 필요해요"


# --- 푸터 · 새로 받기 ---------------------------------------------------------------------------------------------


def test_refresh_button_cooldown_tooltip(card):
    loaded(card, result(catalog=cat_status(wait=1800)))
    assert not card.refresh_btn.isEnabled() and "분 뒤에 다시 받을 수 있어요" in card.refresh_btn.toolTip()


def test_refresh_button_starts_manual_refresh(card):
    loaded(card)
    card.refresh_btn.click()
    assert worker().mode == "refresh_catalog"


def test_catalog_updated_refreshes_footer(card):
    w = loaded(card, mode_done=False)
    st = catalog.CatalogStatus(count=900, fetched_at=datetime(2026, 10, 8), stale=False, usable=True)
    w.catalog_updated.emit(st)
    assert card.footer.text() == "문제 목록 2026-10-08 기준 · 900문제"


# --- 테마 · 좁은 창 ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("theme", [t.key for t in tokens.THEMES])
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_card_renders_in_every_theme_and_mode(card, theme, mode):
    loaded(card, result(its=items() + [rec(9, solved=True)], level=est(2, cold=True), ai_status="needs_consent"), mode_done=False)
    tokens.set_theme(theme)
    tokens.set_color_mode(mode)
    app = QApplication.instance()
    prev_qss = app.styleSheet()
    app.setStyleSheet(tokens.build_qss())
    bus().changed.emit()
    card.grab()
    for row in card.rows:
        row.grab()
        assert row.accessibleName()
    assert len(card.rows) == 5
    app.setStyleSheet(prev_qss)


def test_card_has_no_hardcoded_colors_but_uses_tokens():
    import inspect

    src = inspect.getsource(recommend_card)
    assert "tokens.current()" in src and "setStyleSheet" not in src and "QColor(\"" not in src


def test_card_fits_720_wide_window_without_horizontal_scroll(qtbot, main_window):
    w = main_window
    w.resize(720, 480)
    w.show()
    w.goto("growth")
    page = w.growth_page
    long = [rec(1000 + i, kind=("retry", "fit", "stretch", "stretch")[i], title="아주아주 긴 제목의 문제 " * 6, reason="이유가 아주 길어서 두 줄로 내려가는 문장입니다 " * 4) for i in range(4)]
    FakeRecommendWorker.last().rule_ready.emit(result(its=long, level=est(2, cold=True)))
    qtbot.wait(50)
    card = page.recommend
    assert page.scroll.horizontalScrollBar().maximum() == 0
    vw = page.scroll.viewport().width()
    for row in card.rows:
        top_left = row.mapTo(page.scroll.viewport().window(), QPoint(0, 0))
        assert row.width() <= vw and row.mapTo(card, QPoint(0, 0)).x() >= 0
        assert row.title_width_ok() if hasattr(row, "title_width_ok") else True
    assert card.width() <= vw


def test_every_state_is_reachable_at_720(qtbot, main_window):
    w = main_window
    w.resize(720, 480)
    w.show()
    w.goto("growth")
    card = w.growth_page.recommend
    fw = FakeRecommendWorker.last()
    seen = {card.state}
    fw.catalog_progress.emit(1, 39)
    seen.add(card.state)
    fw.catalog_failed.emit("parse", "", False)
    seen.add(card.state)
    fw.finish()
    card.retry_btn.click()
    fw2 = FakeRecommendWorker.last()
    fw2.rule_ready.emit(result(its=[]))
    seen.add(card.state)
    fw2.rule_ready.emit(result(level=est(2, cold=True)))
    seen.add(card.state)
    fw2.rule_ready.emit(result())
    seen.add(card.state)
    assert {"loading", "catalog_loading", "error", "empty", "cold_start", "ready"} <= seen
    assert w.growth_page.scroll.horizontalScrollBar().maximum() == 0


# --- 설정 토글 · 숨김 · 닫기 ------------------------------------------------------------------------------------------


def test_growth_page_hides_card_when_growth_or_recommend_is_off(qtbot, main_window):
    w = main_window
    w.resize(880, 600)
    w.show()
    w.goto("growth")
    assert not w.growth_page.recommend.isHidden()
    service.set_env_values(w.config_dir, SWEA_RECOMMEND="0")
    w.reload_settings(stay=True)
    assert w.growth_page.recommend.isHidden() and w.growth_page.recommend.state == "hidden"
    service.set_env_values(w.config_dir, SWEA_RECOMMEND="1", SWEA_GROWTH="0")
    w.reload_settings(stay=True)
    assert w.growth_page.recommend.isHidden()
    service.set_env_values(w.config_dir, SWEA_GROWTH="1")
    w.reload_settings(stay=True)
    assert not w.growth_page.recommend.isHidden()


def test_card_sits_between_heatmap_and_report(main_window):
    w = main_window
    w.resize(880, 700)
    w.show()
    w.goto("growth")
    page = w.growth_page
    ys = [wd.mapTo(page.scroll.widget(), QPoint(0, 0)).y() for wd in (page.heat_card, page.recommend, page.stack.parentWidget())]
    assert ys[0] < ys[1] < ys[2]


def test_settings_toggles_save_env_and_chain_enablement(main_window):
    w = main_window
    sp = w.settings_page
    w.goto("settings")
    assert sp.recommend_enabled.isChecked() and sp.recommend_ai.isChecked()
    sp.recommend_ai.setChecked(False)
    env = config_values(w)
    assert env.get("SWEA_RECOMMEND_AI") == "0"
    assert w.settings.recommend_ai is False
    sp.recommend_enabled.setChecked(False)
    assert config_values(w).get("SWEA_RECOMMEND") == "0" and not sp.recommend_ai.isEnabled()
    sp.recommend_enabled.setChecked(True)
    sp.growth_enabled.setChecked(False)
    assert not sp.recommend_enabled.isEnabled() and not sp.recommend_ai.isEnabled()


def config_values(w) -> dict:
    from swea_fetcher import config

    return config.read_env_file(w.config_dir)


def test_growth_clear_dialog_mentions_recommendation_records(main_window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    seen = {}

    def fake_exec(self):
        seen["text"] = self.text()

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    main_window.settings_page._clear_growth()
    assert "오늘의 추천 기록 포함" in seen["text"]


def test_wait_workers_cancels_running_worker_first(card):
    card.ensure_loaded()
    w = worker()
    card.wait_workers()
    assert w.cancelled


def test_closing_the_window_cancels_recommend_worker(qtbot, main_window):
    w = main_window
    w.resize(880, 600)
    w.show()
    w.goto("growth")
    fw = FakeRecommendWorker.last()
    assert fw.running
    w.close()
    assert fw.cancelled


def test_set_settings_cancels_running_worker_and_resets(card, settings):
    card.ensure_loaded()
    w = worker()
    card.set_settings(settings)
    assert w.cancelled and card.result is None


def test_theme_change_rebuilds_rows(card):
    loaded(card)
    old = list(card.rows)
    bus().changed.emit()
    assert len(card.rows) == 4 and all(a is not b for a, b in zip(old, card.rows))


# --- 실제 RecommendWorker (서비스 대체) --------------------------------------------------------------------------


class Recorder:
    def __init__(self):
        self.calls: list[str] = []


@pytest.fixture
def real_service(monkeypatch):
    """RecommendWorker 가 부르는 service 함수를 대체한다 (네트워크·AI 0)."""
    rec_calls: list = []
    st = {"usable": True, "stale": False, "auto_due": True, "passed": 0, "ai": None}

    def status(settings, now=None):
        return catalog.CatalogStatus(count=10 if st["usable"] else 0, fetched_at=datetime(2026, 10, 6), stale=st["stale"], usable=st["usable"], auto_due=st["auto_due"])

    def refresh(settings, *, progress=None, is_cancelled=None, force=False, **kw):
        rec_calls.append(("refresh", force))
        if progress:
            progress(1, 2)
            progress(2, 2)
        if st.get("fail"):
            raise service.CatalogError("x", code=st["fail"])
        st["usable"] = True
        st["stale"] = False
        return catalog.CatalogStatus(count=10, fetched_at=datetime(2026, 10, 7), stale=False, usable=True)

    def today(settings, *, start_level=None, shuffle=False, **kw):
        rec_calls.append(("today", start_level, shuffle))
        return result()

    def ai(settings, base, *, consent_ok, on_start=None, on_begin=None, is_cancelled=None, is_touched=None, retry=False, **kw):
        rec_calls.append(("ai", retry, consent_ok("codex"), consent_ok("claude"), bool(is_touched and is_touched())))
        if on_begin:
            on_begin(["codex"])
        if st["ai"]:
            st["ai"](on_start, is_cancelled)
        base.ai_status = "ok"
        return base

    monkeypatch.setattr(service, "catalog_status", status)
    monkeypatch.setattr(service, "refresh_catalog", refresh)
    monkeypatch.setattr(service, "recommend_today", today)
    monkeypatch.setattr(service, "recommend_ai", ai)
    monkeypatch.setattr(service, "refresh_passed", lambda settings, **kw: rec_calls.append(("passed",)) or st["passed"])
    return rec_calls, st


def run_worker(qtbot, settings, mode="auto", **kw):
    w = RecommendWorker(settings, mode, kw.pop("start_level", None), kw.pop("consented", frozenset()), kw.pop("touched", None))
    got: dict[str, list] = {k: [] for k in ("rule", "ai_started", "ai_ready", "progress", "updated", "failed_cat", "notice", "failed")}
    w.rule_ready.connect(got["rule"].append)
    w.ai_started.connect(got["ai_started"].append)
    w.ai_ready.connect(got["ai_ready"].append)
    w.catalog_progress.connect(lambda a, b: got["progress"].append((a, b)))
    w.catalog_updated.connect(got["updated"].append)
    w.catalog_failed.connect(lambda c, h, u: got["failed_cat"].append((c, u)))
    w.notice.connect(got["notice"].append)
    w.failed.connect(lambda t, h, d: got["failed"].append(t))
    with qtbot.waitSignal(w.finished, timeout=8000):
        w.start()
    w.wait(2000)
    return w, got


def test_worker_auto_runs_rules_then_ai_without_network(qtbot, settings, real_service):
    calls, _st = real_service
    w, got = run_worker(qtbot, settings, consented={"codex"}, start_level=3)
    assert [c[0] for c in calls] == ["passed", "today", "ai"]
    assert calls[1] == ("today", 3, False) and calls[2][1:4] == (False, True, False)  # 동의된 엔진만 True
    assert len(got["rule"]) == 1 and got["ai_started"] == [["codex"]] and got["ai_ready"][0].ai_status == "ok" and got["failed"] == []


def test_worker_auto_downloads_missing_catalog_first(qtbot, settings, real_service):
    calls, st = real_service
    st["usable"] = False
    w, got = run_worker(qtbot, settings)
    assert calls[0] == ("refresh", False) and got["progress"] == [(1, 2), (2, 2)] and len(got["updated"]) == 1
    assert [c[0] for c in calls[1:]] == ["passed", "today", "ai"]


def test_worker_reports_catalog_failure_and_stops(qtbot, settings, real_service):
    calls, st = real_service
    st["usable"] = False
    st["fail"] = "network"
    w, got = run_worker(qtbot, settings)
    assert got["failed_cat"] == [("network", False)] and got["rule"] == [] and [c[0] for c in calls] == ["refresh"]


def test_worker_notices_logged_out_when_passed_list_fails(qtbot, settings, real_service):
    calls, st = real_service
    st["passed"] = -1
    w, got = run_worker(qtbot, settings)
    assert got["notice"] == ["logged_out"] and len(got["rule"]) == 1  # 실패해도 앱 기록으로 계속


def test_worker_quiet_refresh_of_stale_catalog_at_the_end(qtbot, settings, real_service):
    calls, st = real_service
    st["stale"] = True
    w, got = run_worker(qtbot, settings)
    names = [c[0] for c in calls]
    assert names == ["passed", "today", "ai", "refresh", "today"] and calls[3] == ("refresh", False)
    assert len(got["rule"]) == 2 and len(got["updated"]) == 1


def test_worker_modes_shuffle_rules_retry_and_manual_refresh(qtbot, settings, real_service):
    calls, st = real_service
    run_worker(qtbot, settings, "shuffle")
    assert calls == [("today", None, True)]
    calls.clear()
    run_worker(qtbot, settings, "rules", start_level=4)
    assert calls == [("today", 4, False)]
    calls.clear()
    run_worker(qtbot, settings, "retry_ai", consented={"claude"}, touched=lambda: True)
    assert calls == [("today", None, False), ("ai", True, False, True, True)]
    calls.clear()
    run_worker(qtbot, settings, "refresh_catalog")
    assert [c[0] for c in calls] == ["refresh", "passed", "today", "ai"] and calls[0] == ("refresh", True)


def test_worker_does_nothing_when_disabled(qtbot, settings, real_service):
    import dataclasses

    calls, _ = real_service
    run_worker(qtbot, dataclasses.replace(settings, recommend=False))
    assert calls == []


def test_worker_cancel_kills_every_registered_process(qtbot, settings, real_service, monkeypatch):
    calls, st = real_service
    killed = []
    monkeypatch.setattr(ai_engine, "kill_tree", lambda proc: killed.append(proc))
    procs = [object(), object()]
    w = RecommendWorker(settings, "auto")

    def ai_run(on_start, is_cancelled):
        for p in procs:
            on_start(p)
        w.cancel()  # 실행 중 취소 → 등록된 두 프로세스 모두 종료
        assert is_cancelled()

    st["ai"] = ai_run
    with qtbot.waitSignal(w.finished, timeout=8000):
        w.start()
    w.wait(2000)
    assert killed == procs


def test_worker_kills_process_that_starts_after_cancel(qtbot, settings, real_service, monkeypatch):
    killed = []
    monkeypatch.setattr(ai_engine, "kill_tree", lambda proc: killed.append(proc))
    w = RecommendWorker(settings, "auto")
    w.cancel()
    w._on_start("late-proc")
    assert killed == ["late-proc"]
