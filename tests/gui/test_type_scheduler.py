"""배경 풀이 유형 분류 스케줄러 (M24.2, offscreen): 한가함 판단 · 동의/토글 게이트 · 한 번에 워커 하나 · 멈춤 규칙(한도·연속 실패·시간당/하루 상한·네트워크) · 진행 신호 · 깨끗한 종료.

워커는 FakeBgWorker(스레드 없음)로 대체하고 결과를 직접 내보낸다. 실제 TypeBgWorker 는 service.classify_background 를 스텁해 한 번만 돌려 본다. 네트워크·AI 호출 0.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal

from swea_fetcher import service
from swea_fetcher.gui import type_scheduler
from swea_fetcher.gui.type_scheduler import TypeScheduler
from swea_fetcher.gui.workers import TypeBgWorker

T0 = datetime(2026, 10, 6, 12, 30, 0)


class FakeBgWorker(QObject):
    finished_ok = Signal(object)
    failed = Signal(str, str, str)
    finished = Signal()
    instances: list = []

    def __init__(self, settings, consented=frozenset(), start_level=None, exclude=(), parent=None) -> None:
        super().__init__(parent)
        self.settings, self.consented, self.start_level, self.exclude = settings, frozenset(consented), start_level, tuple(exclude)
        self.running = False
        self.cancelled = False
        FakeBgWorker.instances.append(self)

    def start(self) -> None:
        self.running = True

    def isRunning(self) -> bool:  # noqa: N802
        return self.running

    def cancel(self) -> None:
        self.cancelled = True

    def wait(self, _ms: int = 0) -> bool:
        self.waited = True
        return True

    def deliver(self, res) -> None:
        self.running = False
        self.finished_ok.emit(res)
        self.finished.emit()

    def fail(self) -> None:
        self.running = False
        self.failed.emit("내부 오류", "", "")
        self.finished.emit()


@pytest.fixture(autouse=True)
def fake_worker(monkeypatch):
    FakeBgWorker.instances = []
    monkeypatch.setattr(type_scheduler, "TypeBgWorker", FakeBgWorker)


class Env:
    """스케줄러가 묻는 것들(설정·동의·한가함·시계)을 테스트가 바꾼다."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.consented = frozenset({"codex"})
        self.busy = False
        self.level = 3
        self.mono = 1000.0
        self.now = T0


@pytest.fixture
def env(settings):
    return Env(settings)


@pytest.fixture
def sched(qtbot, env):
    s = TypeScheduler(lambda: env.settings, lambda: env.consented, lambda: env.busy, lambda: env.level, clock=lambda: env.mono, now_fn=lambda: env.now)
    s._born = env.mono - 120  # 앱을 켠 지 2분
    yield s
    s.stop()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # 워커 정리(deleteLater)를 테스트 안에서 끝낸다 (나중 이벤트 루프에서 죽은 객체를 건드리지 않게)


def last():
    return FakeBgWorker.instances[-1]


def res(status="ok", done=5, changed=True, capped="", attempted=(1, 2, 3, 4, 5), progress=(5, 926)):
    return service.ClassifyResult(status, done, changed, "codex", capped, tuple(attempted), progress)


# --- 시작 조건 ------------------------------------------------------------------------------------------


def test_tick_starts_one_worker_with_settings_consent_level_and_excludes(sched, env):
    assert sched.blocker() == "" and sched.tick() is True
    w = last()
    assert w.running and w.settings is env.settings and w.consented == {"codex"} and w.start_level == 3 and w.exclude == ()
    assert sched.running() and sched.blocker() == "running" and sched.tick() is False and len(FakeBgWorker.instances) == 1  # 한 번에 하나


def test_timer_ticks_every_two_minutes(sched):
    assert sched._timer.interval() == type_scheduler.TICK_MS == 120_000
    sched.start()
    assert sched._timer.isActive()
    sched.stop()
    assert not sched._timer.isActive()


def test_not_before_sixty_seconds_after_app_start(sched, env):
    sched._born = env.mono - 59
    assert sched.blocker() == "starting" and sched.tick() is False
    env.mono += 2
    assert sched.blocker() == "" and sched.tick() is True


def test_only_when_the_app_is_idle(sched, env):
    env.busy = True
    assert sched.blocker() == "busy" and sched.tick() is False and FakeBgWorker.instances == []
    env.busy = False
    assert sched.tick() is True


@pytest.mark.parametrize("off", [{"type_bg": False}, {"recommend_ai": False}, {"recommend": False}, {"growth": False}])
def test_settings_toggles_gate_the_scheduler(sched, env, settings, off):
    env.settings = dataclasses.replace(settings, **off)
    assert sched.blocker() == "off" and sched.tick() is False
    env.settings = None
    assert sched.blocker() == "off"  # 설정이 없어도 안전하다


