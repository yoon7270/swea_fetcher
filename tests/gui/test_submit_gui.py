"""GUI [SWEA 제출] 흐름 (M8/M9). 확인 다이얼로그는 QMessageBox 대역으로, 제출은 service 스텁 또는 FakeSession 으로.

실서버 호출 0. 공통 assert: 화면·로그 어디에도 비밀번호/쿠키 문자열이 없다.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from swea_fetcher import config, service
from swea_fetcher.errors import SubmitError
from swea_fetcher.gitops import GitResult, RepoInfo
from swea_fetcher.gui import workers
from swea_fetcher.gui.pages import check_page as check_page_mod
from swea_fetcher.gui.pages import history_page as history_page_mod
from swea_fetcher.service import SubmitOutcome
from swea_fetcher.submit import SubmitResult
from tests.conftest import CONTEST_PROB_ID, DUMMY_ID, DUMMY_PW, FIXTURE_DIR, FakeResponse, FakeSession

ID = CONTEST_PROB_ID
BOX_ID = "AZ-xsmtqr73HBIS2"
WAIT = 8000
COOKIE = "supersecretcookievalue"


# --- 대역 ------------------------------------------------------------------------------


class FakeMessageBox:
    """check_page.QMessageBox 대역. 생성 인자를 기록하고, exec 없이 미리 정한 버튼을 '클릭'한 것으로 처리."""

    instances: list["FakeMessageBox"] = []
    choose: str = "제출"  # 클릭할 버튼 라벨

    class Icon:
        Question = 4
        Warning = 2

    class ButtonRole:
        AcceptRole = 0
        RejectRole = 1
        DestructiveRole = 2

    def __init__(self, icon, title, body, parent=None):
        self.title, self.body, self.buttons = title, body, {}
        FakeMessageBox.instances.append(self)

    def addButton(self, label, role):  # noqa: N802
        btn = object()
        self.buttons[label] = btn
        return btn

    def setDefaultButton(self, b):  # noqa: N802
        self.default = b

    def setEscapeButton(self, b):  # noqa: N802
        self.escape = b

    def exec(self):
        return 0

    def clickedButton(self):  # noqa: N802
        return self.buttons.get(FakeMessageBox.choose)


@pytest.fixture(autouse=True)
def fake_msgbox(monkeypatch):
    FakeMessageBox.instances = []
    FakeMessageBox.choose = "제출"
    monkeypatch.setattr(check_page_mod, "QMessageBox", FakeMessageBox)
    return FakeMessageBox


def _result(passed: bool, **kw) -> SubmitResult:
    base = dict(summary="Pass" if passed else "오답: 10개 테스트케이스 중 7개 통과", score="100.00" if passed else "70.00",
                test_cases=10, corrected=10 if passed else 7, execution_time="0.123 ms",
                raw={"result": "success", "vo": {"runValue": "Pass " if passed else "Fail ", "usrScore": "100.00" if passed else "70.00"}})
    base.update(kw)
    return SubmitResult(passed, **base)


@pytest.fixture
def submit_stub(monkeypatch):
    """service.submit_problem 스텁 (워커 스레드에서 호출됨)."""
    st = {"result": _result(True), "git": None, "raise": None, "calls": []}

    def fake(settings, topic, num, *, push=False, message=None, progress=None):
        st["calls"].append({"topic": topic, "num": num, "push": push})
        if progress:
            progress("제출 대상: 모의/클럽 상자 · Queue")
        if st["raise"]:
            raise st["raise"]
        git = st["git"] if push and st["result"].passed else None
        return SubmitOutcome(st["result"], git, ["`import sys` 줄을 빼고 제출합니다"], ID)

    monkeypatch.setattr(service, "submit_problem", fake)
    return st


@pytest.fixture
def solved(main_window) -> Path:
    d = main_window.settings.root / "sim" / "1234"
    d.mkdir(parents=True)
    (d / "input.txt").write_text("1\n2 3\n", encoding="utf-8")
    (d / "output.txt").write_text("#1 5\n", encoding="utf-8")
    (d / "1234.py").write_text("# 1234. A+B\nimport sys\nsys.stdin = open('input.txt', 'r')\nprint('#1 5')\n", encoding="utf-8")
    return d


def _no_secrets(*texts: str):
    for t in texts:
        assert DUMMY_PW not in t and COOKIE not in t, "비밀번호/쿠키 문자열이 화면에 노출됨"


def _wait_submit(qtbot, cp):
    qtbot.waitUntil(lambda: cp._submit_worker is not None, timeout=WAIT)
    qtbot.waitUntil(lambda: cp._submit_worker is None, timeout=WAIT)


# =============================================================================
# 확인 다이얼로그
# =============================================================================


def test_confirm_dialog_text_and_cancel(main_window, solved, submit_stub, fake_msgbox):
    cp = main_window.check_page
    fake_msgbox.choose = "취소"
    cp.set_target("sim", 1234)
    cp.request_submit()
    assert len(fake_msgbox.instances) == 1
    box = fake_msgbox.instances[0]
    assert box.title == "SWEA 제출"
    assert "제출 가능 횟수가 1회 감소" in box.body and "sim/1234/1234.py" in box.body
    assert "[커밋 + 푸시] 버튼" in box.body and "확인 없이" not in box.body  # 자동 모드 아님
    assert set(box.buttons) == {"제출", "취소"}
    assert box.default is box.buttons["제출"] and box.escape is box.buttons["취소"]
    assert submit_stub["calls"] == [] and cp._submit_worker is None
    assert cp.submit_btn.isEnabled() and cp.submit_btn.text() == "SWEA 제출"


def test_confirm_dialog_mentions_auto_push_when_enabled(main_window, solved, submit_stub, fake_msgbox, qtbot):
    cp = main_window.check_page
    cp.set_settings(replace(main_window.settings, auto_push_on_pass=True))
    fake_msgbox.choose = "취소"
    cp.set_target("sim", 1234)
    cp.request_submit()
    assert "확인 없이 커밋 + 푸시" in fake_msgbox.instances[0].body


def test_no_dialog_without_solution_file(main_window, submit_stub, fake_msgbox):
    cp = main_window.check_page
    cp.set_target("sim", 4321)
    cp.request_submit()
    assert fake_msgbox.instances == [] and submit_stub["calls"] == []
    assert "4321.py 가 없습니다" in cp.banner.title.text()


def test_no_dialog_without_settings(main_window_no_config, submit_stub, fake_msgbox):
    cp = main_window_no_config.check_page
    cp.request_submit("sim", 1)
    assert fake_msgbox.instances == [] and submit_stub["calls"] == []
    assert "설정이 없습니다" in cp.banner.title.text()


def test_no_dialog_with_invalid_form(main_window, submit_stub, fake_msgbox):
    cp = main_window.check_page
    cp.topic.setCurrentText("sim")
    cp.num.setText("abc")
    cp.request_submit()
    assert fake_msgbox.instances == [] and "숫자" in cp.err_label.text()


# =============================================================================
# Pass / 오답 / 실패
# =============================================================================


def test_pass_manual_mode_shows_push_banner_and_does_not_push(main_window, solved, submit_stub, qtbot):
    w = main_window
    cp = w.check_page
    cp.set_target("sim", 1234)
    cp.request_submit()
    assert cp.submit_btn.text() == "채점 중…" and not cp.submit_btn.isEnabled()
    assert cp.submit_badge.text() == "제출 중…"
    assert "채점 중" in w.windowTitle()
    _wait_submit(qtbot, cp)

    assert submit_stub["calls"] == [{"topic": "sim", "num": 1234, "push": False}]
    assert cp.submit_badge.text() == "Pass"
    assert "Pass" in cp.banner.title.text()
    assert cp.banner._buttons and cp.banner._buttons[0].text() == "커밋 + 푸시"
    assert cp.push_btn.isVisibleTo(cp) and cp.push_btn.isEnabled()
    assert not cp.git_badge.isVisibleTo(cp)
    assert cp.submit_btn.isEnabled() and cp.submit_btn.text() == "SWEA 제출"
    assert w.windowTitle() == "SWEA Fetch"
    _no_secrets(cp.banner.title.text(), cp.banner.body.text(), cp.git_log.toPlainText())


def test_pass_auto_mode_pushes_without_banner_button(main_window, solved, submit_stub, qtbot):
    cp = main_window.check_page
    cp.set_settings(replace(main_window.settings, auto_push_on_pass=True))
    submit_stub["git"] = GitResult(True, True, "abc1234", "solve: 1234. A+B (sim)", "git push output", "푸시됨 abc1234")
    cp.set_target("sim", 1234)
    cp.request_submit()
    _wait_submit(qtbot, cp)

    assert submit_stub["calls"] == [{"topic": "sim", "num": 1234, "push": True}]
    assert cp.submit_badge.text() == "Pass"
    assert "커밋 + 푸시했습니다" in cp.banner.title.text() and "abc1234" in cp.banner.title.text()
    assert [b.text() for b in cp.banner._buttons] == ["되돌리기 안내"]
    assert cp.git_badge.isVisibleTo(cp) and "abc1234" in cp.git_badge.text()
    assert "git push output" in cp.git_log.toPlainText()


def test_wrong_answer_shows_error_and_no_push(main_window, solved, submit_stub, qtbot):
    cp = main_window.check_page
    cp.set_settings(replace(main_window.settings, auto_push_on_pass=True))  # 자동이어도 오답이면 푸시 없음
    submit_stub["result"] = _result(False, run_error="ZeroDivisionError: division by zero")
    submit_stub["git"] = GitResult(True, True, "x", "m", "", "푸시됨")
    cp.set_target("sim", 1234)
    cp.request_submit()
    _wait_submit(qtbot, cp)

    assert cp.submit_badge.text() == "오답"
    assert "오답" in cp.banner.title.text() and "푸시하지 않았습니다" in cp.banner.title.text()
    assert "7개" in cp.banner.body.text() and "ZeroDivisionError" in cp.banner.body.text()
    assert not cp.git_badge.isVisibleTo(cp)
    assert cp.push_btn.isVisibleTo(cp)  # 실패한 풀이도 수동 커밋은 가능 (보조 스타일)
    assert cp.push_btn.toolTip()


def test_submit_error_shows_failed_badge_and_hint(main_window, solved, submit_stub, qtbot):
    cp = main_window.check_page
    submit_stub["raise"] = SubmitError("허용하지 않는 키워드가 사용되었습니다", hint="코드를 고친 뒤 다시 제출하세요")
    cp.set_target("sim", 1234)
    cp.request_submit()
    _wait_submit(qtbot, cp)
    assert cp.submit_badge.text() == "제출 실패"
    assert "허용하지 않는 키워드" in cp.banner.title.text()
    assert "코드를 고친 뒤" in cp.banner.body.text()
    assert cp.submit_btn.isEnabled()


def test_second_request_while_submitting_is_ignored(main_window, solved, submit_stub, qtbot, monkeypatch):
    import threading

    gate = threading.Event()
    cp = main_window.check_page

    def slow(settings, topic, num, *, push=False, message=None, progress=None):
        submit_stub["calls"].append(1)
        gate.wait(5)
        return SubmitOutcome(_result(True), None, [], ID)

    monkeypatch.setattr(service, "submit_problem", slow)
    cp.set_target("sim", 1234)
    cp.request_submit()
    cp.request_submit()  # 무시 — 다이얼로그도 다시 뜨지 않음
    assert len(FakeMessageBox.instances) == 1
    gate.set()
    _wait_submit(qtbot, cp)
    assert submit_stub["calls"] == [1]


def test_progress_and_notes_go_to_status_bar(main_window, solved, submit_stub, qtbot):
    cp = main_window.check_page
    msgs: list[str] = []
    cp.status_message.connect(msgs.append)
    cp.set_target("sim", 1234)
    cp.request_submit()
    _wait_submit(qtbot, cp)
    assert any("제출 대상" in m for m in msgs) and any("import sys" in m for m in msgs)


# =============================================================================
# 최근 페이지 우클릭 → 같은 다이얼로그
# =============================================================================


def test_history_context_menu_submit_routes_to_check_page(main_window, solved, submit_stub, fake_msgbox, monkeypatch, qtbot):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    w = main_window
    hp = w.history_page
    hp.refresh()
    assert hp.table.rowCount() == 1

    shown: list[QMenu] = []

    class RecordingMenu(QMenu):
        def exec(self, *a, **k):  # 실제 메뉴는 띄우지 않음
            shown.append(self)
            return None

    monkeypatch.setattr(history_page_mod, "QMenu", RecordingMenu)
    monkeypatch.setattr(hp.table, "rowAt", lambda y: 0)
    fake_msgbox.choose = "취소"
    hp._context_menu(QPoint(5, 5))
    labels = [a.text() for a in shown[0].actions()]
    assert "SWEA 제출…" in labels
    next(a for a in shown[0].actions() if a.text() == "SWEA 제출…").trigger()

    assert w.stack.currentIndex() == 1  # 검증 페이지로 이동
    assert w.check_page.topic.currentText() == "sim" and w.check_page.num.text() == "1234"
    assert len(fake_msgbox.instances) == 1 and "1회 감소" in fake_msgbox.instances[0].body
    assert submit_stub["calls"] == []


# =============================================================================
# "git / 제출 응답" 탭 — 실제 service 경로 (FakeSession 까지)
# =============================================================================


def _fx(name: str) -> FakeResponse:
    return FakeResponse(200, json_data=json.loads((FIXTURE_DIR / f"submit_{name}.json").read_text(encoding="utf-8")))


@pytest.fixture
def real_service_env(main_window, solved, monkeypatch):
    s = FakeSession()
    s.cookies.set("SESSION", COOKIE)
    monkeypatch.setattr(service.auth, "get_session", lambda settings: s)
    monkeypatch.setattr(service.lookup, "find_category", lambda sess, settings, num: (ID, "BOX", BOX_ID, "모의/클럽 상자 · Queue"))
    solver = FakeResponse(200, text=f"<html><body><input name='categoryId' value='{BOX_ID}'><input name='categoryType' value='BOX'><h3 class='problem_title'>1234. A+B</h3></body></html>")
    s.queue(solver, _fx("compile_ok"), _fx("wrong"))
    return s


def test_response_tab_shows_last_submit_json_without_secrets(main_window, real_service_env, qtbot):
    w = main_window
    cp = w.check_page
    cp.set_target("sim", 1234)
    cp.request_submit()
    _wait_submit(qtbot, cp)

    assert cp.submit_badge.text() == "오답"
    tab_names = [cp.tabs.tabText(i) for i in range(cp.tabs.count())]
    assert "git / 제출 응답" in tab_names
    text = cp.git_log.toPlainText()
    assert text.startswith(f"[SWEA 제출 응답] contestProbId={ID}")
    shown = json.loads(text.split("\n", 1)[1])

    last = json.loads((w.config_dir / service.LAST_SUBMIT_FILE).read_text(encoding="utf-8"))
    assert shown == last["response"]
    assert (last["categoryType"], last["categoryId"], last["num"]) == ("BOX", BOX_ID, 1234)
    assert last["passed"] is False

    file_text = (w.config_dir / service.LAST_SUBMIT_FILE).read_text(encoding="utf-8")
    _no_secrets(text, file_text, cp.banner.title.text(), cp.banner.body.text())
    assert DUMMY_ID not in file_text and "SESSION" not in file_text
    # 실서버 호출 0: FakeSession 큐만 소비됨
    assert [c["url"].rsplit("/", 1)[1] for c in real_service_env.calls] == ["solvingProblem.do", "compile.do", "submit.do"]
    assert real_service_env.responses == []


# =============================================================================
# SubmitWorker
# =============================================================================


def test_submit_worker_forwards_push_flag_and_progress(qtbot, settings, submit_stub):
    w = workers.SubmitWorker(settings, "sim", 1234, True)
    msgs: list[str] = []
    w.progress.connect(msgs.append)
    with qtbot.waitSignal(w.finished_ok, timeout=WAIT) as sig:
        w.start()
    w.wait()
    assert submit_stub["calls"] == [{"topic": "sim", "num": 1234, "push": True}]
    assert sig.args[0].submit.passed is True
    assert any("제출 대상" in m for m in msgs)


def test_submit_worker_maps_submit_error(qtbot, settings, submit_stub):
    submit_stub["raise"] = SubmitError("횟수 소진")
    w = workers.SubmitWorker(settings, "sim", 1234, False)
    with qtbot.waitSignal(w.failed, timeout=WAIT) as sig:
        w.start()
    w.wait()
    assert sig.args[0] == "횟수 소진" and sig.args[2] == ""
