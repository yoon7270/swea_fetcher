"""growth: 이벤트 로그, 주 경계, 통계, 판정, 스냅샷, 팁, payload. 시간은 전부 주입한다 (기준: 2026-09-30 수, 이번 주 월요일 2026-09-28)."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta

import pytest

from swea_fetcher import growth, growth_tags
from swea_fetcher.config import Settings
from swea_fetcher.growth import Event, WeekStats
from swea_fetcher.growth_tags import Parsed, Tag

NOW = datetime(2026, 9, 30, 12, 0, 0)
MON = date(2026, 9, 28)  # 이번 주 월요일
W1 = date(2026, 9, 21)  # 지난 주
W2 = date(2026, 9, 14)
W3 = date(2026, 9, 7)


def at(week: date, day: int = 0, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(week.year, week.month, week.day, hour, minute) + timedelta(days=day)


def submit(settings, week, res="pass", wb=0, num=1000, day=0, hour=10):
    assert growth.record_submit(settings, num, "sim", res, wb, at=at(week, day, hour))


def coach_ev(settings, week, kind="review", lv=0, eng="codex", tags=(), ok=True, num=1000, day=0, hour=11):
    parsed = Parsed(tuple(Tag(*t) for t in tags), True) if ok else None
    assert growth.record_coach(settings, num, "sim", kind, lv, eng, parsed, at=at(week, day, hour))


def fill_week(settings, week, *, passes=4, first_try=2, wrong=1, timeouts=0, tagged=3, weak=("edge",), num0=2000):
    """passes 건 Pass (first_try 건은 wb=0, 나머지 wb=2), 오답 wrong 건, 시간초과 timeouts 건, 코치 tagged 건 (weak 태그 s=2)."""
    for i in range(passes):
        submit(settings, week, "pass", 0 if i < first_try else 2, num0 + i, day=i % 5)
    for i in range(wrong):
        submit(settings, week, "wrong", 0, num0 + 50 + i, day=1)
    for i in range(timeouts):
        submit(settings, week, "timeout", 0, num0 + 80 + i, day=2)
    for i in range(tagged):
        coach_ev(settings, week, "review", 0, "codex", [(c, "weak", 2) for c in weak], num=num0 + i, day=i % 5)


# --- 설정 ---------------------------------------------------------------------------------


def test_default_settings_have_growth_on(settings):
    assert settings.growth is True and settings.growth_comment is True
    assert "growth=" not in repr(settings)  # __repr__ 불변


# --- 주 경계 ------------------------------------------------------------------------------


def test_week_boundaries():
    assert growth.week_start(datetime(2026, 9, 27, 23, 59, 59)) == W1  # 일요일 = 지난 주
    assert growth.week_start(datetime(2026, 9, 28, 0, 0, 0)) == MON  # 월요일 00:00 = 새 주
    assert growth.week_start(date(2026, 12, 31)) == date(2026, 12, 28)  # 연말연시
    assert growth.week_start(date(2027, 1, 3)) == date(2026, 12, 28)
    assert growth.week_end(MON) == date(2026, 10, 4)


def test_snapshot_filename_validation():
    assert growth._valid_week_name("2026-09-21") == W1
    for bad in ("2026-09-22", "../evil", "2026-9-21", "2026-13-01", "abc"):
        assert growth._valid_week_name(bad) is None


# --- 이벤트 로그 ----------------------------------------------------------------------------


def test_events_roundtrip_and_no_source_text(settings):
    submit(settings, W1, "wrong", wb=1, num=25730)
    coach_ev(settings, W1, "hint", 2, "claude", [("edge", "weak", 2)], num=25730)
    coach_ev(settings, W1, "hint", 1, "claude", ok=False, num=25730)
    lines = (settings.coach_dir / "profile" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["res"] == "wrong" and json.loads(lines[0])["wb"] == 1
    evs = growth.read_events(settings)
    assert [e.t for e in evs] == ["submit", "coach", "coach"]
    assert evs[1].k == "hint" and evs[1].lv == 2 and evs[1].ok and evs[1].tags == (Tag("edge", "weak", 2),)
    assert evs[2].ok is False and evs[2].tags == ()
    assert set(json.loads(lines[1])) == {"v", "t", "at", "num", "topic", "k", "lv", "eng", "ok", "tg"}  # 코드·지문·제목 필드 없음


def test_corrupt_lines_are_skipped(settings):
    submit(settings, W1)
    path = settings.coach_dir / "profile" / "events.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write("{broken\n\n[1,2]\n" + json.dumps({"v": 9, "t": "submit", "at": "2026-09-22T10:00:00"}) + "\n")
        f.write(json.dumps({"v": 1, "t": "other", "at": "2026-09-22T10:00:00"}) + "\n")
        f.write(json.dumps({"v": 1, "t": "submit", "at": "not-a-date", "res": "pass"}) + "\n")
    submit(settings, W1, "wrong")
    assert [e.res for e in growth.read_events(settings)] == ["pass", "wrong"]


def test_concurrent_appends_are_serialized(settings):
    def worker(n):
        for i in range(25):
            growth.record_submit(settings, n * 100 + i, "sim", "pass", 0, at=at(W1))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(growth.read_events(settings)) == 100


def test_writes_are_refused_inside_root(root_dir, config_dir):
    inside = Settings(root=root_dir, user_id="u", password="p", config_dir=root_dir / ".cfg")
    assert growth.record_submit(inside, 1, "sim", "pass", 0, at=NOW) is False
    assert not (root_dir / ".cfg").exists()
    assert growth.build_missing_snapshots(inside, NOW) == []


def test_write_failure_never_raises(settings, monkeypatch):
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert growth.record_submit(settings, 1, "sim", "pass", 0, at=NOW) is False
    assert growth.record_coach(settings, 1, "sim", "review", 0, "codex", None, at=NOW) is False


def test_trim_drops_old_events_when_file_is_large(settings, monkeypatch):
    monkeypatch.setattr(growth, "now", lambda: NOW)
    monkeypatch.setattr(growth, "EVENT_MAX_LINES", 300)
    path = settings.coach_dir / "profile" / "events.jsonl"
    path.parent.mkdir(parents=True)
    old = datetime(2026, 1, 1, 10, 0)
    pad = "x" * 800
    with open(path, "w", encoding="utf-8") as f:
        for i in range(400):
            rec = {"v": 1, "t": "submit", "at": (old if i < 200 else NOW).isoformat(timespec="seconds"), "num": i, "topic": pad, "res": "pass", "wb": 0}
            f.write(json.dumps(rec) + "\n")
    assert path.stat().st_size > 256 * 1024
    growth.record_submit(settings, 999, "sim", "pass", 0, at=NOW)
    kept = growth.read_events(settings)
    assert len(kept) == 201 and all(e.at >= datetime(2026, 6, 1) for e in kept)  # 120일 지난 200건 제거


# --- 통계 ---------------------------------------------------------------------------------


def test_compute_stats(settings):
    submit(settings, W1, "pass", wb=0, num=1)
    submit(settings, W1, "pass", wb=2, num=2)
    submit(settings, W1, "pass", wb=1, num=2)  # 같은 문제 두 번 Pass: solved 는 1건
    submit(settings, W1, "wrong", num=3)
    submit(settings, W1, "timeout", num=3)
    submit(settings, W1, "runtime_error", num=4)
    st = growth.compute_stats(growth.read_events(settings))
    assert (st.submits, st.passes, st.solved, st.wrong, st.timeouts, st.runtime_errors, st.first_try) == (6, 3, 2, 3, 1, 1, 1)
    assert st.avg_wrong_before_pass == pytest.approx(1.0) and st.first_try_rate == pytest.approx(1 / 3) and st.timeout_share == pytest.approx(1 / 6)
    empty = growth.compute_stats([])
    assert empty.avg_wrong_before_pass is None and empty.first_try_rate is None and empty.weak_rate("edge") is None


def test_grouping_merges_retries_and_two_engines(settings):
    coach_ev(settings, W1, "review", 0, "codex", [("edge", "weak", 1), ("pythonic", "strong", 2)], num=7)
    coach_ev(settings, W1, "review", 0, "claude", [("edge", "weak", 3), ("time", "weak", 2)], num=7)  # both 모드: 태그 합집합·강도 최댓값
    coach_ev(settings, W1, "review", 0, "codex", [("edge", "weak", 2)], num=7, hour=15)  # [다시 받기]
    coach_ev(settings, W1, "hint", 1, "codex", ok=False, num=7)
    coach_ev(settings, W1, "hint", 2, "codex", [("impl", "weak", 2)], num=7)
    coach_ev(settings, W1, "hint", 2, "claude", ok=False, num=7)  # 한 엔진만 파싱 성공해도 그룹은 ok
    st = growth.compute_stats(growth.read_events(settings))
    assert (st.reviews, st.hints, st.solutions, st.tagged, st.events) == (1, 2, 0, 2, 3)
    assert st.weak == {"edge": 3, "time": 2, "impl": 2} and st.strong == {"pythonic": 2}


def test_stats_dict_roundtrip_drops_unknown_categories():
    st = WeekStats(passes=2, weak={"edge": 2}, strong={"pythonic": 1})
    raw = st.to_dict()
    raw["weak"]["future_cat"] = 5
    back = WeekStats.from_dict(raw)
    assert back.weak == {"edge": 2} and back.passes == 2


# --- 판정 ---------------------------------------------------------------------------------


def stats(**kw) -> WeekStats:
    base = dict(submits=8, passes=4, solved=4, wrong=4, first_try=2, avg_wrong_before_pass=1.0, tagged=4, events=8)
    base.update(kw)
    return WeekStats(**base)


def keys(js, kind=None):
    return [j.key for j in js if kind is None or j.kind == kind]


def test_no_prev_means_no_judgments_except_persistent():
    prev, js = growth.evaluate(MON, stats(), {})
    assert prev is None and js == []
    assert growth.headline(js, stats(solved=3), False) == growth.FIRST_RECORD_TEXT


def test_first_try_exact_threshold_is_included():
    prev = stats(passes=20, first_try=4)  # 0.20
    _, js = growth.evaluate(MON, stats(passes=20, first_try=7), {W1: prev})  # 0.35 = 정확히 +0.15
    assert keys(js, "improved") == ["first_try_rate"]
    _, js = growth.evaluate(MON, stats(passes=20, first_try=6), {W1: prev})  # +0.10: 미달
    assert "first_try_rate" not in keys(js)
    _, js = growth.evaluate(MON, stats(passes=20, first_try=1), {W1: stats(passes=20, first_try=4)})  # 0.05 vs 0.20: -0.15 정확히
    assert keys(js, "watch") == ["first_try_rate"]


def test_avg_wrong_threshold_and_sample_condition():
    prev = stats(avg_wrong_before_pass=2.0)
    _, js = growth.evaluate(MON, stats(avg_wrong_before_pass=1.5), {W1: prev})  # -0.5 정확히 포함
    assert keys(js, "improved") == ["avg_wrong_before_pass"]
    _, js = growth.evaluate(MON, stats(avg_wrong_before_pass=1.6), {W1: prev})
    assert "avg_wrong_before_pass" not in keys(js)
    _, js = growth.evaluate(MON, stats(avg_wrong_before_pass=2.5), {W1: prev})
    assert keys(js, "watch") == ["avg_wrong_before_pass"]
    _, js = growth.evaluate(MON, stats(passes=2, first_try=0, avg_wrong_before_pass=0.0), {W1: prev})  # passes < 3: 조용히 생략
    assert js == []


def test_timeout_share_needs_five_submits_in_both_weeks():
    prev = stats(submits=10, timeouts=4)  # 0.4
    _, js = growth.evaluate(MON, stats(submits=10, timeouts=3), {W1: prev})  # -0.10 정확히
    assert keys(js, "improved") == ["timeout_share"]
    _, js = growth.evaluate(MON, stats(submits=4, timeouts=0), {W1: prev})  # 이번 주 표본 미달
    assert "timeout_share" not in keys(js)
    _, js = growth.evaluate(MON, stats(submits=10, timeouts=5), {W1: prev})
    assert keys(js, "watch") == ["timeout_share"]


def test_solved_activity_only_positive():
    _, js = growth.evaluate(MON, stats(solved=5), {W1: stats(solved=3)})
    assert keys(js, "activity") == ["solved"]
    _, js = growth.evaluate(MON, stats(solved=4), {W1: stats(solved=3)})
    assert keys(js, "activity") == []
    _, js = growth.evaluate(MON, stats(solved=1), {W1: stats(solved=5)})
    assert not [j for j in js if j.key == "solved"]  # 감소는 판정 없음


def test_weak_category_relief_and_worsening():
    prev = stats(tagged=4, weak={"edge": 4})  # 1.0
    _, js = growth.evaluate(MON, stats(tagged=4, weak={"edge": 3}), {W1: prev})  # -0.25 정확히
    assert keys(js, "improved") == ["weak:edge"] and "약점 완화" in js[0].text
    _, js = growth.evaluate(MON, stats(tagged=4, weak={"edge": 4}), {W1: prev})
    assert js == []
    prev = stats(tagged=4, weak={"edge": 2})  # 0.5
    _, js = growth.evaluate(MON, stats(tagged=4, weak={"edge": 3}), {W1: prev})  # +0.25 정확히, cur>=2
    assert keys(js, "watch") == ["weak:edge"]
    _, js = growth.evaluate(MON, stats(tagged=4, weak={"edge": 3}), {W1: stats(tagged=4, weak={"edge": 1})})  # prev < 2: 판정 안 함
    assert js == []
    _, js = growth.evaluate(MON, stats(tagged=2, weak={"edge": 0}), {W1: prev})  # tagged < 3
    assert js == []


def test_strong_category_growth_and_new_strength():
    _, js = growth.evaluate(MON, stats(tagged=4, strong={"pythonic": 3}), {W1: stats(tagged=4, strong={"pythonic": 2})})  # 0.75 vs 0.5
    assert keys(js, "strength") == ["strong:pythonic"] and "강점 성장" in js[0].text
    _, js = growth.evaluate(MON, stats(tagged=9, strong={"ds": 2}), {W1: stats(tagged=4)})  # prev 0 -> cur >= 2 = 새 강점
    assert keys(js, "strength") == ["strong:ds"] and "새 강점" in js[0].text
    _, js = growth.evaluate(MON, stats(tagged=4, strong={"ds": 1}), {W1: stats(tagged=4)})  # cur < 2
    assert js == []
    _, js = growth.evaluate(MON, stats(tagged=4, strong={}), {W1: stats(tagged=4, strong={"ds": 3})})  # 강점 약화는 표시 안 함
    assert js == []


def test_prev_selection_skips_empty_weeks_and_limits_to_five_weeks():
    hist = {MON - timedelta(days=35): stats(), MON - timedelta(days=42): stats()}
    prev, _ = growth.evaluate(MON, stats(), hist)
    assert prev == MON - timedelta(days=35)  # 5주 이내 (이벤트 없는 사이 주는 건너뜀)
    prev, _ = growth.evaluate(MON, stats(), {MON - timedelta(days=42): stats()})
    assert prev is None  # 6주 전: baseline 없음
    prev, _ = growth.evaluate(MON, stats(), {W1: stats(), W3: stats()})
    assert prev == W1


def test_persistent_weak_needs_three_consecutive_calendar_weeks():
    w = stats(tagged=3, weak={"time": 2})
    _, js = growth.evaluate(MON, w, {W1: w, W2: w})
    assert keys(js, "persistent") == ["weak:time"] and js[0].cur == 3
    _, js = growth.evaluate(MON, w, {W1: w, W3: w})  # 중간에 이벤트 없는 주가 있으면 끊김
    assert keys(js, "persistent") == []
    _, js = growth.evaluate(MON, w, {W1: w, W2: stats(tagged=3, weak={"time": 1})})  # 점수 < 2 인 주가 끼면 끊김
    assert keys(js, "persistent") == []


def test_judgment_limits_and_ordering():
    prev = stats(passes=20, first_try=4, submits=20, timeouts=10, avg_wrong_before_pass=3.0, solved=2, tagged=10, weak={"edge": 8}, events=30)
    cur = stats(passes=20, first_try=18, submits=20, timeouts=1, avg_wrong_before_pass=0.5, solved=9, tagged=10, weak={"edge": 1}, events=30)
    _, js = growth.evaluate(MON, cur, {W1: prev})
    good = [j for j in js if j.kind in growth.GOOD_KINDS]
    assert len(good) == 3 and [j.score for j in good] == sorted((j.score for j in good), reverse=True)
    assert growth.headline(js, cur, True) == "좋아진 점이 3가지 있어요"
    assert growth.headline([], stats(solved=4), True) == "이번 주는 뚜렷한 변화가 없어요 (꾸준히 4문제 해결)"


# --- 스냅샷 -------------------------------------------------------------------------------


def test_build_missing_snapshots_is_idempotent_and_immutable(settings):
    fill_week(settings, W1)
    assert growth.build_missing_snapshots(settings, NOW) == [W1]
    path = settings.coach_dir / "profile" / "weeks" / "2026-09-21.json"
    first = path.read_text(encoding="utf-8")
    fill_week(settings, W1, passes=2, tagged=0, wrong=0, num0=3000)  # 확정 뒤 늘어난 이벤트
    assert growth.build_missing_snapshots(settings, NOW) == []
    assert path.read_text(encoding="utf-8") == first  # 불변
    raw = json.loads(first)
    assert raw["week_start"] == "2026-09-21" and raw["week_end"] == "2026-09-27" and raw["prev_week"] is None and raw["comment_status"] == "pending"


def test_current_week_is_not_confirmed_and_empty_weeks_have_no_snapshot(settings):
    fill_week(settings, MON)  # 이번 주는 진행 중
    submit(settings, W3)  # W2 는 이벤트 없음
    assert growth.build_missing_snapshots(settings, NOW) == [W3]
    assert not (settings.coach_dir / "profile" / "weeks" / "2026-09-14.json").exists()


def test_backlog_only_latest_is_pending_and_low_data_skipped(settings):
    fill_week(settings, W3)
    fill_week(settings, W2)
    submit(settings, W1)  # 이벤트 1건: 표본 부족
    assert growth.build_missing_snapshots(settings, NOW) == [W3, W2, W1]
    snaps = growth.load_snapshots(settings)
    assert (snaps[W3].comment_status, snaps[W2].comment_status, snaps[W1].comment_status) == ("skipped_backlog", "skipped_backlog", "skipped_low_data")
    # 가장 최근이 정상이면 그 주만 pending
    fill_week(settings, date(2026, 8, 31))
    assert growth.build_missing_snapshots(settings, NOW) == [date(2026, 8, 31)]  # 오래된 주가 나중에 채워져도 그 주만 대상


def test_snapshots_link_prev_weeks_in_order(settings):
    fill_week(settings, W3, first_try=1)
    fill_week(settings, W2, first_try=4)  # 0.25 -> 1.0
    growth.build_missing_snapshots(settings, NOW)
    snaps = growth.load_snapshots(settings)
    assert snaps[W2].prev_week == W3 and snaps[W3].prev_week is None
    assert "first_try_rate" in keys(snaps[W2].judgments, "improved")


def test_weeks_older_than_twelve_weeks_are_not_built(settings):
    old = MON - timedelta(days=7 * 13)
    fill_week(settings, old)
    assert growth.build_missing_snapshots(settings, NOW) == []


def test_after_downtime_all_missed_weeks_are_built(settings):
    for w in (W3, W2, W1):
        fill_week(settings, w)
    later = NOW + timedelta(days=30)  # 앱을 한 달 꺼 뒀다가 켬
    assert growth.build_missing_snapshots(settings, later) == [W3, W2, W1]
    assert growth.build_missing_snapshots(settings, later) == []


def test_corrupt_snapshot_is_renamed_and_ignored(settings):
    fill_week(settings, W1)
    growth.build_missing_snapshots(settings, NOW)
    path = settings.coach_dir / "profile" / "weeks" / "2026-09-21.json"
    path.write_text("{oops", encoding="utf-8")
    assert growth.load_snapshots(settings) == {}
    assert path.with_name(path.name + ".corrupt").exists() and not path.exists()
    assert growth.build_missing_snapshots(settings, NOW) == [W1]  # 이벤트가 남아 있으면 재생성


def test_bad_filenames_in_weeks_dir_are_ignored(settings):
    d = settings.coach_dir / "profile" / "weeks"
    d.mkdir(parents=True)
    (d / "2026-09-22.json").write_text("{}", encoding="utf-8")  # 월요일이 아님
    (d / "evil.json").write_text("{}", encoding="utf-8")
    assert growth.load_snapshots(settings) == {}
    assert (d / "2026-09-22.json").exists()  # 건드리지 않는다


def test_snapshots_pruned_to_52_weeks(settings):
    d = settings.coach_dir / "profile" / "weeks"
    for i in range(54):
        w = date(2025, 1, 6) + timedelta(days=7 * i)
        growth.save_snapshot(settings, growth.Snapshot(w, "x", WeekStats(events=5)))
    fill_week(settings, W1)
    growth.build_missing_snapshots(settings, NOW)
    snaps = growth.load_snapshots(settings)
    assert len(snaps) == 52 and date(2025, 1, 6) not in snaps and W1 in snaps
    assert len(list(d.glob("*.json"))) == 52


def test_update_snapshot_only_changes_mutable_fields(settings):
    fill_week(settings, W1)
    growth.build_missing_snapshots(settings, NOW)
    with pytest.raises(ValueError):
        growth.update_snapshot(settings, W1, stats=WeekStats())
    growth.update_snapshot(settings, W1, comment={"text": "굿", "engine": "x", "at": "t"}, comment_status="ok")
    snap = growth.load_snapshots(settings)[W1]
    assert snap.comment["text"] == "굿" and snap.comment_status == "ok" and snap.stats.passes == 4


def test_seen_and_unseen_count(settings):
    fill_week(settings, W2)
    fill_week(settings, W1)
    growth.build_missing_snapshots(settings, NOW)
    assert growth.unseen_count(settings) == 2
    growth.mark_seen(settings, W1, NOW)
    assert growth.unseen_count(settings) == 1 and growth.load_snapshots(settings)[W1].seen_at == "2026-09-30T12:00:00"


# --- 코멘트 후보 ----------------------------------------------------------------------------


def snap_with(status, attempts=0, week=W1, events=5):
    return growth.Snapshot(week, "x", WeekStats(events=events), comment_status=status, comment_attempts=attempts)


def test_comment_candidate_rules():
    assert growth.comment_candidate({W1: snap_with("pending")}, NOW).week_start == W1
    assert growth.comment_candidate({W1: snap_with("ok")}, NOW) is None
    assert growth.comment_candidate({W1: snap_with("failed", 1)}, NOW) is not None
    assert growth.comment_candidate({W1: snap_with("failed", 2)}, NOW) is None  # 자동 재시도는 총 2회까지
    assert growth.comment_candidate({W1: snap_with("skipped_backlog")}, NOW) is None
    assert growth.comment_candidate({W2: snap_with("pending", week=W2), W1: snap_with("ok")}, NOW) is None  # 가장 최근 스냅샷만
    assert growth.comment_candidate({W1: snap_with("pending")}, NOW + timedelta(days=16)) is None  # 주 종료 후 14일 초과 (9/27 + 14 = 10/11)
    assert growth.comment_candidate({W1: snap_with("pending")}, datetime(2026, 10, 11, 9, 0)) is not None
    # 수동: 나이·횟수 무시, 표본 조건은 유지
    assert growth.comment_candidate({W1: snap_with("failed", 5)}, datetime(2027, 1, 1), W1) is not None
    assert growth.comment_candidate({W1: snap_with("skipped_low_data", events=2)}, NOW, W1) is None
    assert growth.comment_candidate({}, NOW) is None


def test_is_due(settings):
    assert growth.is_due(settings, NOW) is False
    fill_week(settings, W1)
    assert growth.is_due(settings, NOW) is True  # 만들 스냅샷 있음
    growth.build_missing_snapshots(settings, NOW)
    assert growth.is_due(settings, NOW) is True  # pending 코멘트
    assert growth.is_due(settings, NOW, comment=False) is False
    growth.update_snapshot(settings, W1, comment_status="ok")
    assert growth.is_due(settings, NOW) is False


# --- payload / 후처리 ----------------------------------------------------------------------------


def test_comment_payload_whitelist_and_no_private_values(settings):
    submit(settings, W1, "pass", num=99123)
    coach_ev(settings, W1, "review", 0, "codex", [("edge", "weak", 2)], num=99123)
    fill_week(settings, W2, num0=4000)
    growth.build_missing_snapshots(settings, NOW)
    snaps = growth.load_snapshots(settings)
    payload = growth.comment_payload(snaps[W1], snaps.get(snaps[W1].prev_week))
    assert set(payload) == {
        "period", "baseline", "current", "previous", "weak_categories", "strong_categories", "improved", "strength", "activity", "watch", "persistent",
    }
    dumped = json.dumps(payload, ensure_ascii=False)
    for private in ("99123", "sim", settings.user_id, settings.password, str(settings.root), "codex"):
        assert private not in dumped
    assert payload["period"] == "2026-09-21 ~ 2026-09-27" and payload["weak_categories"][0]["name"] == growth_tags.name_of("edge")


def test_clean_comment_strips_blocks_code_links_and_truncates():
    raw = "이번 주 좋았어요.\n```python\nprint(1)\n```\n[링크](http://x.y) 와 https://z.com 도.\n```profile\n{\"v\":1,\"tags\":[]}\n```\n"
    out = growth.clean_comment(raw)
    assert "```" not in out and "print" not in out and "http" not in out and "링크" in out and "profile" not in out
    assert len(growth.clean_comment("가" * 5000)) == growth.COMMENT_MAX_CHARS
    assert growth.clean_comment("  \n ") == "" and growth.clean_comment("```\ncode only\n```") == ""


# --- 팁 -----------------------------------------------------------------------------------


def three_edge(settings, strength=2, base=None):
    for i in range(3):
        coach_ev(settings, W1, "review", 0, "codex", [("edge", "weak", strength)], num=10 + i, day=i)


def test_tip_after_three_in_a_row_with_cooldown(settings):
    three_edge(settings)
    text = growth.pending_tip(settings, NOW)
    assert text.startswith("성장 팁 · 최근 3번 연속 '경계·예외 조건'이 지적됐어요.") and growth_tags.tip_of("edge") in text
    assert growth.pending_tip(settings, NOW + timedelta(days=1)) is None  # 7일 쿨다운
    assert growth.pending_tip(settings, NOW + timedelta(days=8)) is not None


def test_tip_requires_strength_and_consecutive_and_ok(settings):
    three_edge(settings, strength=1)
    assert growth.pending_tip(settings, NOW) is None
    coach_ev(settings, W1, "review", 0, "codex", [("edge", "weak", 3)], num=20, day=4)
    assert growth.pending_tip(settings, NOW) is None  # 마지막 3개 = 1, 1, 3
    coach_ev(settings, W1, "review", 0, "codex", [("edge", "weak", 3)], num=21, day=4, hour=12)
    coach_ev(settings, W1, "review", 0, "codex", [("edge", "weak", 3)], num=22, day=4, hour=13)
    assert growth.pending_tip(settings, NOW) is not None
    coach_ev(settings, W1, "review", 0, "codex", ok=False, num=23, day=5)  # ok=false 응답은 세지 않는다
    assert growth.pending_tip(settings, NOW + timedelta(days=9)) is not None


def test_tip_ignores_events_older_than_five_weeks(settings):
    three_edge(settings)
    assert growth.pending_tip(settings, NOW + timedelta(days=40)) is None


def test_tip_survives_corrupt_state_file(settings):
    three_edge(settings)
    state = settings.coach_dir / "profile" / "state.json"
    state.write_text("{oops", encoding="utf-8")
    assert growth.pending_tip(settings, NOW) is not None
    assert json.loads(state.read_text(encoding="utf-8"))["tip_shown"]["edge"]


# --- 리포트 / 화면용 행 ---------------------------------------------------------------------------


def test_report_for_in_progress_and_confirmed_weeks(settings):
    fill_week(settings, W2, first_try=1)
    fill_week(settings, W1, first_try=4)
    fill_week(settings, MON, passes=2, first_try=1, wrong=0, tagged=1)
    growth.build_missing_snapshots(settings, NOW)
    rep = growth.report(settings, W1, NOW)
    assert rep.confirmed and not rep.in_progress and rep.prev_week == W2 and rep.baseline
    assert rep.chart_weeks[-1] == W1 and len(rep.chart_weeks) == 8 and rep.chart_stats[-2].passes == 4 and rep.chart_stats[0] is None
    live = growth.report(settings, MON, NOW)
    assert live.in_progress and not live.confirmed and live.stats.passes == 2 and live.prev_week == W1 and live.seen is True
    empty = growth.report(settings, date(2026, 6, 1), NOW)
    assert empty.stats.events == 0 and empty.headline == growth.FIRST_RECORD_TEXT


def test_overview(settings):
    assert growth.overview(settings, NOW).has_events is False
    fill_week(settings, W1)
    fill_week(settings, MON, passes=1, tagged=0, wrong=0)
    growth.build_missing_snapshots(settings, NOW)
    ov = growth.overview(settings, NOW)
    assert ov.has_events and ov.this_week.in_progress and ov.this_week.solved == 1 and ov.this_week.week_start == MON
    assert [w.week_start for w in ov.weeks] == [W1] and ov.weeks[0].unseen and ov.unseen == 1
    assert len(ov.series) == 8 and ov.series[-1] == (MON, 1) and ov.series[-2] == (W1, 4)


def test_metric_and_category_rows(settings):
    fill_week(settings, W2, passes=4, first_try=1, tagged=4, weak=("edge",), wrong=4)
    fill_week(settings, W1, passes=4, first_try=4, tagged=4, weak=("time",), wrong=4)
    growth.build_missing_snapshots(settings, NOW)
    rep = growth.report(settings, W1, NOW)
    rows = {r.key: r for r in growth.metric_rows(rep)}
    assert set(rows) == {"solved", "first_try_rate", "avg_wrong_before_pass", "timeout_share", "assist"}
    assert rows["first_try_rate"].value == "100%" and rows["first_try_rate"].direction == "better" and "좋아짐" in rows["first_try_rate"].change and "+75%p" in rows["first_try_rate"].change
    assert rows["avg_wrong_before_pass"].direction == "better" and rows["avg_wrong_before_pass"].invert
    assert len(rows["solved"].series) == 8 and rows["solved"].series[-1] == 4.0 and rows["solved"].series[0] is None
    weak = growth.category_rows(rep, True)
    assert [r.cid for r in weak] == ["time"] and weak[0].score == 8 and weak[0].value.startswith("점수 8")
    edge_prev = growth.category_rows(growth.report(settings, W2, NOW), True)[0]
    assert edge_prev.change == "비교 불가" and edge_prev.direction == "na"
    assert growth.category_rows(rep, False) == []


def test_metric_rows_without_baseline(settings):
    fill_week(settings, W1)
    growth.build_missing_snapshots(settings, NOW)
    for row in growth.metric_rows(growth.report(settings, W1, NOW)):
        assert row.direction == "na" and row.change == "비교 불가"


# --- 삭제 ---------------------------------------------------------------------------------


def test_clear_removes_only_profile(settings):
    fill_week(settings, W1)
    (settings.coach_dir / "records.json").write_text("{}", encoding="utf-8")
    n = growth.clear(settings.config_dir)
    assert n >= 1 and not (settings.coach_dir / "profile").exists() and (settings.coach_dir / "records.json").exists()
    assert growth.clear(settings.config_dir) == 0