def test_inert_until_consent(sched, env):
    env.consented = frozenset()
    assert sched.blocker() == "consent" and sched.tick() is False and FakeBgWorker.instances == []
    env.consented = frozenset({"claude"})
    assert sched.tick() is True and last().consented == {"claude"}


def test_toggle_off_stops_scheduling_immediately_but_lets_the_running_batch_finish(sched, env, settings):
    sched.tick()
    w = last()
    env.settings = dataclasses.replace(settings, type_bg=False)
    assert sched.blocker() == "off" and not w.cancelled and w.running  # 돌던 묶음은 끝까지
    w.deliver(res())
    assert sched.tick() is False and len(FakeBgWorker.instances) == 1


# --- 결과 처리 · 멈춤 규칙 ---------------------------------------------------------------------------------


def test_ok_result_emits_progress_and_classified(sched, qtbot):
    sched.tick()
    with qtbot.waitSignal(sched.progress_changed) as p, qtbot.waitSignal(sched.classified), qtbot.waitSignal(sched.status_changed) as st:
        last().deliver(res(progress=(312, 926)))
    assert p.args == [312, 926, ""] and st.args == ["ok"] and not sched.running() and sched.last_status == "ok"
    assert sched.tick() is True  # 다음 틱에 또 한 묶음


def test_nothing_changed_does_not_emit_classified(sched, qtbot):
    sched.tick()
    seen = []
    sched.classified.connect(lambda: seen.append(1))
    last().deliver(res("nothing", 0, False, progress=(926, 926)))
    assert seen == []


def test_usage_limit_stops_for_the_rest_of_the_day_only(sched, env):
    sched.tick()
    last().deliver(res("limit", 0, False, capped="day"))
    assert sched.blocker() == "stopped" and sched.tick() is False
    env.now = T0 + timedelta(days=1)
    assert sched.blocker() == "" and sched.tick() is True


def test_daily_cap_and_todays_failure_pause_stop_for_the_day(sched, env):
    sched.tick()
    last().deliver(res("capped", 0, False, capped="day"))
    assert sched.blocker() == "stopped"
    env.now = T0 + timedelta(days=1)
    sched.tick()
    last().deliver(res("paused", 0, False))
    assert sched.blocker() == "stopped"


def test_ok_batch_that_reaches_the_daily_cap_stops_the_day(sched):
    sched.tick()
    last().deliver(res("ok", 3, True, capped="day"))
    assert sched.blocker() == "stopped"


def test_hourly_cap_waits_until_the_next_hour(sched, env):
    sched.tick()
    last().deliver(res("capped", 0, False, capped="hour"))
    assert sched.blocker() == "cooldown"
    env.now = datetime(2026, 10, 6, 12, 59, 0)
    assert sched.blocker() == "cooldown"
    env.now = datetime(2026, 10, 6, 13, 0, 1)
    assert sched.blocker() == "" and sched.tick() is True


def test_network_problem_cools_down_without_retrying_or_counting_as_failure(sched, env):
    sched.tick()
    last().deliver(res("network", 0, False))
    assert sched.blocker() == "cooldown" and sched._fails == 0 and sched.tick() is False
    env.now = T0 + type_scheduler.NETWORK_COOLDOWN + timedelta(seconds=1)
    assert sched.tick() is True


def test_nothing_to_do_or_no_engine_rests_half_an_hour(sched, env):
    for status in ("nothing", "no_engine"):
        env.now = T0 + timedelta(days=1 if status == "no_engine" else 0)
        assert sched.tick() is True
        last().deliver(res(status, 0, False, progress=(900, 926)))
        assert sched.blocker() == "cooldown"
        env.now += type_scheduler.IDLE_COOLDOWN + timedelta(seconds=1)
        assert sched.blocker() == ""


def test_three_consecutive_failures_stop_the_day_and_a_success_resets_the_count(sched, env):
    for n in range(2):
        sched.tick()
        last().deliver(res("failed", 0, False, attempted=(10 + n, 20 + n)))
    assert sched.blocker() == "" and sched._fails == 2
    sched.tick()
    last().deliver(res("ok"))
    assert sched._fails == 0
    for n in range(3):
        assert sched.tick() is True
        last().deliver(res("failed", 0, False, attempted=(100 + n,)))
    assert sched.blocker() == "stopped"
    env.now = T0 + timedelta(days=1)
    assert sched.tick() is True


def test_failed_batches_are_excluded_for_the_rest_of_the_session(sched):
    sched.tick()
    last().deliver(res("failed", 0, False, attempted=(7, 8, 9)))
    sched.tick()
    assert last().exclude == (7, 8, 9)
    last().deliver(res("failed", 0, False, attempted=(9, 11)))
    sched.tick()
    assert last().exclude == (7, 8, 9, 11)


