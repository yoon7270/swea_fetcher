"""풀이 잔디 (M20) 코어: 기록·집계·보관·백필·색 단계 + service 훅 (SWEA Pass / 로컬 검증 통과). 시간은 주입·고정, 네트워크·AI 호출 없음."""

from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime, timedelta

import pytest

from swea_fetcher import checker, coach, growth, service, solved
from swea_fetcher.errors import SubmitError
from swea_fetcher.submit import SubmitContext, SubmitResult

NUM = 1234
NOW = datetime(2026, 10, 1, 12, 0, 0)  # 목요일
TODAY = NOW.date()


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(growth, "now", lambda: NOW)


def rec(settings, num=NUM, at=NOW, via="swea", topic="sim", title="A+B"):
    return solved.record(settings, num, topic, title, via, at=at)


# --- 기록 · 집계 ------------------------------------------------------------------------------


def test_same_problem_same_day_counts_once_and_swea_wins(settings):
    assert rec(settings, via="local", title="")
    assert rec(settings, via="swea", at=NOW + timedelta(hours=1))
    assert rec(settings, via="local", at=NOW + timedelta(hours=2))
    days = solved.load(settings)
    assert list(days) == [TODAY] and len(days[TODAY]) == 1
    it = days[TODAY][0]
    assert it.via == "swea" and it.title == "A+B" and it.topic == "sim"  # SWEA 우선, 빈 제목은 채움


def test_different_problems_and_days_are_separate(settings):
    rec(settings, 1)
    rec(settings, 2)
    rec(settings, 1, at=NOW - timedelta(days=1))
    days = solved.load(settings)
    assert solved.counts(days) == {TODAY: 2, TODAY - timedelta(days=1): 1}


def test_local_date_boundary(settings):
    rec(settings, 1, at=datetime(2026, 9, 30, 23, 59, 59))
    rec(settings, 1, at=datetime(2026, 10, 1, 0, 0, 0))
    assert solved.counts(solved.load(settings)) == {date(2026, 9, 30): 1, date(2026, 10, 1): 1}  # 자정 넘으면 다른 날


def test_keep_400_days(settings):
    rec(settings, 1, at=NOW - timedelta(days=401))
    rec(settings, 2, at=NOW - timedelta(days=400))
    rec(settings, 3)  # 저장할 때 (오늘 기준) 400일 넘은 날을 걷어낸다
    days = solved.load(settings)
    assert TODAY - timedelta(days=400) in days and TODAY - timedelta(days=401) not in days and TODAY in days


def test_invalid_via_and_corrupt_file(settings):
    assert not solved.record(settings, 1, "sim", "", "github", at=NOW)
    path = settings.coach_dir / "profile" / "solved.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    assert solved.load(settings) == {}
    assert rec(settings)  # 손상돼도 새로 쓴다
    assert len(solved.load(settings)[TODAY]) == 1
    path.write_text(json.dumps({"v": 1, "days": {"bad": [{"num": 1, "via": "swea"}], "2026-10-01": [{"num": "x", "via": "swea"}, {"num": 5, "via": "zz"}, {"num": 7, "via": "local"}]}}), encoding="utf-8")
    assert [i.num for i in solved.load(settings)[TODAY]] == [7]  # 손상된 항목만 건너뜀


def test_refuses_to_write_inside_root(settings):
    inside = dataclasses.replace(settings, config_dir=settings.root / "cfg")
    assert rec(inside) is False
    assert not (inside.root / "cfg").exists()


def test_no_source_code_or_extra_fields_stored(settings):
    rec(settings)
    raw = json.loads((settings.coach_dir / "profile" / "solved.json").read_text(encoding="utf-8"))
    assert set(raw["days"][TODAY.isoformat()][0]) == {"num", "topic", "title", "via", "at"}


# --- 격자 · 단계 -------------------------------------------------------------------------------


def test_level_thresholds():
    assert [solved.level(n) for n in (0, 1, 2, 3, 4, 5, 20)] == [0, 1, 2, 3, 4, 4, 4]


