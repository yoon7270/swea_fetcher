"""GUI AI 코치 (M17): 코치 바 상태, 동의 게이트, AI 탭, 취소/실패 배너, 복습 카드·배지, 설정 섹션.

service.ask_coach / resolve_engine 은 대체한다 — 실제 CLI·네트워크 호출 0.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl

from swea_fetcher import checker, coach, config, service
from swea_fetcher.ai_engine import EngineInfo
from swea_fetcher.errors import AiEngineMissing, AiRunFailed, AiTimeout
from swea_fetcher.gui import coach_widgets
from swea_fetcher.gui.coach_widgets import AnswerBrowser, CoachBar
from swea_fetcher.gui.pages import check_page as check_page_mod
from swea_fetcher.gui.pages import settings_page as settings_page_mod
from swea_fetcher.service import CoachAnswer
from swea_fetcher.submit import SubmitResult

WAIT = 8000
CODEX = EngineInfo("codex", "C:/c/codex.cmd")


def shown(w) -> bool:
    return not w.isHidden()


# --- 코치 바 (위젯 단위) ---------------------------------------------------------------------


def test_bar_pass_state(qtbot):
    bar = CoachBar()
    qtbot.addWidget(bar)
    bar.show_pass()
    assert "Pass!" in bar.text.text() and "평가" in bar.text.text()
    assert (shown(bar.review_btn), shown(bar.hint_btn), shown(bar.solution_btn), shown(bar.later_btn)) == (True, False, False, False)


def test_bar_wrong_below_threshold_hides_solution(qtbot):
    bar = CoachBar()
    qtbot.addWidget(bar)
    bar.show_wrong(2, 3, 3, False)
    assert bar.text.text() == "이 문제 오답 2회"
    assert shown(bar.hint_btn) and not shown(bar.solution_btn) and not shown(bar.later_btn) and not shown(bar.review_btn)
    assert bar.hint_btn.accessibleName() == "힌트 받기" and not bar.hint_btn.icon().isNull()


def test_bar_offer_and_dismissed(qtbot):
    bar = CoachBar()
    qtbot.addWidget(bar)
    bar.show_wrong(3, 3, 5, False)
    assert "3번 틀렸어요" in bar.text.text() and "5일 뒤" in bar.text.text()
    assert shown(bar.hint_btn) and shown(bar.solution_btn) and shown(bar.later_btn)
    bar.show_wrong(3, 3, 5, True)  # [다음에] 이후: 문장은 사라지고 버튼은 유지
    assert bar.text.text() == "이 문제 오답 3회" and shown(bar.solution_btn) and not shown(bar.later_btn)


def test_bar_hint_progress_and_requesting(qtbot):
    bar = CoachBar()
    qtbot.addWidget(bar)
    bar.show_wrong(1, 3, 3, False, hint_done=1)
    assert bar.hint_btn.text() == "다음 힌트 (2/3)"
    bar.set_hint_done(3)
    assert bar.hint_btn.text() == "힌트 (3/3)" and not bar.hint_btn.isEnabled() and "3단계" in bar.hint_btn.toolTip()
    bar.show_wrong(4, 3, 3, False, hint_done=0)
    bar.set_requesting(True)
    assert not any(b.isEnabled() for b in (bar.hint_btn, bar.solution_btn, bar.later_btn))
    bar.set_requesting(False)
    assert bar.hint_btn.isEnabled() and bar.solution_btn.isEnabled()


def test_bar_zero_wrong_text_depends_on_solution_viewed(qtbot):
    bar = CoachBar()
    qtbot.addWidget(bar)
    bar.show_wrong(0, 3, 3, False)  # 기록 없음 → 풀이를 봤다고 말하지 않는다
    assert bar.text.text() == "오답이에요. 힌트를 받아 보세요"
    bar.show_wrong(0, 3, 3, False, solution_viewed=True)
    assert bar.text.text().startswith("정답 풀이를 확인했어요")


def test_bar_local_failure_text(qtbot):
    bar = CoachBar()
    qtbot.addWidget(bar)
    bar.show_wrong(0, 3, 3, False, local=True)
    assert "로컬 검증에 실패" in bar.text.text() and shown(bar.hint_btn) and not shown(bar.solution_btn)


# --- AnswerBrowser 가드 -----------------------------------------------------------------------


def test_answer_browser_blocks_resources_and_links(qtbot, monkeypatch):
    requested = []
    orig = AnswerBrowser.loadResource

    def spy(self, t, url):
        requested.append(url.toString())
        return orig(self, t, url)

    monkeypatch.setattr(AnswerBrowser, "loadResource", spy)
    b = AnswerBrowser()
    qtbot.addWidget(b)
    b.set_markdown('## 제목\n\n<img src="http://evil.example/x.png"> ![p](https://evil.example/p.png)\n\n[링크](https://evil.example)\n\n```\ncode\n```')
    b.show()
    qtbot.wait(50)
    assert not b.openLinks() and not b.openExternalLinks()
    assert b.loadResource(2, QUrl("http://evil.example/x.png")) is None
    assert "제목" in b.toPlainText() and "code" in b.toPlainText()
    assert '<img src="http://evil.example/x.png">' in b.toPlainText()  # raw HTML 은 렌더링되지 않고 글자로 보인다 (마크다운 이미지 문법은 loadResource=None 으로 막힘)
    b.set_markdown("앞 <br> 뒤 <details>본문</details> 끝")
    assert "뒤" in b.toPlainText() and "끝" in b.toPlainText()  # 기본 모드처럼 태그 뒤 본문이 사라지지 않는다 (R12 실측)
    assert all(orig(b, 2, QUrl(u)) is None for u in requested)  # Qt 가 무엇을 요청하든 항상 None


# --- 검증 탭 통합 -----------------------------------------------------------------------------


class Coach:
    """service.ask_coach / resolve_engine / 동의 대화상자 대역."""

    def __init__(self):
        self.calls: list[dict] = []
        self.answers: list = []  # CoachAnswer 또는 예외 (순서대로, 마지막은 반복)
        self.block_until_cancelled = False
        self.consent_asked = 0
        self.consent_reply = True
        self.engine = CODEX
        self.missing = False

    def resolve(self, settings):
        if self.missing:
            raise AiEngineMissing("없음", hint="설치하세요")
        return self.engine

    def ask(self, settings, kind, topic="", num=0, **kw):
        self.calls.append({"kind": kind, "topic": topic, "num": num, **{k: v for k, v in kw.items() if k in ("force_new", "submit_summary", "run_error")}})
        if self.block_until_cancelled:
            end = time.time() + 6
            while time.time() < end and not kw["is_cancelled"]():
                time.sleep(0.02)
            return CoachAnswer(kind, "", "Codex", cancelled=True)
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return a

    def consent(self, parent, label, ping=False):
        self.consent_asked += 1
        return self.consent_reply


@pytest.fixture
def fake(monkeypatch):
    c = Coach()
    c.answers = [CoachAnswer("review", "## 총평\n좋아요", "Codex")]
    monkeypatch.setattr(service, "ask_coach", c.ask)
    monkeypatch.setattr(service, "resolve_engine", c.resolve)
    monkeypatch.setattr(check_page_mod, "ask_consent", c.consent)
    monkeypatch.setattr(settings_page_mod, "ask_consent", c.consent)
    return c


@pytest.fixture
def cp(main_window):
    """검증 페이지 + 풀이 폴더 sim/1234. 제출 직후 상태를 흉내 낸다."""
    d = main_window.settings.root / "sim" / "1234"
    d.mkdir(parents=True)
    (d / "1234.py").write_text("# 1234. A+B\nprint(1)\n", encoding="utf-8")
    page = main_window.check_page
    page._last_target = ("sim", 1234)
    return page


def _submit_result(passed: bool, **kw) -> SubmitResult:
    return SubmitResult(passed, "Pass" if passed else "오답: 10개 테스트케이스 중 7개 통과", **kw)


def _wait_done(qtbot, page):
    qtbot.waitUntil(lambda: page._coach_worker is None, timeout=WAIT)


def _click_and_wait(qtbot, page, btn):
    btn.click()
    _wait_done(qtbot, page)


def test_no_ai_call_without_click(cp, fake):
    """AC1: 결과 뒤 코치 바만 보이고 클릭 전에는 어떤 AI 호출도 없다."""
    cp._coach_after_submit(_submit_result(True))
    assert shown(cp.coach_bar) and shown(cp.coach_bar.review_btn)
    assert fake.calls == [] and cp._coach_worker is None and fake.consent_asked == 0


def test_consent_cancel_blocks_call(qtbot, cp, fake):
    cp._coach_after_submit(_submit_result(True))
    fake.consent_reply = False
    cp.coach_bar.review_btn.click()
    assert fake.consent_asked == 1 and fake.calls == [] and cp._coach_worker is None
    assert not coach_widgets.has_consent(cp.qs, "codex")


def test_consent_once_per_engine_then_reset(qtbot, cp, fake):
    cp._coach_after_submit(_submit_result(True))
    _click_and_wait(qtbot, cp, cp.coach_bar.review_btn)
    assert fake.consent_asked == 1 and len(fake.calls) == 1 and coach_widgets.has_consent(cp.qs, "codex")
    _click_and_wait(qtbot, cp, cp.coach_bar.review_btn)
    assert fake.consent_asked == 1 and len(fake.calls) == 2  # 다시 묻지 않음
    fake.engine = EngineInfo("claude", "C:/c/claude.exe")  # 엔진(벤더)이 바뀌면 다시 동의
    _click_and_wait(qtbot, cp, cp.coach_bar.review_btn)
    assert fake.consent_asked == 2
    coach_widgets.reset_consents(cp.qs)  # 설정의 [동의 초기화]
    fake.engine = CODEX
    _click_and_wait(qtbot, cp, cp.coach_bar.review_btn)
    assert fake.consent_asked == 3


def test_answer_tab_added_and_stack_switched(qtbot, cp, fake):
    cp.stack.setCurrentIndex(0)  # 제출만 하고 로컬 실행이 없는 상태 (빈 화면)
    cp._coach_after_submit(_submit_result(True))
    _click_and_wait(qtbot, cp, cp.coach_bar.review_btn)
    assert cp.stack.currentIndex() == 1 and cp.tabs.currentWidget() is cp.coach_tab
    assert cp.tabs.tabText(cp.tabs.indexOf(cp.coach_tab)) == "AI 코치"
    assert "총평" in cp.coach_tab.browser.toPlainText() and "Codex" in cp.coach_tab.header.text()
    assert not shown(cp.coach_tab.cache_badge)
    assert cp.busy.isHidden()


def test_cached_badge_and_retry_forces_new(qtbot, cp, fake):
    fake.answers = [CoachAnswer("review", "캐시 응답", "Codex", from_cache=True)]
    cp._coach_after_submit(_submit_result(True))
    _click_and_wait(qtbot, cp, cp.coach_bar.review_btn)
    assert shown(cp.coach_tab.cache_badge)
    cp.coach_tab.retry_btn.click()
    _wait_done(qtbot, cp)
    assert fake.calls[-1]["force_new"] is True and fake.calls[-1]["kind"] == "review"


def test_local_check_keeps_ai_tab_and_shows_hint(qtbot, cp, fake):
    cp._coach_after_submit(_submit_result(True))
    _click_and_wait(qtbot, cp, cp.coach_bar.review_btn)
    res = checker.CheckResult(False, "a\n", "b\n", "", 0.1, False, [("changed", "a", "b")])
    cp._on_done(res)  # 새 로컬 실행 결과 — AI 탭은 남아야 한다
    assert cp.tabs.indexOf(cp.coach_tab) >= 0 and cp.tabs.currentWidget() is cp.diff
    assert shown(cp.coach_bar) and shown(cp.coach_bar.hint_btn) and "로컬 검증" in cp.coach_bar.text.text()
    _click_and_wait(qtbot, cp, cp.coach_bar.hint_btn)  # B: 로컬 검증 실패에도 힌트
    assert fake.calls[-1]["kind"] == "hint" and "로컬 검증 실패" in fake.calls[-1]["submit_summary"]
    ok = checker.CheckResult(True, "a\n", "a\n", "", 0.1, False, [("same", "a", "a")])
    cp._on_done(ok)
    assert cp.coach_bar.isHidden()


def test_local_timeout_and_runtime_error_summaries(cp, fake):
    cp._on_done(checker.CheckResult(False, "a\n", "", "", 10.0, True, []))
    assert "제한시간 초과" in cp._coach_judge[0]
    cp._on_done(checker.CheckResult(False, "a\n", "", "Traceback\nIndexError: list index out of range", 0.1, False, [("missing", "a", None)], returncode=1))
    assert "런타임 에러" in cp._coach_judge[0] and cp._coach_judge[1].startswith("IndexError")


def test_hint_progression_in_bar(qtbot, cp, fake, monkeypatch):
    fake.answers = [CoachAnswer("hint", f"힌트 {n}", "Codex", level=n, max_level=3) for n in (1, 2, 3)]
    cp._coach_after_submit(_submit_result(False))
    assert cp.coach_bar.hint_btn.text() == "힌트"
    _click_and_wait(qtbot, cp, cp.coach_bar.hint_btn)
    assert cp.coach_bar.hint_btn.text() == "다음 힌트 (2/3)"
    assert fake.calls[0]["submit_summary"].startswith("오답")
    _click_and_wait(qtbot, cp, cp.coach_bar.hint_btn)
    _click_and_wait(qtbot, cp, cp.coach_bar.hint_btn)
    assert cp.coach_bar.hint_btn.text() == "힌트 (3/3)" and not cp.coach_bar.hint_btn.isEnabled()
    assert len(fake.calls) == 3


def test_solution_flow_emits_coach_changed_and_shows_review(qtbot, cp, fake):
    due = date.today() + timedelta(days=3)
    fake.answers = [CoachAnswer("solution", "## 정답 코드\n```python\nprint(1)\n```", "Codex", review_due=due, code="print(1)")]
    for _ in range(3):
        coach.record_submit(cp.settings, 1234, "sim", "A+B", SubmitResult(False, "오답"))
    cp._coach_after_submit(_submit_result(False))
    assert shown(cp.coach_bar.solution_btn) and shown(cp.coach_bar.later_btn)
    with qtbot.waitSignal(cp.coach_changed, timeout=WAIT):
        cp.coach_bar.solution_btn.click()
    _wait_done(qtbot, cp)
    assert f"복습 예정: {due.isoformat()}" in cp.coach_tab.info.text()
    assert shown(cp.coach_tab.copy_btn) and "저장되지 않습니다" in cp.coach_tab.footer.text()
    cp.coach_tab.copy_btn.click()
    from PySide6.QtGui import QGuiApplication

    assert QGuiApplication.clipboard().text() == "print(1)"


def test_dismiss_offer_keeps_solution_button(cp, fake):
    for _ in range(3):
        coach.record_submit(cp.settings, 1234, "sim", "A+B", SubmitResult(False, "오답"))
    cp._coach_after_submit(_submit_result(False))
    assert shown(cp.coach_bar.later_btn)
    cp.coach_bar.later_btn.click()
    assert not shown(cp.coach_bar.later_btn) and shown(cp.coach_bar.solution_btn)
    assert coach.get_record(cp.settings, 1234).offer_dismissed


def test_engine_missing_banner(cp, fake):
    fake.missing = True
    cp._coach_after_submit(_submit_result(True))
    cp.coach_bar.review_btn.click()
    assert shown(cp.banner) and "AI 엔진을 찾지 못했습니다" in cp.banner.title.text()
    assert cp.banner.action.text() == "설정으로 이동" and "설치하세요" in cp.banner.body.text()
    assert fake.calls == [] and cp._coach_worker is None and cp.tabs.indexOf(cp.coach_tab) < 0
    got = []
    cp.goto_requested.connect(got.append)
    cp.banner.action.click()
    assert got == ["settings"]


@pytest.mark.parametrize("exc", [AiRunFailed("Codex 실행 실패 (코드 1)", hint="로그인하세요\n\nstderr"), AiTimeout("300초 초과")])
def test_failure_banner_with_retry(qtbot, cp, fake, exc):
    fake.answers = [exc, CoachAnswer("review", "복구됨", "Codex")]
    cp._coach_after_submit(_submit_result(True))
    _click_and_wait(qtbot, cp, cp.coach_bar.review_btn)
    assert shown(cp.banner) and str(exc) in cp.banner.title.text()
    assert cp.banner.action.text() == "다시 시도" and cp.tabs.indexOf(cp.coach_tab) < 0
    cp.banner.action.click()
    _wait_done(qtbot, cp)
    assert "복구됨" in cp.coach_tab.browser.toPlainText()


def test_cancel_returns_info_banner(qtbot, cp, fake):
    fake.block_until_cancelled = True
    cp._coach_after_submit(_submit_result(True))
    cp.coach_bar.review_btn.click()
    qtbot.waitUntil(lambda: cp._coach_worker is not None and len(fake.calls) == 1, timeout=WAIT)
    assert not cp.busy.isHidden() and not cp.coach_bar.review_btn.isEnabled()  # 요청 중 버튼 비활성
    assert "묻는 중" in cp.coach_tab.loading_label.text()
    cp.coach_tab.cancel_btn.click()
    _wait_done(qtbot, cp)
    assert "취소" in cp.banner.title.text() and cp.tabs.indexOf(cp.coach_tab) < 0
    assert cp.coach_bar.review_btn.isEnabled() and cp.busy.isHidden()


def test_wait_workers_cancels_ai_first(qtbot, cp, fake):
    fake.block_until_cancelled = True
    cp._coach_after_submit(_submit_result(True))
    cp.coach_bar.review_btn.click()
    qtbot.waitUntil(lambda: len(fake.calls) == 1, timeout=WAIT)
    t0 = time.time()
    cp.wait_workers(3000)
    assert time.time() - t0 < 3 and not cp._coach_worker.isRunning()


def test_busy_bar_shown_while_any_worker_runs(cp):
    cp._coach_worker = object()  # AI 워커만 돌고 있는 상황에서 다른 워커 종료 경로가 막대를 끄지 않는다
    cp._sync_busy()
    assert not cp.busy.isHidden()
    cp._coach_worker = None
    cp._sync_busy()
    assert cp.busy.isHidden()


def test_submit_done_records_and_shows_bar(cp, fake):
    from swea_fetcher.service import SubmitOutcome

    got = []
    cp.coach_changed.connect(lambda: got.append(1))
    cp._on_submit_done(SubmitOutcome(_submit_result(True), None, [], "CID"))
    assert shown(cp.coach_bar.review_btn) and got == [1]
    cp._on_submit_done(SubmitOutcome(_submit_result(False), None, [], "CID"))
    assert shown(cp.coach_bar.hint_btn) and not shown(cp.coach_bar.review_btn)


# --- 복습 카드 · 배지 -------------------------------------------------------------------------


def _review(settings, num, days_ahead, title="제목"):
    """오늘 기준 days_ahead 일 뒤가 복습일이 되도록 예약 (음수 = 이미 지남)."""
    coach.record_submit(settings, num, "sim", title, SubmitResult(False, "오답"))
    coach.mark_solution_viewed(settings, num, 1, today=date.today() + timedelta(days=days_ahead - 1))


def test_review_card_items_and_dismiss(qtbot, main_window):
    hp = main_window.history_page
    s = main_window.settings
    _review(s, 101, -2, "지남")
    _review(s, 102, 0, "오늘")
    _review(s, 103, 3, "예정")
    hp.refresh()
    assert shown(hp.review_card)
    texts = [lab.text() for lab in hp.review_card.findChildren(type(hp.count_label))]
    assert "· 2일 지남" in texts and "· 오늘 복습" in texts and "· 3일 뒤" in texts
    from PySide6.QtWidgets import QToolButton

    with qtbot.waitSignal(hp.reviews_changed, timeout=2000):
        hp.review_card.findChildren(QToolButton)[0].click()  # 가장 오래 밀린 항목의 [✕]
    assert [i.num for i in service.review_items(s)] == [102, 103]


def test_review_card_more_and_hidden_when_empty(main_window):
    hp = main_window.history_page
    s = main_window.settings
    hp.refresh()
    assert hp.review_card.isHidden()
    for n in range(1, 8):
        _review(s, 200 + n, n)
    hp.refresh()
    from PySide6.QtWidgets import QPushButton

    links = [b for b in hp.review_card.findChildren(QPushButton)]
    assert len(links) == 5 and any("외 2개" in lab.text() for lab in hp.review_card.findChildren(type(hp.count_label)))


def test_review_card_click_targets_check_tab(main_window):
    s = main_window.settings
    _review(s, 301, 0, "복습 대상")
    hp = main_window.history_page
    hp.refresh()
    from PySide6.QtWidgets import QPushButton

    hp.review_card.findChildren(QPushButton)[0].click()
    assert main_window.check_page.num.text() == "301" and main_window.check_page.topic.currentText() == "sim"


def test_badge_and_startup_message(main_window):
    s = main_window.settings
    assert main_window.review_badge.isHidden()
    _review(s, 401, -1)
    _review(s, 402, 5)  # 아직 도래 전 — 세지 않음
    main_window._refresh_review_badge(startup=True)
    assert shown(main_window.review_badge) and main_window.review_badge.text() == "복습 1개 ↗"
    assert "복습할 문제 1개" in main_window.statusBar().currentMessage()
    service.dismiss_review(s, 401)
    main_window._refresh_review_badge()
    assert main_window.review_badge.isHidden()


def test_badge_updates_on_coach_changed(main_window):
    _review(main_window.settings, 501, 0)
    main_window.check_page.coach_changed.emit()
    assert shown(main_window.review_badge)


# --- 설정 섹션 --------------------------------------------------------------------------------


class FakeBox:
    choose = "지우기"

    class Icon:
        Warning = 2

    class ButtonRole:
        DestructiveRole = 2
        RejectRole = 1

    def __init__(self, icon, title, body, parent=None):
        self.buttons, self.body = {}, body

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


def test_settings_engine_and_numbers_saved_to_env(main_window, valid_config):
    sp = main_window.settings_page
    got = []
    sp.coach_settings_changed.connect(lambda: got.append(1))
    sp.ai_engine.setCurrentIndex(sp.ai_engine.findData("claude"))
    sp.ai_threshold.setValue(5)
    sp.ai_threshold.editingFinished.emit()
    sp.review_days.setValue(7)
    sp.review_days.editingFinished.emit()
    env = config.read_env_file(valid_config)
    assert env["SWEA_AI_ENGINE"] == "claude" and env["SWEA_AI_WRONG_THRESHOLD"] == "5" and env["SWEA_REVIEW_DAYS"] == "7"
    assert len(got) == 3
    assert (main_window.settings.ai_engine, main_window.settings.ai_wrong_threshold, main_window.settings.review_days) == ("claude", 5, 7)
    assert main_window.check_page.settings is main_window.settings  # 입력창은 건드리지 않고 설정 객체만 교체


def test_settings_loaded_values_shown(main_window):
    sp = main_window.settings_page
    assert sp.ai_engine.currentData() == "auto" and sp.ai_threshold.value() == 3 and sp.review_days.value() == 3
    assert sp.ai_threshold.suffix() == " 회" and sp.review_days.suffix() == " 일"


def test_settings_detect_status(qtbot, main_window, monkeypatch):
    st = service.EngineStatus([EngineInfo("codex", "C:/c/codex.cmd", "codex-cli 0.9.1"), EngineInfo("claude", "", "", False, "없음")], ["OPENAI_API_KEY"])
    monkeypatch.setattr(service, "detect_engines", lambda settings=None: st)
    sp = main_window.settings_page
    sp._detect_ai()
    qtbot.waitUntil(lambda: sp._ai_detect_worker is None, timeout=WAIT)
    assert "Codex codex-cli 0.9.1 감지됨" in sp.ai_status.text() and "Claude Code 없음" in sp.ai_status.text()
    assert shown(sp.ai_note) and "OPENAI_API_KEY" in sp.ai_note.text()


def test_settings_detect_none_installed_shows_install_hint(qtbot, main_window, monkeypatch):
    st = service.EngineStatus([EngineInfo("codex", "", "", False), EngineInfo("claude", "", "", False)], [])
    monkeypatch.setattr(service, "detect_engines", lambda settings=None: st)
    sp = main_window.settings_page
    sp._detect_ai()
    qtbot.waitUntil(lambda: sp._ai_detect_worker is None, timeout=WAIT)
    assert "npm" in sp.ai_note.text() and "다시 켜" in sp.ai_note.text()


def test_ping_success_and_failure_banners(qtbot, main_window, fake):
    sp = main_window.settings_page
    fake.answers = [CoachAnswer("ping", "OK", "Codex", elapsed=2.1)]
    sp.ai_test_btn.click()
    qtbot.waitUntil(lambda: sp._ai_ping_worker is None and shown(sp.banner), timeout=WAIT)
    assert fake.calls[0]["kind"] == "ping" and "Codex 연결됨 (2.1초)" in sp.banner.title.text()
    assert not coach_widgets.has_consent(sp.qs, "codex")  # 테스트 문장 동의는 엔진 동의로 저장하지 않는다
    fake.answers = [AiRunFailed("Codex 실행 실패 (코드 2)", hint="실행한 명령: codex exec --bogus\n\nunknown option")]
    sp.ai_test_btn.click()
    qtbot.waitUntil(lambda: sp._ai_ping_worker is None and "실패" in sp.banner.title.text(), timeout=WAIT)
    assert "codex exec --bogus" in sp.banner.body.text() and "unknown option" in sp.banner.body.text()


def test_ping_consent_cancel_and_missing_engine(main_window, fake):
    sp = main_window.settings_page
    fake.consent_reply = False
    sp.ai_test_btn.click()
    assert fake.calls == [] and sp._ai_ping_worker is None
    fake.missing = True
    sp.ai_test_btn.click()
    assert "AI 엔진을 찾지 못했습니다" in sp.banner.title.text()


def test_consent_reset_and_clear_records(main_window, monkeypatch, valid_config):
    sp = main_window.settings_page
    coach_widgets.set_consent(sp.qs, "codex")
    sp.ai_consent_reset_btn.click()
    assert not coach_widgets.has_consent(sp.qs, "codex")
    _review(main_window.settings, 601, 1)
    monkeypatch.setattr(settings_page_mod, "QMessageBox", FakeBox)
    FakeBox.choose = "취소"
    sp.ai_clear_btn.click()
    assert service.review_items(main_window.settings)  # 취소하면 그대로
    FakeBox.choose = "지우기"
    got = []
    sp.coach_settings_changed.connect(lambda: got.append(1))
    sp.ai_clear_btn.click()
    assert service.review_items(main_window.settings) == [] and not (valid_config / "coach").exists() and got == [1]
    assert main_window.review_badge.isHidden()


def test_coach_dir_and_engine_module_have_no_root_writes(main_window, cp, fake, qtbot):
    """정답 풀이 흐름 뒤에도 루트 폴더에는 새 파일이 생기지 않는다 (기록은 config_dir/coach)."""
    before = sorted(p.relative_to(main_window.settings.root).as_posix() for p in main_window.settings.root.rglob("*"))
    fake.answers = [CoachAnswer("solution", "## 정답 코드\n```\nprint(2)\n```", "Codex", code="print(2)")]
    for _ in range(3):
        coach.record_submit(cp.settings, 1234, "sim", "A+B", SubmitResult(False, "오답"))
    cp._coach_after_submit(_submit_result(False))
    _click_and_wait(qtbot, cp, cp.coach_bar.solution_btn)
    after = sorted(p.relative_to(main_window.settings.root).as_posix() for p in main_window.settings.root.rglob("*"))
    assert before == after