def test_unexpected_worker_error_counts_as_a_failure(sched):
    sched.tick()
    last().fail()
    assert sched._fails == 1 and not sched.running()


def test_busy_and_cancelled_results_change_nothing(sched):
    sched.tick()
    last().deliver(res("busy", 0, False))
    assert sched.blocker() == "" and sched._fails == 0
    sched.tick()
    last().deliver(res("cancelled", 0, False))
    assert sched.blocker() == "" and sched._fails == 0


# --- 종료 -----------------------------------------------------------------------------------------------


def test_wait_workers_cancels_the_running_worker_and_stops_the_timer(sched):
    sched.start()
    sched.tick()
    w = last()
    sched.wait_workers()
    assert w.cancelled and getattr(w, "waited", False) and not sched._timer.isActive()
    sched.wait_workers()  # 실행 중이 아니면 아무 일도 없다


def test_wait_workers_is_a_no_op_without_a_worker(sched):
    sched.wait_workers()
    assert FakeBgWorker.instances == []


# --- 실제 워커 · 메인 창 -----------------------------------------------------------------------------------


def test_real_worker_runs_classify_background_with_consent_level_and_excludes(qtbot, settings, monkeypatch):
    got = {}

    def fake(settings, *, consent_ok, start_level=None, exclude=(), on_start=None, is_cancelled=None, **kw):
        got.update(codex=consent_ok("codex"), claude=consent_ok("claude"), level=start_level, exclude=tuple(exclude), cancelled=is_cancelled())
        return service.ClassifyResult("ok", 5, True, "codex", "", (1,), (5, 926))

    monkeypatch.setattr(service, "classify_background", fake)
    w = TypeBgWorker(settings, {"codex"}, 4, [3, 1])
    results = []
    w.finished_ok.connect(results.append)
    with qtbot.waitSignal(w.finished, timeout=8000):
        w.start()
    w.wait(2000)
    assert got == {"codex": True, "claude": False, "level": 4, "exclude": (3, 1), "cancelled": False} and results[0].status == "ok"


def test_real_worker_cancel_sets_the_flag_and_kills_registered_processes(settings, monkeypatch):
    from swea_fetcher import ai_engine

    killed = []
    monkeypatch.setattr(ai_engine, "kill_tree", killed.append)
    w = TypeBgWorker(settings)
    proc = object()
    w._on_start(proc)
    w.cancel()
    assert w._cancel_requested and killed == [proc]
    late = object()
    w._on_start(late)  # 취소 뒤에 뜬 프로세스도 즉시 종료
    assert killed == [proc, late]


def test_real_worker_exception_becomes_failed_signal(qtbot, settings, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(service, "classify_background", boom)
    w = TypeBgWorker(settings)
    errors = []
    w.failed.connect(lambda t, h, d: errors.append(t))
    with qtbot.waitSignal(w.finished, timeout=8000):
        w.start()
    w.wait(2000)
    assert errors and "내부 오류" in errors[0]


def test_main_window_busy_check_covers_user_started_work(main_window):
    w = main_window
    assert w.is_busy() is False
    for owner, attr in ((w.fetch_page, "_worker"), (w.check_page, "_worker"), (w.check_page, "_submit_worker"), (w.check_page, "_coach_worker"),
                        (w.settings_page, "_worker"), (w.settings_page, "_ai_ping_worker"), (w.growth_page.recommend, "_worker"), (w, "_stmt_worker"), (w, "_growth_worker")):
        setattr(owner, attr, object())
        assert w.is_busy() is True, attr
        setattr(owner, attr, None)
    assert w.is_busy() is False


def test_main_window_scheduler_reads_live_settings_consent_and_busy(main_window, monkeypatch):
    w = main_window
    sch = w.type_scheduler
    sch._born -= 600
    assert sch._timer.isActive() and sch._timer.interval() == type_scheduler.TICK_MS
    assert sch.blocker() == "consent"  # 동의 전에는 아무 것도 하지 않는다
    monkeypatch.setattr("swea_fetcher.gui.main_window.growth_consent_ok", lambda qs, key: key == "codex")
    assert sch.blocker() == ""
    w.fetch_page._worker = object()
    assert sch.blocker() == "busy"
    w.fetch_page._worker = None
    service.set_env_values(w.config_dir, SWEA_TYPE_BG="0")
    w.reload_settings(stay=True)
    assert sch.blocker() == "off"


def test_main_window_close_stops_scheduler_and_cancels_its_worker(main_window):
    w = main_window
    w.type_scheduler._born -= 600
    w._consented_engines = lambda: frozenset({"codex"})
    w.type_scheduler._consented = w._consented_engines
    assert w.type_scheduler.tick() is True
    fw = last()
    w.close()
    assert fw.cancelled and not w.type_scheduler._timer.isActive()