def test_grid_start_is_sunday_53_weeks_ending_this_week():
    start = solved.grid_start(TODAY)  # 2026-10-01 (목) → 이번 주 일요일 09-27
    assert start.weekday() == 6 and start == date(2026, 9, 27) - timedelta(weeks=52)
    assert solved.grid_start(date(2026, 9, 27)) == date(2026, 9, 27) - timedelta(weeks=52)  # 일요일 당일은 그 날이 마지막 열 첫 칸
    assert solved.grid_start(date(2026, 10, 3)) == solved.grid_start(TODAY)  # 토요일까지 같은 주


def test_total_last_year_counts_visible_window_only(settings):
    start = solved.grid_start(TODAY)
    rec(settings, 1, at=datetime.combine(start, datetime.min.time()))  # 첫 칸
    rec(settings, 2, at=datetime.combine(start - timedelta(days=1), datetime.min.time()))  # 격자 밖
    rec(settings, 3)
    assert solved.total_last_year(solved.load(settings), TODAY) == 2


# --- 색 ----------------------------------------------------------------------------------------


def test_parse_hex():
    assert solved.parse_hex("#2da44e") == "#2DA44E"
    for bad in ("", None, "2DA44E", "#12", "#GGGGGG", "red"):
        assert solved.parse_hex(bad) == solved.DEFAULT_HEAT_COLOR


def test_mix_endpoints_and_midpoint():
    assert solved.mix("#000000", "#FFFFFF", 0) == "#FFFFFF"
    assert solved.mix("#000000", "#FFFFFF", 1) == "#000000"
    assert solved.mix("#FF0000", "#000000", 0.5) == "#800000"
    assert solved.mix("#FF0000", "#000000", 7) == "#FF0000"  # 범위 밖은 자른다


def _dist(a: str, b: str) -> int:
    return sum(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (1, 3, 5))


@pytest.mark.parametrize("bg", ["#FFFFFF", "#0D1117"])  # 라이트·다크 배경 모두 단계가 진해진다
@pytest.mark.parametrize("base", [c for _n, c in solved.HEAT_PRESETS])
def test_heat_colors_get_stronger_and_base_is_level3(base, bg):
    cols = solved.heat_colors(base, bg)
    assert len(cols) == 4 and cols[2] == base  # 4단계는 기준색보다 한 단계 더 진하다
    d = [_dist(c, bg) for c in cols]
    assert d == sorted(d) and len(set(d)) == 4


# --- 백필 --------------------------------------------------------------------------------------


def seed_old(settings):
    growth.record_submit(settings, 10, "sim", "pass", 0, at=NOW - timedelta(days=3))
    growth.record_submit(settings, 10, "sim", "pass", 0, at=NOW - timedelta(days=3, hours=-1))  # 같은 날 같은 문제
    growth.record_submit(settings, 11, "sim", "wrong", 0, at=NOW - timedelta(days=2))  # 오답은 제외
    growth.record_submit(settings, 12, "dp", "pass", 0, at=NOW - timedelta(days=200))  # 120일 밖
    r = coach.ProblemRecord(13, "graph", "BFS", last_result="pass", last_submit_at=(NOW - timedelta(days=300)).isoformat(timespec="seconds"))
    w = coach.ProblemRecord(14, "graph", "DFS", last_result="wrong", last_submit_at=NOW.isoformat(timespec="seconds"))
    coach._save_records(settings, {"13": r, "14": w, "10": coach.ProblemRecord(10, "sim", "두 수", last_result="pass", last_submit_at=(NOW - timedelta(days=3)).isoformat(timespec="seconds"))})


def test_backfill_from_events_and_records(settings):
    seed_old(settings)
    assert service.growth_solved(settings, NOW)  # 첫 로드에서 백필
    days = solved.load(settings)
    flat = {(d, i.num, i.title, i.via) for d, v in days.items() for i in v}
    assert flat == {(NOW.date() - timedelta(days=3), 10, "두 수", "swea"), (NOW.date() - timedelta(days=300), 13, "BFS", "swea")}  # 이벤트 120일 + 코치 기록(마지막 Pass)


