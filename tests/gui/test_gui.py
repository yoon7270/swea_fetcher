"""GUI 스모크·동작 테스트 (offscreen). 네트워크 경계(service.fetch_problem / verify_login)는 스텁."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from swea_fetcher import config, service
from swea_fetcher.errors import AlreadyExists, AttachmentNotFound, InvalidInput, LoginFailed, NetworkError
from swea_fetcher.gui import workers
from swea_fetcher.models import SaveResult
from swea_fetcher.service import FetchOutcome
from tests.conftest import CONTEST_PROB_ID, DUMMY_ID, DUMMY_PW

ID = CONTEST_PROB_ID
WAIT = 5000


def _saved_outcome(root: Path, info) -> FetchOutcome:
    d = root / "sim" / "25730"
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for name, body in (("input.txt", "3\n"), ("output.txt", "#1 3\n"), ("25730.py", "# 25730. 항아리 게임\n")):
        (d / name).write_text(body, encoding="utf-8")
        files.append(d / name)
    return FetchOutcome(info, SaveResult(d, files, []), None, [], "sim")


# =============================================================================
# MainWindow
# =============================================================================


def test_window_builds_with_settings(main_window):
    w = main_window
    assert w.settings is not None and w.settings.user_id == DUMMY_ID
    assert w.stack.count() == 4 and w.nav.count() == 4
    assert w.status_login.text() == "○ 세션 없음"
    assert str(w.settings.root) in w.status_root.toolTip()
    assert w.nav.currentRow() == 0 and w.stack.currentIndex() == 0


def test_window_without_settings_goes_to_settings_page(main_window_no_config):
    w = main_window_no_config
    assert w.settings is None
    assert w.nav.currentRow() == 3 and w.stack.currentIndex() == 3
    assert w.status_login.text() == "○ 설정 없음"
    assert w.settings_page.banner.isVisibleTo(w) and "처음 실행" in w.settings_page.banner.title.text()


def test_nav_switches_pages_and_persists_last_page(main_window, qtbot):
    w = main_window
    w.goto("history")
    assert w.stack.currentIndex() == 2
    assert int(w.qs.value("window/last_page", -1, type=int)) == 2
    w.goto("check")
    assert w.stack.currentIndex() == 1


def test_status_shows_logged_in_when_session_cached(qtbot, valid_config):
    (valid_config / "session.json").write_text("{}")
    from swea_fetcher.gui.main_window import MainWindow

    w = MainWindow(config_dir=valid_config)
    qtbot.addWidget(w)
    assert w.status_login.text() == "● 로그인됨"


def test_history_check_request_routes_to_check_page(main_window):
    w = main_window
    w.history_page.check_requested.emit("BFS", 4014)
    assert w.stack.currentIndex() == 1
    assert w.check_page.topic.currentText() == "BFS" and w.check_page.num.text() == "4014"


def test_busy_changes_window_title(main_window):
    w = main_window
    w.fetch_page.busy_changed.emit(True, "저장 중…")
    assert "저장 중" in w.windowTitle()
    w.fetch_page.busy_changed.emit(False, "")
    assert w.windowTitle() == "SWEA Fetch"


# =============================================================================
# FetchPage
# =============================================================================


def test_fetch_page_lists_topics_from_root(main_window):
    for n in ("BFS", "DP"):
        (main_window.settings.root / n).mkdir()
    main_window.fetch_page.set_settings(main_window.settings)
    items = [main_window.fetch_page.topic.itemText(i) for i in range(main_window.fetch_page.topic.count())]
    assert items == ["BFS", "DP"]


def test_fetch_page_validates_empty_target(main_window):
    fp = main_window.fetch_page
    fp.target.setText("")
    fp.topic.setCurrentText("sim")
    fp.start(dry_run=False)
    assert fp._worker is None
    assert fp.err_label.isVisibleTo(fp) and "문제 번호" in fp.err_label.text()
    assert fp.target.property("state") == "invalid"


def test_fetch_page_validates_empty_topic(main_window):
    fp = main_window.fetch_page
    fp.target.setText("25730")
    fp.topic.setCurrentText("")
    fp.start(dry_run=False)
    assert fp._worker is None
    assert "주제" in fp.err_label.text()


def test_fetch_page_without_settings_shows_banner(main_window_no_config):
    fp = main_window_no_config.fetch_page
    fp.target.setText("1")
    fp.topic.setCurrentText("t")
    fp.start(dry_run=False)
    assert fp._worker is None
    assert "설정이 없습니다" in fp.banner.title.text()


def test_fetch_page_success_flow(main_window, qtbot, monkeypatch, problem_info):
    w = main_window
    fp = w.fetch_page
    seen = {}

    def fake(settings, target, topic, opts, progress):
        seen.update(target=target, topic=topic, opts=opts)
        progress("진행 메시지")
        return _saved_outcome(settings.root, problem_info)

    monkeypatch.setattr(service, "fetch_problem", fake)
    fp.target.setText("25730")
    fp.topic.setCurrentText("sim")
    fp.force.setChecked(True)
    with qtbot.waitSignal(fp.saved, timeout=WAIT):
        fp.start(dry_run=False)
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)

    assert seen["target"] == "25730" and seen["topic"] == "sim" and seen["opts"].force is True
    assert fp.card.isVisibleTo(fp) and "25730. 항아리 게임" in fp.card_title.text()
    assert fp.run_btn.isEnabled() and fp.run_btn.text() == "저장"
    assert w.qs.value("fetch/last_topic", type=str) == "sim"
    assert fp.topic.findText("sim") >= 0
    assert "진행 메시지" in fp.log.text.toPlainText()
    # 최근 목록이 갱신됨
    assert w.history_page.table.rowCount() == 1
    assert w.history_page.table.item(0, 0).text() == "25730"


@pytest.mark.parametrize(
    "exc, expect_title, expect_action",
    [
        (AlreadyExists("이미 저장된 파일이 있습니다: x", existing=[Path("x")]), "이미 저장된 문제", "force"),
        (AttachmentNotFound("첨부 링크가 없습니다 (누락: in)"), "샘플 첨부가 없는 문제", "skeleton"),
        (InvalidInput("문제 번호 5 을(를) 찾지 못했습니다"), "찾지 못했습니다", "refresh"),
        (NetworkError("네트워크 오류"), "네트워크", "retry"),
        (LoginFailed("로그인 실패: LoginIdPwdFail"), "로그인 실패", "settings"),
    ],
)
def test_fetch_page_failure_banner_actions(main_window, qtbot, monkeypatch, exc, expect_title, expect_action):
    fp = main_window.fetch_page

    def fake(*a, **k):
        raise exc

    monkeypatch.setattr(service, "fetch_problem", fake)
    fp.target.setText("5")
    fp.topic.setCurrentText("sim")
    fp.start(dry_run=False)
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)
    assert expect_title in fp.banner.title.text()
    assert fp.banner._buttons, "조치 버튼이 있어야 함"
    keys = []
    fp.banner.action_clicked.connect(keys.append)
    fp.banner._buttons[0].click()
    assert keys == [expect_action] or expect_action == "settings"  # settings 는 goto_requested 로 빠짐
    assert exc.hint in fp.banner.body.text() or not exc.hint


def test_fetch_page_force_action_reruns_with_force(main_window, qtbot, monkeypatch, problem_info):
    fp = main_window.fetch_page
    calls = []

    def fake(settings, target, topic, opts, progress):
        calls.append(opts.force)
        if not opts.force:
            raise AlreadyExists("이미 저장된 파일이 있습니다: x", existing=[Path("x")])
        return _saved_outcome(settings.root, problem_info)

    monkeypatch.setattr(service, "fetch_problem", fake)
    fp.target.setText("25730")
    fp.topic.setCurrentText("sim")
    fp.start(dry_run=False)
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)
    assert calls == [False]
    with qtbot.waitSignal(fp.saved, timeout=WAIT):
        fp.banner._buttons[0].click()
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)
    assert calls == [False, True]
    assert fp.force.isChecked()


def test_fetch_page_internal_error_banner(main_window, qtbot, monkeypatch):
    fp = main_window.fetch_page

    def fake(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(service, "fetch_problem", fake)
    fp.target.setText("1")
    fp.topic.setCurrentText("sim")
    fp.start(dry_run=False)
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)
    assert fp.banner.title.text().startswith("내부 오류") and "kaboom" in fp.banner.title.text()
    assert "Traceback" in fp.log.text.toPlainText()


def test_fetch_page_dry_run_shows_preview_and_commit(main_window, qtbot, monkeypatch, problem_info):
    from swea_fetcher.service import FilePlan

    fp = main_window.fetch_page
    calls = []

    def fake(settings, target, topic, opts, progress):
        calls.append((opts.dry_run, opts.force))
        if opts.dry_run:
            pv = {"problem_dir": settings.root / "sim" / "25730", "files": [FilePlan("input.txt", "conflict", "i", 1, "3"), FilePlan("25730.py", "keep")], "needs_force": True}
            return FetchOutcome(problem_info, None, pv, [], "sim")
        return _saved_outcome(settings.root, problem_info)

    monkeypatch.setattr(service, "fetch_problem", fake)
    fp.target.setText("25730")
    fp.topic.setCurrentText("sim")
    fp.start(dry_run=True)
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)
    assert calls == [(True, False)]
    assert fp.commit_btn.isVisibleTo(fp) and fp.commit_btn.text() == "덮어쓰고 저장"
    with qtbot.waitSignal(fp.saved, timeout=WAIT):
        fp.commit_btn.click()
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)
    assert calls == [(True, False), (False, True)]


def test_fetch_page_ignores_start_while_busy(main_window, qtbot, monkeypatch, problem_info):
    import threading

    fp = main_window.fetch_page
    gate = threading.Event()
    calls = []

    def fake(settings, target, topic, opts, progress):
        calls.append(1)
        gate.wait(3)
        return _saved_outcome(settings.root, problem_info)

    monkeypatch.setattr(service, "fetch_problem", fake)
    fp.target.setText("25730")
    fp.topic.setCurrentText("sim")
    fp.start(dry_run=False)
    assert not fp.run_btn.isEnabled() and not fp.target.isEnabled()
    fp.start(dry_run=False)  # 무시
    gate.set()
    qtbot.waitUntil(lambda: fp._worker is None, timeout=WAIT)
    assert calls == [1]


# =============================================================================
# SettingsPage
# =============================================================================


def test_settings_page_prefills_from_env(main_window):
    sp = main_window.settings_page
    assert sp.root_edit.text() == str(main_window.settings.root)
    assert sp.id_edit.text() == DUMMY_ID
    assert sp.pw_edit.text() == ""


def test_settings_save_only_validates(main_window_no_config, qtbot):
    sp = main_window_no_config.settings_page
    sp.root_edit.setText("")
    sp.id_edit.setText("")
    sp.save(check=False)
    assert sp.root_edit.property("state") == "invalid"
    assert sp.id_edit.property("state") == "invalid"
    assert sp.pw_edit.property("state") == "invalid"
    assert not (main_window_no_config.config_dir / ".env").exists()


def test_settings_save_only_writes_env_and_keyring(main_window_no_config, qtbot, root_dir, fake_keyring):
    w = main_window_no_config
    sp = w.settings_page
    sp.root_edit.setText(str(root_dir))
    sp.id_edit.setText(DUMMY_ID)
    sp.pw_edit.setText(DUMMY_PW)
    with qtbot.waitSignal(sp.settings_changed, timeout=WAIT):
        sp.save(check=False)
    assert sp.pw_edit.text() == ""
    assert fake_keyring.store == {(config.KEYRING_SERVICE, DUMMY_ID): DUMMY_PW}
    assert config.read_env_file(w.config_dir)["SWEA_ID"] == DUMMY_ID
    assert "저장했습니다" in sp.banner.title.text()
    # MainWindow 가 다시 로드해 설정이 생김 (stay=True 라 페이지 이동 없음)
    assert w.settings is not None and w.settings.user_id == DUMMY_ID
    assert w.stack.currentIndex() == 3


def test_settings_save_without_pw_uses_saved_credential(main_window, qtbot, fake_keyring):
    sp = main_window.settings_page
    sp.pw_edit.setText("")
    with qtbot.waitSignal(sp.settings_changed, timeout=WAIT):
        sp.save(check=False)
    assert sp.pw_edit.property("state") != "invalid"
    assert fake_keyring.store[(config.KEYRING_SERVICE, DUMMY_ID)] == DUMMY_PW


def test_settings_save_with_check_runs_login_worker(main_window, qtbot, monkeypatch, fake_keyring):
    sp = main_window.settings_page
    seen = {}

    def fake_verify(settings, progress=None):
        seen["user"] = settings.user_id
        seen["pw"] = settings.password
        return "로그인 확인 완료"

    monkeypatch.setattr(service, "verify_login", fake_verify)
    sp.pw_edit.setText("new-pw")
    with qtbot.waitSignal(sp.settings_changed, timeout=WAIT):
        sp.save(check=True)
    qtbot.waitUntil(lambda: sp._worker is None, timeout=WAIT)
    assert seen == {"user": DUMMY_ID, "pw": "new-pw"}
    assert fake_keyring.store[(config.KEYRING_SERVICE, DUMMY_ID)] == "new-pw"
    assert "로그인 확인 완료" in sp.banner.title.text()
    assert sp.save_btn.isEnabled()


def test_settings_login_failure_keeps_settings(main_window, qtbot, monkeypatch):
    sp = main_window.settings_page

    def bad(settings, progress=None):
        raise LoginFailed("비밀번호 오류")

    monkeypatch.setattr(service, "verify_login", bad)
    with qtbot.waitSignal(sp.settings_changed, timeout=WAIT):
        sp.save(check=True)
    qtbot.waitUntil(lambda: sp._worker is None, timeout=WAIT)
    assert "비밀번호 오류" in sp.banner.title.text()
    assert "저장됐습니다" in sp.banner.body.text()
    assert (main_window.config_dir / ".env").exists()


def test_settings_logout_session(main_window, qtbot):
    w = main_window
    (w.config_dir / "session.json").write_text("{}")
    w._update_status()
    assert w.status_login.text() == "● 로그인됨"
    with qtbot.waitSignal(w.settings_page.settings_changed, timeout=WAIT):
        w.settings_page._logout(False)
    assert not (w.config_dir / "session.json").exists()
    assert w.status_login.text() == "○ 세션 없음"
    assert w.settings_page.id_edit.text() == DUMMY_ID  # 계정 정보는 유지


def test_settings_timeout_persists_and_updates_check_hint(main_window):
    w = main_window
    w.settings_page.timeout.setValue(25)
    assert w.check_page.timeout() == 25.0
    assert "25초" in w.check_page.hint.text()


# =============================================================================
# CheckPage
# =============================================================================


def test_check_page_validation(main_window):
    cp = main_window.check_page
    cp.topic.setCurrentText("")
    cp.num.setText("1")
    cp.start()
    assert cp._worker is None and "주제" in cp.err_label.text()
    cp.topic.setCurrentText("sim")
    cp.num.setText("abc")
    cp.start()
    assert cp._worker is None and "숫자" in cp.err_label.text()


def test_check_page_missing_py_banner(main_window):
    cp = main_window.check_page
    cp.set_target("sim", 1234)
    cp.start()
    assert cp._worker is None
    assert "1234.py 가 없습니다" in cp.banner.title.text()
    assert cp.banner._buttons and cp.banner._buttons[0].text() == "저장 페이지로"


def test_check_page_runs_solution_and_passes(main_window, qtbot):
    w = main_window
    d = w.settings.root / "sim" / "1234"
    d.mkdir(parents=True)
    (d / "input.txt").write_text("1\n2 3\n", encoding="utf-8")
    (d / "output.txt").write_text("#1 5\n", encoding="utf-8")
    (d / "1234.py").write_text("input()\na,b=map(int,input().split())\nprint(f'#1 {a+b}')\n", encoding="utf-8")
    cp = w.check_page
    cp.set_target("sim", 1234)
    cp.start()
    assert cp.badge.text() == "실행 중…"
    qtbot.waitUntil(lambda: cp._worker is None, timeout=30000)
    assert cp.badge.text() == "통과"
    assert cp.stack.currentIndex() == 1
    assert not cp.mismatch.isVisibleTo(cp)
    assert cp.run_btn.isEnabled() and cp.run_btn.text() == "실행"


def test_check_page_failure_shows_mismatch(main_window, qtbot):
    w = main_window
    d = w.settings.root / "sim" / "1234"
    d.mkdir(parents=True)
    (d / "input.txt").write_text("1\n", encoding="utf-8")
    (d / "output.txt").write_text("#1 5\n", encoding="utf-8")
    (d / "1234.py").write_text("print('#1 6')\n", encoding="utf-8")
    cp = w.check_page
    cp.set_target("sim", 1234)
    cp.start()
    qtbot.waitUntil(lambda: cp._worker is None, timeout=30000)
    assert cp.badge.text() == "실패"
    assert cp.mismatch.isVisibleTo(cp) and "1줄" in cp.mismatch.text()
    assert cp.tabs.count() == 1  # stderr 없음


def test_check_page_drop_folder_sets_target(main_window, qtbot):
    from PySide6.QtCore import QMimeData, QPoint, QUrl
    from PySide6.QtGui import QDropEvent

    w = main_window
    d = w.settings.root / "BFS" / "777"
    d.mkdir(parents=True)
    (d / "777.py").write_text("")
    cp = w.check_page
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(d / "777.py"))])
    ev = QDropEvent(QPoint(1, 1), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    cp.dropEvent(ev)
    assert cp.topic.currentText() == "BFS" and cp.num.text() == "777"


def test_check_page_drop_unrelated_file_warns(main_window):
    from PySide6.QtCore import QMimeData, QPoint, QUrl
    from PySide6.QtGui import QDropEvent

    cp = main_window.check_page
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(main_window.settings.root / "readme.txt"))])
    ev = QDropEvent(QPoint(1, 1), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    cp.dropEvent(ev)
    assert "끌어다 놓으세요" in cp.banner.title.text()
    assert "readme.txt" in cp.banner.body.text()


# =============================================================================
# HistoryPage
# =============================================================================


def test_history_page_lists_and_double_click_requests_check(main_window, qtbot):
    w = main_window
    d = w.settings.root / "DP" / "42"
    d.mkdir(parents=True)
    (d / "42.py").write_text("# 42. 제목\n", encoding="utf-8")
    hp = w.history_page
    hp.refresh()
    assert hp.table.rowCount() == 1
    assert [hp.table.item(0, c).text() for c in range(3)] == ["42", "제목", "DP"]
    assert hp.stack.currentIndex() == 0
    with qtbot.waitSignal(hp.check_requested, timeout=WAIT) as sig:
        hp._double_clicked(0, 0)
    assert sig.args == ["DP", 42]


def test_history_page_empty_state(main_window):
    hp = main_window.history_page
    hp.refresh()
    assert hp.table.rowCount() == 0 and hp.stack.currentIndex() == 1


# =============================================================================
# Workers
# =============================================================================


def test_base_worker_maps_domain_error_to_failed_signal(qtbot):
    class W(workers.BaseWorker):
        def work(self):
            raise NetworkError("net down")

    w = W()
    with qtbot.waitSignal(w.failed, timeout=WAIT) as sig:
        w.start()
    w.wait()
    assert sig.args[0] == "net down" and sig.args[1] == NetworkError.default_hint and sig.args[2] == ""


def test_base_worker_unexpected_error_includes_traceback(qtbot):
    class W(workers.BaseWorker):
        def work(self):
            raise ValueError("x")

    w = W()
    with qtbot.waitSignal(w.failed, timeout=WAIT) as sig:
        w.start()
    w.wait()
    assert sig.args[0].startswith("내부 오류: ValueError") and "Traceback" in sig.args[2]


def test_login_worker_discards_password_after_saving(qtbot, root_dir, config_dir, fake_keyring, monkeypatch):
    monkeypatch.setattr(service, "verify_login", lambda s, p=None: "ok")
    w = workers.LoginWorker(config_dir, root_dir, DUMMY_ID, DUMMY_PW)
    with qtbot.waitSignal(w.finished_ok, timeout=WAIT) as sig:
        w.start()
    w.wait()
    assert sig.args == ["ok"]
    assert w._password is None
    assert fake_keyring.store[(config.KEYRING_SERVICE, DUMMY_ID)] == DUMMY_PW
    assert "SWEA_PW" not in (config_dir / ".env").read_text(encoding="utf-8")


def test_func_worker(qtbot):
    w = workers.FuncWorker(lambda: 42)
    with qtbot.waitSignal(w.finished_ok, timeout=WAIT) as sig:
        w.start()
    w.wait()
    assert sig.args == [42]


# =============================================================================
# M5 #3: 검증 취소
# =============================================================================

INFINITE = "import time\nprint('#1 3', flush=True)\nwhile True:\n    time.sleep(0.05)\n"


def _infinite_problem(root: Path, num: int = 1234) -> Path:
    d = root / "sim" / str(num)
    d.mkdir(parents=True)
    (d / "input.txt").write_text("1\n", encoding="utf-8")
    (d / "output.txt").write_text("#1 3\n", encoding="utf-8")
    (d / f"{num}.py").write_text(INFINITE, encoding="utf-8")
    return d


def test_check_worker_cancel_kills_running_process(qtbot, settings):
    d = _infinite_problem(settings.root)
    w = workers.CheckWorker(d, settings, timeout=30)
    with qtbot.waitSignal(w.finished_ok, timeout=15000) as sig:
        w.start()
        qtbot.waitUntil(lambda: w._proc is not None and w._proc.poll() is None, timeout=WAIT)
        w.cancel()
    w.wait()
    res = sig.args[0]
    assert res.cancelled is True and res.passed is False and res.timed_out is False
    assert w._proc.poll() is not None  # 프로세스 종료됨


def test_check_worker_cancel_before_process_starts(qtbot, settings):
    d = _infinite_problem(settings.root)
    w = workers.CheckWorker(d, settings, timeout=30)
    w.cancel()  # 아직 안 떴음
    with qtbot.waitSignal(w.finished_ok, timeout=15000) as sig:
        w.start()
    w.wait()
    assert sig.args[0].cancelled is True


def test_check_worker_cancel_after_finish_is_noop(qtbot, settings):
    d = settings.root / "sim" / "1"
    d.mkdir(parents=True)
    (d / "input.txt").write_text("1\n")
    (d / "output.txt").write_text("x\n")
    (d / "1.py").write_text("print('x')\n")
    w = workers.CheckWorker(d, settings, timeout=30)
    with qtbot.waitSignal(w.finished_ok, timeout=15000) as sig:
        w.start()
    w.wait()
    w.cancel()  # 예외 없어야 함
    assert sig.args[0].passed is True and sig.args[0].cancelled is False


def test_check_page_cancel_button_flow(main_window, qtbot):
    w = main_window
    _infinite_problem(w.settings.root)
    cp = w.check_page
    assert not cp.cancel_btn.isVisibleTo(cp)
    cp.set_target("sim", 1234)
    cp.start()
    assert cp.cancel_btn.isVisibleTo(cp) and cp.cancel_btn.isEnabled()
    assert not cp.run_btn.isEnabled()
    qtbot.waitUntil(lambda: cp._worker is not None and cp._worker._proc is not None, timeout=WAIT)
    cp.cancel_btn.click()
    assert not cp.cancel_btn.isEnabled()
    qtbot.waitUntil(lambda: cp._worker is None, timeout=15000)
    assert cp.badge.text() == "취소됨"
    assert "취소했습니다" in cp.banner.title.text()
    assert not cp.cancel_btn.isVisibleTo(cp)
    assert cp.run_btn.isEnabled() and cp.run_btn.text() == "실행"
    assert not cp.mismatch.isVisibleTo(cp) and not cp.elapsed.isVisibleTo(cp)
    assert "SWEA Fetch" == w.windowTitle()


def test_check_page_cancel_then_rerun_works(main_window, qtbot):
    w = main_window
    d = _infinite_problem(w.settings.root)
    cp = w.check_page
    cp.set_target("sim", 1234)
    cp.start()
    qtbot.waitUntil(lambda: cp._worker is not None and cp._worker._proc is not None, timeout=WAIT)
    cp.cancel()
    qtbot.waitUntil(lambda: cp._worker is None, timeout=15000)
    (d / "1234.py").write_text("print('#1 3')\n", encoding="utf-8")
    cp.start()
    qtbot.waitUntil(lambda: cp._worker is None, timeout=30000)
    assert cp.badge.text() == "통과"


def test_check_page_cancel_when_idle_is_noop(main_window):
    cp = main_window.check_page
    cp.cancel()
    assert cp._worker is None
