"""GUI 성장 기록 (M19, offscreen): 성장 탭 상태·코멘트 카드·목록·차트, 상태바 배지·시작 알림, 설정 카드, 동의 배너 → 워커, 내비 6개.

service.generate_growth / growth_comment_engine 은 대체한다 — 실제 CLI·네트워크 호출 0. 시간은 growth.now 를 고정한다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QShortcut

from swea_fetcher import config, growth, service
from swea_fetcher.ai_engine import EngineInfo
from swea_fetcher.errors import AiEngineMissing
from swea_fetcher.gui import coach_widgets
from swea_fetcher.gui.growth_widgets import BarChart, SparkLine
from swea_fetcher.gui.main_window import PAGES, MainWindow
from swea_fetcher.gui.pages import growth_page as growth_page_mod
from swea_fetcher.gui.pages import settings_page as settings_page_mod
from swea_fetcher.growth import Snapshot, WeekStats
from swea_fetcher.growth_tags import Parsed, Tag
from swea_fetcher.service import CoachAnswer, CoachResult, EngineOutcome, GrowthRunResult

WAIT = 8000
NOW = datetime(2026, 9, 30, 12, 0, 0)
MON = date(2026, 9, 28)
W1, W2, W3 = date(2026, 9, 21), date(2026, 9, 14), date(2026, 9, 7)
CODEX = EngineInfo("codex", "C:/c/codex.cmd")


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(growth, "now", lambda: NOW)


@pytest.fixture(autouse=True)
def engine(monkeypatch):
    """주간 코멘트 엔진: 기본은 Codex 설치됨 (테스트가 None 으로 바꿔 미설치를 흉내)."""
    st = {"engine": CODEX}
    monkeypatch.setattr(service, "growth_comment_engine", lambda settings: st["engine"])
    return st


@pytest.fixture
def gw(main_window):
    main_window.resize(880, 600)
    main_window.show()
    return main_window


def stats(**kw) -> WeekStats:
    base = dict(submits=8, passes=4, solved=4, wrong=4, first_try=2, avg_wrong_before_pass=1.0, hints=2, reviews=2, tagged=4, events=8, weak={"edge": 4, "time": 2}, strong={"pythonic": 2})
    base.update(kw)
    return WeekStats(**base)


def snap(settings, week, status="pending", seen=True, comment=None, attempts=0, prev=None, **kw):
    s = Snapshot(week, "2026-09-28T09:00:00", stats(**kw), prev, comment_status=status, comment=comment, comment_attempts=attempts, seen_at="x" if seen else None)
    assert growth.save_snapshot(settings, s)
    return s


def live_events(settings, n=3):
    """이번 주(진행 중) 이벤트."""
    for i in range(n):
        growth.record_submit(settings, 3000 + i, "sim", "pass", 0, at=datetime(2026, 9, 28, 9 + i))
    growth.record_coach(settings, 3000, "sim", "review", 0, "codex", Parsed((Tag("edge", "weak", 2),)), at=datetime(2026, 9, 29, 9))


def set_growth_env(w, **kv):
    service.set_env_values(w.config_dir, **kv)
    w.reload_settings(stay=True)


def page_of(w):
    w.goto("growth")
    return w.growth_page


# --- 내비 --------------------------------------------------------------------------------


def test_nav_has_six_pages_growth_before_settings_and_ctrl_shortcuts(main_window):
    w = main_window
    assert [k for _l, k, _i in PAGES] == ["fetch", "problem", "check", "history", "growth", "settings"]
    assert w.nav.count() == 6 and w.stack.count() == 6 and w.nav.item(4).text() == "성장" and not w.nav.item(4).icon().isNull()
    keys = {s.key().toString(): s for s in w.findChildren(QShortcut)}
    keys["Ctrl+5"].activated.emit()
    assert w.stack.currentWidget() is w.growth_page
    keys["Ctrl+6"].activated.emit()
    assert w.stack.currentWidget() is w.settings_page  # 설정은 Ctrl+5 -> Ctrl+6
    keys["Ctrl+,"].activated.emit()
    w.goto("fetch")
    keys["Ctrl+,"].activated.emit()
    assert w.stack.currentWidget() is w.settings_page


def test_growth_last_page_key_restored_and_back_forward(qtbot, valid_config):
    w = MainWindow(config_dir=valid_config)
    qtbot.addWidget(w)
    w.goto("growth")
    assert w.qs.value("window/last_page_key", type=str) == "growth"
    w.goto("settings")
    w.go_back()
    assert w.stack.currentWidget() is w.growth_page
    w.go_forward()
    assert w.stack.currentWidget() is w.settings_page
    w.qs.sync()
    w2 = MainWindow(config_dir=valid_config)
    qtbot.addWidget(w2)
    assert w2.stack.currentWidget() is w2.settings_page  # 마지막 페이지(설정)가 키로 복원


def test_first_run_redirect_is_key_based(main_window_no_config):
    w = main_window_no_config
    assert w.stack.currentWidget() is w.settings_page and PAGES[w.nav.currentRow()][1] == "settings"


# --- 성장 탭 상태 ---------------------------------------------------------------------------------


def test_off_state_shows_notice_and_hides_cards(gw, valid_config):
    set_growth_env(gw, SWEA_GROWTH="0")
    p = page_of(gw)
    assert p.stack.currentWidget() is p.off_state and p.comment_state == "off"
    assert not p.banner.isHidden() and "꺼져" in p.banner.title.text() and p.stack.currentWidget() is not p.content
    got = []
    p.goto_requested.connect(got.append)
    p.off_state.button.click()
    assert got == ["settings"]


def test_empty_state(gw):
    p = page_of(gw)
    assert p.stack.currentWidget() is p.empty and p.comment_state == "empty" and p.banner.isHidden()


def test_only_in_progress_week_is_shown_by_default(gw):
    live_events(gw.settings)
    p = page_of(gw)
    assert p.stack.currentWidget() is p.content and p.selected_week == MON
    assert p.state_badge.text() == "진행 중" and not p.confirm_note.isHidden()
    assert p.comment_state == "in_progress" and "첫 주가 끝나면" in p.comment_text.text() and p.comment_btn.isHidden()
    assert "AI 분류 기반 참고용" in p.reference.text()
    assert p.report_list.count() == 1 and p.report_list.item(0).text() == "이번 주 (진행 중)"
    assert p.headline.text() == growth.FIRST_RECORD_TEXT  # 기준 주가 없으면 첫 기록 문구


def test_default_selection_is_latest_confirmed_report(gw):
    snap(gw.settings, W2)
    snap(gw.settings, W1, prev=W2, first_try=4, passes=4, avg_wrong_before_pass=0.0)  # 첫 시도 0.5 -> 1.0
    live_events(gw.settings)
    p = page_of(gw)
    assert p.selected_week == W1 and p.state_badge.text() == "확정" and p.confirm_note.isHidden()
    assert p.range_label.text() == "2026-09-21 ~ 09-27"
    texts = [p.report_list.item(i).text() for i in range(p.report_list.count())]
    assert texts[0] == "이번 주 (진행 중)" and texts[1] == "09-21 ~ 09-27 · Pass 4 · 좋아진 점 0" and texts[2].startswith("09-14 ~ 09-20")


def test_report_header_shows_judgments_and_baseline(gw):
    prev = snap(gw.settings, W2, passes=4, first_try=1, tagged=4, weak={"edge": 2})
    cur = snap(gw.settings, W1, prev=W2, passes=4, first_try=4, tagged=4, weak={"edge": 2})
    growth.update_snapshot(gw.settings, W1)  # 아무 변경 없이 호출해도 안전
    # 판정은 스냅샷에 저장된 것 그대로 보여준다 (재계산 없음)
    cur.judgments = [growth.Judgment("improved", "first_try_rate", 1.0, 0.25, "첫 시도 Pass 비율이 25% → 100% 로 올랐어요"),
                     growth.Judgment("watch", "timeout_share", 0.4, 0.1, "시간초과 비중이 10% → 40% 로 늘었어요"),
                     growth.Judgment("persistent", "weak:time", 3, None, "'시간 복잡도'가 3주 연속 지적되고 있어요")]
    growth.save_snapshot(gw.settings, cur)
    p = page_of(gw)
    assert not p.good_label.isHidden() and not p.watch_label.isHidden() and not p.persist_label.isHidden()
    assert "첫 시도 Pass 비율이 25% → 100%" in p.good_box.itemAt(0).widget().text() and p.good_box.count() == 1 and p.watch_box.count() == 1
    assert prev.stats.passes == 4


def test_no_change_headline(gw):
    snap(gw.settings, W2)
    snap(gw.settings, W1, prev=W2)
    p = page_of(gw)
    assert p.headline.text() == "이번 주는 뚜렷한 변화가 없어요 (꾸준히 4문제 해결)" and p.good_label.isHidden()


# --- 코멘트 카드 상태 -------------------------------------------------------------------------------


def comment_state(gw, status, **kw):
    snap(gw.settings, W1, status=status, **kw)
    p = page_of(gw)
    p.refresh()
    return p


def test_comment_card_done(gw):
    coach_widgets.set_consent(gw.growth_page.qs, "codex")
    p = comment_state(gw, "ok", comment={"text": "이번 주 잘하셨어요", "engine": "GPT (Codex)", "at": "2026-09-28T09:10:00"})
    assert p.comment_state == "done" and not p.comment_browser.isHidden() and "이번 주 잘하셨어요" in p.comment_browser.toPlainText()
    assert p.comment_meta.text() == "GPT · 2026-09-28 09:10" and p.comment_btn.text() == "다시 받기" and not p.comment_btn.isHidden()


def test_comment_card_low_data_backlog_failed_pending(gw):
    coach_widgets.set_consent(gw.growth_page.qs, "codex")
    p = comment_state(gw, "skipped_low_data")
    assert p.comment_state == "skipped_low_data" and "기록이 적어 코멘트를 생략" in p.comment_text.text() and p.comment_btn.isHidden()
    p = comment_state(gw, "skipped_backlog")
    assert p.comment_state == "skipped_backlog" and "밀린 주라 통계만" in p.comment_text.text() and p.comment_btn.text() == "코멘트 받기" and not p.comment_btn.isHidden()
    p = comment_state(gw, "failed", attempts=1)
    assert p.comment_state == "failed" and "만들지 못했어요" in p.comment_text.text() and p.comment_btn.text() == "다시 받기"
    p.note_comment_failure(W1, "Codex 실행 실패")
    p.refresh()
    assert "Codex 실행 실패" in p.comment_text.text()
    p = comment_state(gw, "pending")
    assert p.comment_state == "pending" and p.comment_btn.text() == "코멘트 받기"


def test_comment_card_loading_and_cancel(gw):
    coach_widgets.set_consent(gw.growth_page.qs, "codex")
    p = comment_state(gw, "pending")
    got = []
    p.cancel_requested.connect(lambda: got.append(1))
    p.set_comment_running(W1)
    assert p.comment_state == "loading" and "작성 중" in p.comment_text.text() and not p.comment_cancel_btn.isHidden() and p.comment_btn.isHidden()
    p.comment_cancel_btn.click()
    assert got == [1]
    p.set_comment_running(None)
    assert p.comment_state == "pending" and p.comment_cancel_btn.isHidden()


def test_comment_card_blockers(gw, engine):
    p = comment_state(gw, "pending")
    assert p.blocker == "needs_consent" and not p.banner.isHidden() and "동의하고 코멘트 받기" in [b.text() for b in p.banner._buttons]
    assert "CLI" not in p.banner.body.text() and "집계 숫자와 분류 이름만 GPT (Codex) 으로 보냅니다(코드·지문·문제 번호 제외)" in p.banner.body.text()
    coach_widgets.set_consent(p.qs, "codex")  # 코치 동의가 있으면 추가 동의 없이 허용
    p.refresh()
    assert p.blocker is None and p.banner.isHidden()
    engine["engine"] = None
    p.refresh()
    assert p.comment_state == "no_engine" and "엔진을 찾지 못해" in p.comment_text.text() and not p.comment_settings_btn.isHidden() and p.comment_btn.isHidden()
    engine["engine"] = CODEX
    set_growth_env(gw, SWEA_GROWTH_COMMENT="0")
    p = page_of(gw)
    p.refresh()
    assert p.comment_state == "comment_off" and "꺼져 있어요" in p.comment_text.text() and not p.comment_btn.isHidden()  # 수동 받기는 가능


# --- 목록 선택 · 미확인 · 배지 --------------------------------------------------------------------

def test_list_selection_updates_cards_and_marks_seen(gw):
    coach_widgets.set_consent(gw.growth_page.qs, "codex")
    snap(gw.settings, W2, seen=False, solved=3, passes=3)
    snap(gw.settings, W1, seen=False, solved=6, passes=6, first_try=3)
    gw._refresh_growth_badge()
    assert gw.growth_badge.text() == "새 성장 리포트 2개 ↗" and not gw.growth_badge.isHidden()
    p = page_of(gw)  # 가장 최근 확정 = W1 을 표시 → 확인 처리
    assert p.selected_week == W1 and service.growth_unseen_count(gw.settings) == 1
    assert gw.growth_badge.text() == "새 성장 리포트 ↗"
    assert "새 · " in p.report_list.item(2).text() and not p.report_list.item(1).text().startswith("새")
    p.report_list.setCurrentRow(2)  # 09-14 리포트 선택
    assert p.selected_week == W2 and p.range_label.text() == "2026-09-14 ~ 09-20"
    assert service.growth_unseen_count(gw.settings) == 0 and gw.growth_badge.isHidden()
    assert p.scroll.verticalScrollBar().value() == 0
    assert p.metric_box.count() == 5


def test_seen_is_not_marked_while_page_is_hidden(gw):
    snap(gw.settings, W1, seen=False)
    gw.goto("fetch")
    gw.growth_page.refresh()
    assert service.growth_unseen_count(gw.settings) == 1


def test_badge_click_goes_to_growth_tab(gw):
    snap(gw.settings, W1, seen=False)
    gw._refresh_growth_badge()
    gw.goto("fetch")
    gw.growth_badge.click()
    assert gw.stack.currentWidget() is gw.growth_page
    assert gw.growth_badge.isHidden()  # 리포트를 봤으니 사라진다


def test_badge_hidden_when_growth_off(gw):
    snap(gw.settings, W1, seen=False)
    set_growth_env(gw, SWEA_GROWTH="0")
    assert gw.growth_badge.isHidden()


# --- 시작 알림 ------------------------------------------------------------------------------------


def _start(qtbot, valid_config):
    w = MainWindow(config_dir=valid_config)
    qtbot.addWidget(w)
    return w


def test_startup_message_growth_only(qtbot, valid_config):
    s = config.load_settings(valid_config)
    snap(s, W1, seen=False)
    w = _start(qtbot, valid_config)
    assert w.statusBar().currentMessage() == "새 성장 리포트가 도착했어요 — 성장 탭에서 확인" and not w.isModal()


def test_startup_message_merges_review_and_growth(qtbot, valid_config):
    from swea_fetcher import coach
    from swea_fetcher.submit import SubmitResult

    s = config.load_settings(valid_config)
    snap(s, W1, seen=False)
    for num in (601, 602):
        coach.record_submit(s, num, "sim", "t", SubmitResult(False, "오답"))
        coach.mark_solution_viewed(s, num, 1, today=date.today() - timedelta(days=2))
    w = _start(qtbot, valid_config)
    assert w.statusBar().currentMessage() == "복습 2개 · 새 성장 리포트 — 최근/성장 탭에서 확인"


def test_startup_message_review_only_unchanged(qtbot, valid_config):
    from swea_fetcher import coach
    from swea_fetcher.submit import SubmitResult

    s = config.load_settings(valid_config)
    coach.record_submit(s, 601, "sim", "t", SubmitResult(False, "오답"))
    coach.mark_solution_viewed(s, 601, 1, today=date.today() - timedelta(days=2))
    w = _start(qtbot, valid_config)
    assert w.statusBar().currentMessage() == "복습할 문제 1개가 있습니다 — 최근 탭에서 확인"


# --- 워커 · 동의 ------------------------------------------------------------------------------------


class FakeBox:
    """QMessageBox 대역: exec 없이 미리 정한 버튼을 클릭한 것으로 처리."""

    choose = ""
    made: list = []

    def __init__(self, icon, title, text, parent=None):
        self.title, self.text = title, text
        self.buttons = {}
        FakeBox.made.append(self)

    class Icon:
        Question = Warning = 0

    class ButtonRole:
        AcceptRole = RejectRole = DestructiveRole = 0

    def addButton(self, label, role):  # noqa: N802
        from PySide6.QtWidgets import QPushButton

        self.buttons[label] = QPushButton(label)
        return self.buttons[label]

    def setDefaultButton(self, b):  # noqa: N802
        pass

    def setEscapeButton(self, b):  # noqa: N802
        pass

    def exec(self):
        return 0

    def clickedButton(self):  # noqa: N802
        return self.buttons.get(FakeBox.choose)


@pytest.fixture
def fake_gen(monkeypatch):
    """service.generate_growth 대역. calls 에 (consented 결과, force_week) 기록."""
    st = {"calls": [], "result": GrowthRunResult(), "comment": True}

    def gen(settings, *, consent_ok, force_week=None, on_begin=None, on_comment=None, on_stats=None, **kw):
        st["calls"].append({"force_week": force_week, "consent_codex": consent_ok("codex"), "consent_claude": consent_ok("claude")})
        if st["result"].new_weeks and on_stats:
            on_stats(list(st["result"].new_weeks))
        if force_week is not None and on_begin:
            on_begin(force_week)
            if on_comment and st["comment"]:
                growth.update_snapshot(settings, force_week, comment={"text": "새 코멘트", "engine": "GPT (Codex)", "at": "2026-09-30T12:00:00"}, comment_status="ok")
                on_comment(force_week, "새 코멘트")
        return st["result"]

    monkeypatch.setattr(service, "generate_growth", gen)
    return st


def test_consent_banner_dialog_saves_consent_and_starts_worker(qtbot, gw, fake_gen, monkeypatch):
    snap(gw.settings, W1, status="pending")
    p = page_of(gw)
    assert p.blocker == "needs_consent"
    monkeypatch.setattr(growth_page_mod, "QMessageBox", FakeBox)
    FakeBox.choose = "취소"
    p.banner._buttons[0].click()
    assert not coach_widgets.growth_consent_ok(p.qs, "codex") and fake_gen["calls"] == [] and gw._growth_worker is None
    FakeBox.choose = "동의하고 코멘트 받기"
    p.banner._buttons[0].click()
    assert coach_widgets.growth_consent_ok(p.qs, "codex")
    assert "집계 숫자와 분류 이름만" in FakeBox.made[-1].text and "코드·지문·문제 번호·제목·폴더명은 보내지 않습니다" in FakeBox.made[-1].text
    qtbot.waitUntil(lambda: gw._growth_worker is None and bool(fake_gen["calls"]), timeout=WAIT)
    assert fake_gen["calls"][0] == {"force_week": W1, "consent_codex": True, "consent_claude": False}
    qtbot.waitUntil(lambda: p.comment_state == "done", timeout=WAIT)
    assert "새 코멘트" in p.comment_browser.toPlainText() and p.banner.isHidden()


def test_manual_button_with_consent_starts_worker_without_dialog(qtbot, gw, fake_gen, monkeypatch):
    coach_widgets.set_consent(gw.growth_page.qs, "codex")
    snap(gw.settings, W1, status="skipped_backlog")
    monkeypatch.setattr(growth_page_mod, "QMessageBox", lambda *a, **k: pytest.fail("동의가 있으면 확인창이 뜨지 않는다"))
    p = page_of(gw)
    p.comment_btn.click()
    qtbot.waitUntil(lambda: gw._growth_worker is None and bool(fake_gen["calls"]), timeout=WAIT)
    assert fake_gen["calls"][0]["force_week"] == W1 and fake_gen["calls"][0]["consent_codex"] is True


def test_no_engine_button_goes_to_settings_and_no_worker(gw, fake_gen, engine):
    engine["engine"] = None
    snap(gw.settings, W1, status="pending")
    p = page_of(gw)
    got = []
    p.goto_requested.connect(got.append)
    p.comment_settings_btn.click()
    assert got == ["settings"] and fake_gen["calls"] == []


def test_kick_starts_worker_only_when_due(qtbot, gw, fake_gen):
    gw._growth_kick()
    assert gw._growth_worker is None and fake_gen["calls"] == []  # 할 일 없음 (틱은 파일 확인만)
    live_events(gw.settings)
    for i in range(3):
        growth.record_submit(gw.settings, 900 + i, "sim", "pass", 0, at=datetime(2026, 9, 22, 9 + i))  # 지난 주 이벤트 -> 만들 스냅샷
    fake_gen["result"] = GrowthRunResult(new_weeks=[W1])
    gw._growth_kick()
    assert gw._growth_worker is not None
    qtbot.waitUntil(lambda: gw._growth_worker is None, timeout=WAIT)
    assert len(fake_gen["calls"]) == 1
    assert gw.statusBar().currentMessage().startswith("새 성장 리포트가 도착했어요")


def test_kick_skipped_when_growth_off_or_running(qtbot, gw, fake_gen):
    for i in range(3):
        growth.record_submit(gw.settings, 900 + i, "sim", "pass", 0, at=datetime(2026, 9, 22, 9 + i))
    set_growth_env(gw, SWEA_GROWTH="0")
    gw._growth_kick()
    assert gw._growth_worker is None and fake_gen["calls"] == []


def test_manual_request_while_worker_running_is_queued(qtbot, gw, fake_gen, monkeypatch):
    import threading

    gate = threading.Event()
    orig = service.generate_growth

    def slow(settings, **kw):
        gate.wait(5)
        return orig(settings, **kw)

    monkeypatch.setattr(service, "generate_growth", slow)
    coach_widgets.set_consent(gw.growth_page.qs, "codex")
    snap(gw.settings, W1, status="pending")
    gw._growth_kick()
    assert gw._growth_worker is not None
    gw._growth_kick(W1)  # 실행 중: 두 번째 워커를 만들지 않고 대기열에
    assert gw._growth_queued == W1
    gate.set()
    qtbot.waitUntil(lambda: gw._growth_worker is None and gw._growth_queued is None and len(fake_gen["calls"]) == 2, timeout=WAIT)
    assert [c["force_week"] for c in fake_gen["calls"]] == [None, W1]


def test_close_cancels_running_growth_worker(qtbot, gw, monkeypatch):
    import threading

    started = threading.Event()
    seen = {}

    def slow(settings, *, is_cancelled=None, **kw):
        started.set()
        while not is_cancelled():
            threading.Event().wait(0.01)
        seen["cancelled"] = True
        return GrowthRunResult(cancelled=True)

    monkeypatch.setattr(service, "generate_growth", slow)
    snap(gw.settings, W1, status="pending")
    gw._growth_kick(W1)
    assert started.wait(5)
    gw.close()
    assert seen.get("cancelled") is True


def test_worker_cancel_kills_process_tree(qtbot, monkeypatch):
    from swea_fetcher import ai_engine
    from swea_fetcher.gui.workers import GrowthWorker

    killed = []
    monkeypatch.setattr(ai_engine, "kill_tree", killed.append)
    w = GrowthWorker(None, set())
    proc = object()
    w._on_start(proc)
    w.cancel()
    assert killed == [proc]
    w2 = GrowthWorker(None, set())
    w2.cancel()  # 아직 프로세스가 없으면 뜨는 즉시 죽인다
    w2._on_start(proc)
    assert killed == [proc, proc]


# --- 차트 위젯 ---------------------------------------------------------------------------------------


def render(widget) -> QImage:
    widget.resize(widget.size())
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.white)
    widget.render(img)
    return img


def has_ink(img: QImage) -> bool:
    white = QImage(img.size(), QImage.Format.Format_ARGB32)
    white.fill(Qt.GlobalColor.white)
    return img != white


def test_bar_chart_renders_and_has_accessible_description(qtbot):
    c = BarChart()
    qtbot.addWidget(c)
    c.resize(500, 120)
    c.set_data([1, 0, 3, 5, 0, 2, 4, 6], [f"09-{d:02d}" for d in range(1, 9)], 7)
    assert has_ink(render(c)) and c.height() == 120
    assert c.accessibleName() == "주별 Pass 문제 수" and "09-01: 1" in c.accessibleDescription() and "09-08: 6" in c.toolTip()


@pytest.mark.parametrize("values", [[], [0, 0, 0], [7], [None, None]])
def test_bar_chart_safe_on_edge_values(qtbot, values):
    c = BarChart()
    qtbot.addWidget(c)
    c.resize(300, 120)
    c.set_data(values, ["a"] * len(values), len(values) - 1)
    render(c)  # 예외 없음
    c.resize(60, 120)  # 아주 좁아도 안전
    render(c)


def test_spark_line_draws_and_describes(qtbot):
    s = SparkLine()
    qtbot.addWidget(s)
    s.set_data([0.1, None, 0.4, 0.3, None, 0.9], True, "첫 시도 Pass 비율")
    assert has_ink(render(s)) and (s.width(), s.height()) == (96, 24)
    assert "0.1 → 0.9" in s.accessibleDescription() and "낮을수록 좋음" in s.accessibleDescription()


@pytest.mark.parametrize("values", [[], [None], [0.5], [None, 0.5, None], [1, 1, 1, 1], [0, 0]])
def test_spark_line_safe_on_edge_values(qtbot, values):
    s = SparkLine()
    qtbot.addWidget(s)
    s.set_data(values)
    render(s)
    if len([v for v in values if v is not None]) < 2:
        assert "부족" in s.accessibleDescription()  # "-" 표시


def test_report_charts_and_rows_are_built(gw):
    snap(gw.settings, W2, first_try=1, tagged=4, weak={"edge": 4})
    snap(gw.settings, W1, prev=W2, first_try=4, tagged=4, weak={"edge": 2, "time": 2}, strong={"pythonic": 3})
    p = page_of(gw)
    assert p.chart.values[-1] == 4.0 and p.chart.values[0] == 0.0 and p.chart.highlight == 7 and len(p.chart.labels) == 8
    assert [p.metric_box.itemAt(i).widget().objectName() for i in range(5)][:2] == ["MetricRow_solved", "MetricRow_first_try_rate"]
    assert p.weak_box.count() == 2 and p.strong_box.count() == 1
    row = p.metric_box.itemAt(1).widget()
    assert "좋아짐" in row.change.text() and row.spark.accessibleDescription()


def test_category_card_falls_back_when_few_tagged(gw):
    snap(gw.settings, W1, tagged=2, weak={"edge": 1})
    p = page_of(gw)
    assert not p.category_note.isHidden() and p.category_note.text() == "AI 코치를 더 사용하면 변화가 보여요 (이번 주 분류 2건)"
    assert p.weak_box.count() == 0 and p.weak_label.isHidden()


def test_page_scrolls_without_clipping_at_minimum_size(gw):
    snap(gw.settings, W2, first_try=1, tagged=4, weak={"edge": 4})
    s1 = snap(gw.settings, W1, prev=W2, first_try=4, tagged=4, weak={"edge": 2, "time": 2}, strong={"pythonic": 3}, hints=12, solutions=10)  # 긴 값 ("힌트 12 · 정답 풀이 10")
    s1.judgments = [growth.Judgment("improved", "first_try_rate", 1.0, 0.25, "첫 시도 Pass 비율이 25% → 100% 로 올랐어요 " * 3),
                    growth.Judgment("persistent", "weak:time", 3, None, "'시간 복잡도'가 3주 연속 지적되고 있어요 (꾸준히 지적되는 약점)")]
    growth.save_snapshot(gw.settings, s1)
    gw.resize(720, 480)
    p = page_of(gw)
    p.refresh()
    assert p.scroll.widgetResizable() and p.scroll.verticalScrollBar().maximum() > 0  # 길면 스크롤
    assert p.scroll.horizontalScrollBar().maximum() == 0  # 가로 잘림 없음


# --- 설정 카드 -----------------------------------------------------------------------------------------


def test_settings_growth_card_writes_env_and_reloads(gw, valid_config):
    sp = gw.settings_page
    assert sp.growth_enabled.isChecked() and sp.growth_comment.isChecked() and sp.growth_comment.isEnabled()
    got = []
    sp.coach_settings_changed.connect(lambda: got.append(1))
    sp.growth_comment.setChecked(False)
    assert config.read_env_file(valid_config)["SWEA_GROWTH_COMMENT"] == "0" and gw.settings.growth_comment is False
    sp.growth_enabled.setChecked(False)
    env = config.read_env_file(valid_config)
    assert env["SWEA_GROWTH"] == "0" and gw.settings.growth is False and not sp.growth_comment.isEnabled() and len(got) == 2
    sp.growth_enabled.setChecked(True)
    assert config.read_env_file(valid_config)["SWEA_GROWTH"] == "1" and sp.growth_comment.isEnabled() and gw.settings.growth is True


def test_settings_loaded_values_reflect_env(gw, valid_config):
    set_growth_env(gw, SWEA_GROWTH="1", SWEA_GROWTH_COMMENT="0")
    sp = gw.settings_page
    assert sp.growth_enabled.isChecked() and not sp.growth_comment.isChecked() and sp.growth_comment.isEnabled()


def test_clear_growth_button_only_clears_profile(gw, monkeypatch, valid_config):
    from swea_fetcher import coach
    from swea_fetcher.submit import SubmitResult

    s = gw.settings
    live_events(s)
    coach.record_submit(s, 1234, "sim", "t", SubmitResult(False, "오답"))
    sp = gw.settings_page
    monkeypatch.setattr(settings_page_mod, "QMessageBox", FakeBox)
    FakeBox.choose = "취소"
    sp.growth_clear_btn.click()
    assert (valid_config / "coach" / "profile").exists()
    FakeBox.choose = "지우기"
    sp.growth_clear_btn.click()
    assert "성장 리포트·분류 기록·풀이 잔디가 삭제됩니다" in FakeBox.made[-1].text
    assert not (valid_config / "coach" / "profile").exists() and (valid_config / "coach" / "records.json").exists()
    assert gw.growth_page.stack.currentWidget() is gw.growth_page.empty or not gw.growth_page.isVisible()


def test_ai_clear_confirmation_mentions_growth(gw, monkeypatch):
    monkeypatch.setattr(settings_page_mod, "QMessageBox", FakeBox)
    FakeBox.choose = "취소"
    gw.settings_page.ai_clear_btn.click()
    assert "성장 기록" in FakeBox.made[-1].text


def test_consent_text_mentions_growth_tags_and_reset_clears_growth_consent(main_window):
    assert "분류 태그(코드 제외)가 성장 기록으로 저장됩니다" in coach_widgets.consent_text("GPT (Codex)")
    assert "성장 기록" not in coach_widgets.consent_text("GPT (Codex)", ping=True)  # 연결 테스트는 태그를 받지 않는다
    qs = main_window.qs
    coach_widgets.set_growth_consent(qs, "claude")
    assert coach_widgets.growth_consent_ok(qs, "claude") and not coach_widgets.growth_consent_ok(qs, "codex")
    coach_widgets.reset_consents(qs)
    assert not coach_widgets.growth_consent_ok(qs, "claude")


# --- 코치 탭 팁 ------------------------------------------------------------------------------------------


def test_coach_tab_shows_growth_tip_once_and_hides_on_new_request(qtbot):
    from swea_fetcher.gui.coach_widgets import CoachTab

    tab = CoachTab()
    qtbot.addWidget(tab)
    tab.show()
    assert tab.tip.isHidden()
    tip = "성장 팁 · 최근 3번 연속 '경계·예외 조건'이 지적됐어요. 제출 전에 최솟값·최댓값·빈 경우를 한 번씩 돌려 보세요"
    tab.show_growth_tip(tip)
    assert not tab.tip.isHidden() and tab.tip.text() == tip
    tab.begin([CODEX], (), None, "review", 1)
    assert tab.tip.isHidden()
    tab.show_growth_tip(None)
    assert tab.tip.isHidden()


def test_check_page_passes_growth_tip_to_tab(gw):
    cp = gw.check_page
    res = CoachResult("review", [EngineOutcome("codex", "GPT (Codex)", CoachAnswer("review", "## 총평\nx", "GPT (Codex)", "codex"))], growth_tip="성장 팁 · 테스트")
    cp._on_coach_done(res)
    assert cp.coach_tab.tip.text() == "성장 팁 · 테스트" and not cp.coach_tab.tip.isHidden()
    cp._on_coach_done(CoachResult("review", [EngineOutcome("codex", "GPT (Codex)", CoachAnswer("review", "x", "GPT (Codex)", "codex"))]))
    assert cp.coach_tab.tip.isHidden()