def test_backfill_runs_once_even_after_growth_clear(settings):
    seed_old(settings)
    service.growth_solved(settings, NOW)
    service.clear_growth(settings.config_dir)  # profile/ 삭제 (records.json 은 남음)
    assert service.growth_solved(settings, NOW) == {}  # 되살아나지 않는다
    rec(settings, 99)
    assert list(solved.counts(service.growth_solved(settings, NOW)).values()) == [1]


def test_backfill_again_after_ai_records_cleared_is_empty(settings):
    seed_old(settings)
    service.growth_solved(settings, NOW)
    service.clear_coach(settings.config_dir)  # coach/ 전체 (표식 포함) — 원본도 사라졌으니 빈 상태
    assert service.growth_solved(settings, NOW) == {}


def test_backfill_with_no_data_is_quiet(settings):
    assert service.growth_solved(settings, NOW) == {}
    assert (settings.coach_dir / solved.BACKFILL_MARK).exists()


def test_growth_off_records_and_returns_nothing(settings):
    off = dataclasses.replace(settings, growth=False)
    seed_old(settings)
    assert service.growth_solved(off, NOW) == {}
    service._record_solved(off, "sim", NUM, "local")
    assert solved.load(settings) == {}
    assert not (settings.coach_dir / solved.BACKFILL_MARK).exists()


def test_logout_all_and_clear_coach_remove_solved(settings):
    rec(settings)
    assert (settings.coach_dir / "profile" / "solved.json").exists()
    service.clear_growth(settings.config_dir)
    assert not (settings.coach_dir / "profile" / "solved.json").exists()
    rec(settings)
    service.logout(settings.config_dir, all_=True)
    assert solved.load(settings) == {}


# --- 기록 시점 (service 훅) --------------------------------------------------------------------


@pytest.fixture
def problem(settings):
    d = settings.root / "sim" / str(NUM)
    d.mkdir(parents=True)
    (d / f"{NUM}.py").write_text("# 1234. A+B\nprint('#1 3')\n", encoding="utf-8")
    (d / "input.txt").write_text("1\n", encoding="utf-8")
    (d / "output.txt").write_text("#1 3\n", encoding="utf-8")
    return d


@pytest.fixture
def submit_stub(settings, problem, monkeypatch):
    st = {"results": []}
    monkeypatch.setattr(service.auth, "get_session", lambda s, explicit=False: object())
    monkeypatch.setattr(service.lookup, "find_category", lambda *a, **k: ("CID", "CODE", "CID", "공개 문제"))
    monkeypatch.setattr(service.client, "_with_relogin", lambda session, settings, fn: fn())
    monkeypatch.setattr(service.submit, "get_context", lambda *a, **k: SubmitContext("CID", "CID", "CODE", "A+B"))
    monkeypatch.setattr(service.submit, "compile_source", lambda *a, **k: {})

    def submit_source(*a, **k):
        r = st["results"].pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(service.submit, "submit_source", submit_source)
    return st


def test_swea_pass_is_recorded_with_title_and_topic(settings, submit_stub):
    submit_stub["results"] += [SubmitResult(True, "Pass"), SubmitResult(True, "Pass")]
    service.submit_problem(settings, "sim", NUM)
    service.submit_problem(settings, "sim", NUM)  # 같은 날 두 번 Pass 해도 1번
    items = solved.load(settings)[TODAY]
    assert [(i.num, i.topic, i.title, i.via) for i in items] == [(NUM, "sim", "A+B", "swea")]


def test_wrong_and_submit_error_are_not_recorded(settings, submit_stub):
    submit_stub["results"] += [SubmitResult(False, "오답"), SubmitResult(False, "제한시간 초과", timed_out=True), SubmitError("컴파일 오류")]
    service.submit_problem(settings, "sim", NUM)
    service.submit_problem(settings, "sim", NUM)
    with pytest.raises(SubmitError):
        service.submit_problem(settings, "sim", NUM)
    assert solved.load(settings) == {}


def test_record_failure_does_not_change_submit_result(settings, submit_stub, monkeypatch):
    submit_stub["results"] += [SubmitResult(True, "Pass")]
    monkeypatch.setattr(solved, "record", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    oc = service.submit_problem(settings, "sim", NUM)
    assert oc.submit.passed


def test_local_check_pass_is_recorded_fail_is_not(settings, problem):
    ok = service.check_problem(settings, problem, timeout=30)
    assert ok.passed
    assert [(i.num, i.via) for i in solved.load(settings)[TODAY]] == [(NUM, "local")]
    # 같은 날 SWEA Pass 가 오면 방식만 SWEA 로 (1건 유지)
    service._record_solved(settings, "sim", NUM, "swea")
    assert [i.via for i in solved.load(settings)[TODAY]] == ["swea"]


def test_local_check_fail_timeout_cancel_not_recorded(settings, problem, monkeypatch):
    (problem / f"{NUM}.py").write_text("print('#1 4')\n", encoding="utf-8")
    assert not service.check_problem(settings, problem, timeout=30).passed
    cancelled = checker.CheckResult(True, "x", "x", "", 0.1, False, cancelled=True)
    monkeypatch.setattr(checker, "run_and_compare", lambda *a, **k: cancelled)
    service.check_problem(settings, problem, timeout=30)
    assert solved.load(settings) == {}


def test_cli_check_records_pass(settings, problem, monkeypatch):
    from swea_fetcher import cli, config

    monkeypatch.setattr(config, "load_settings", lambda *a, **k: settings)
    assert cli.main(["check", "sim", str(NUM), "--no-push"]) == 0
    assert [i.via for i in solved.load(settings)[TODAY]] == ["local"]


def test_check_without_growth_does_not_record(settings, problem):
    off = dataclasses.replace(settings, growth=False)
    assert service.check_problem(off, problem, timeout=30).passed
    assert solved.load(settings) == {}


# --- M22: 다크 농도 · 모드 보정 · 설정 값 해석 ---------------------------------------------------


@pytest.mark.parametrize("base", ["#2DA44E", "#1F6FEB", "#8250DF", "#E16F24", "#D6336C", "#4C94FF"])
def test_dark_heat_levels_strictly_brighter(base):
    bg, empty = "#1E222A", "#29303A"
    cols = [empty, *solved.heat_colors(base, bg, dark=True)]
    lums = [solved.rel_luminance(c) for c in cols]
    assert all(a < b for a, b in zip(lums, lums[1:])), lums
    assert solved.heat_colors(base, bg, dark=True) != solved.heat_colors(base, bg)  # 다크는 다른 혼합 비율


def test_adjust_for_mode_luminance_bounds_and_idempotent():
    dark_fixed = solved.adjust_for_mode("#0B1020", dark=True)
    assert solved.rel_luminance(dark_fixed) >= solved.DARK_MIN_LUMA and dark_fixed != "#0B1020"
    assert solved.adjust_for_mode("#4C94FF", dark=True) == "#4C94FF"
    light_fixed = solved.adjust_for_mode("#FFEE88", dark=False)
    assert solved.rel_luminance(light_fixed) <= solved.LIGHT_MAX_LUMA
    assert solved.adjust_for_mode("#2da44e", dark=False) == "#2DA44E"  # 범위 안이면 그대로(대문자 통일)
    assert solved.adjust_for_mode(solved.adjust_for_mode("#0B1020", True), True) == solved.adjust_for_mode("#0B1020", True)


@pytest.mark.parametrize(
    "value,expected",
    [(None, ("follow", None)), ("", ("follow", None)), ("follow", ("follow", None)), ("zzz", ("follow", None)),
     ("#12AB3", ("follow", None)), ("#12ab34", ("fixed", "#12AB34")), ("#2DA44E", ("fixed", "#2DA44E"))],
)
def test_heat_base_setting_migration(value, expected):
    assert solved.heat_base(value) == expected
