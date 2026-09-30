"""coach: 학습 기록·복습 일정·응답 캐시 (순수, 날짜 주입)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from swea_fetcher import coach
from swea_fetcher.submit import SubmitResult

T0 = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 14, 0, 0)


def wrong(**kw) -> SubmitResult:
    return SubmitResult(False, kw.pop("summary", "오답: 10개 중 7개"), **kw)


PASS = SubmitResult(True, "Pass")


def rec(settings, num=25730):
    return coach.get_record(settings, num)


def submit(settings, result, num=25730, today=T0):
    return coach.record_submit(settings, num, "IM_test", "항아리 게임", result, now=NOW, today=today)


def test_wrong_accumulates_and_classifies(settings):
    assert submit(settings, wrong()).wrong_count == 1
    r = submit(settings, wrong(timed_out=True))
    assert r.wrong_count == 2 and r.last_result == "timeout"
    assert submit(settings, wrong(run_error="IndexError")).last_result == "runtime_error"
    r = rec(settings)
    assert r.wrong_count == 3 and r.topic == "IM_test" and r.title == "항아리 게임" and r.last_submit_at == "2026-09-30T14:00:00"
    assert coach.classify(False, "오답") == "wrong" and coach.classify(True) == "pass"


def test_pass_resets_count_and_offer_dismissed(settings):
    submit(settings, wrong())
    coach.dismiss_offer(settings, 25730)
    assert rec(settings).offer_dismissed
    r = submit(settings, PASS)
    assert r.wrong_count == 0 and not r.offer_dismissed and r.last_result == "pass"


def test_thresholds(settings):
    r = None
    for _ in range(3):
        r = submit(settings, wrong())
    assert coach.should_offer(r, 3) and coach.show_solution_button(r, 3)
    assert not coach.should_offer(r, 4) and not coach.show_solution_button(r, 4)  # 기준 미만이면 버튼도 숨김
    coach.dismiss_offer(settings, 25730)
    r = rec(settings)
    assert not coach.should_offer(r, 3) and coach.show_solution_button(r, 3)  # 거절해도 버튼은 유지
    assert not coach.should_offer(None, 3)


def test_solution_viewed_schedules_review_and_resets(settings):
    for _ in range(3):
        submit(settings, wrong())
    r = coach.mark_solution_viewed(settings, 25730, 3, now=NOW, today=T0)
    assert r.wrong_count == 0 and r.review_due == "2026-10-03" and r.solution_viewed_at == "2026-09-30T14:00:00"


def test_solution_viewed_keeps_future_schedule(settings):
    coach.mark_solution_viewed(settings, 25730, 5, now=NOW, today=T0)
    r = coach.mark_solution_viewed(settings, 25730, 1, now=NOW, today=T0 + timedelta(days=1))
    assert r.review_due == "2026-10-05"  # 아직 미래라 유지
    r = coach.mark_solution_viewed(settings, 25730, 2, now=NOW, today=date(2026, 10, 5))
    assert r.review_due == "2026-10-07"  # 도래했으면 새로 예약


def test_pass_before_due_does_not_complete_review(settings):
    coach.mark_solution_viewed(settings, 25730, 3, now=NOW, today=T0)
    r = submit(settings, PASS, today=T0)  # 열람 당일 바로 Pass
    assert r.review_due == "2026-10-03" and r.review_done_at is None
    r = submit(settings, PASS, today=date(2026, 10, 2))
    assert r.review_due == "2026-10-03"


def test_pass_on_or_after_due_completes_review(settings):
    coach.mark_solution_viewed(settings, 25730, 3, now=NOW, today=T0)
    r = submit(settings, PASS, today=date(2026, 10, 3))
    assert r.review_due is None and r.review_done_at == "2026-09-30T14:00:00"


def test_dismiss_review(settings):
    coach.mark_solution_viewed(settings, 25730, 3, now=NOW, today=T0)
    assert coach.dismiss_review(settings, 25730).review_due is None
    assert coach.dismiss_review(settings, 999) is None  # 기록 없음


def test_review_items_sorted_and_overdue_days(settings):
    coach.mark_solution_viewed(settings, 300, 3, now=NOW, today=T0)  # 10-03
    coach.mark_solution_viewed(settings, 100, 1, now=NOW, today=T0 - timedelta(days=4))  # 09-27 (3일 지남)
    coach.mark_solution_viewed(settings, 200, 1, now=NOW, today=T0 - timedelta(days=1))  # 10-00 => 09-30 (오늘)
    submit(settings, wrong(), num=400)  # 복습 없음
    items = coach.review_items(settings, today=T0)
    assert [i.num for i in items] == [100, 200, 300]
    assert [i.overdue_days for i in items] == [3, 0, -3]
    assert [i.is_due for i in items] == [True, True, False]
    assert coach.due_count(settings, today=T0) == 2


def test_review_items_ignores_bad_date(settings):
    coach.mark_solution_viewed(settings, 1, 3, now=NOW, today=T0)
    path = settings.coach_dir / coach.RECORDS_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    data["problems"]["1"]["review_due"] = "not-a-date"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert coach.review_items(settings, T0) == []


def test_corrupt_records_backed_up(settings):
    submit(settings, wrong())
    path = settings.coach_dir / coach.RECORDS_FILE
    path.write_text("{not json", encoding="utf-8")
    assert coach.get_record(settings, 25730) is None
    assert (settings.coach_dir / "records.json.corrupt").read_text(encoding="utf-8") == "{not json"
    assert submit(settings, wrong()).wrong_count == 1  # 빈 상태로 다시 시작


def test_refuses_to_write_inside_root(root_dir, config_dir):
    from swea_fetcher.config import Settings

    s = Settings(root=root_dir, user_id="u", password="p", config_dir=root_dir / ".cfg")  # coach 디렉터리가 루트 안
    assert submit(s, wrong()) is not None  # 예외 없음
    assert not (root_dir / ".cfg").exists()
    assert not coach.save_answers(s, coach.AnswerCache(1, "x"))
    assert not (root_dir / ".cfg").exists()


def test_atomic_write_leaves_no_tmp(settings):
    submit(settings, wrong())
    coach.save_answers(settings, coach.AnswerCache(1, coach.code_hash("x")))
    leftovers = [p for p in settings.coach_dir.rglob("*") if p.suffix == ".tmp"]
    assert leftovers == []


def test_record_prune_over_500_keeps_active(settings, monkeypatch):
    monkeypatch.setattr(coach, "MAX_PROBLEMS", 5)
    for n in range(1, 8):
        coach.record_submit(settings, n, "t", "", PASS, now=datetime(2026, 1, n), today=T0)
    coach.mark_solution_viewed(settings, 1, 3, now=NOW, today=T0)  # 가장 오래됐지만 복습 중
    coach.record_submit(settings, 8, "t", "", wrong(), now=NOW, today=T0)  # 진행 중(오답 1)
    nums = {int(k) for k in coach._load_records(settings)}
    assert len(nums) == 5 and 1 in nums and 8 in nums


def test_never_raises(settings, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(coach, "_atomic_write", boom)
    r = submit(settings, wrong())
    assert r is not None and r.wrong_count == 1  # 저장 실패해도 스냅샷은 돌려줌
    monkeypatch.setattr(coach, "_load_records", boom)
    assert submit(settings, wrong()) is None
    assert coach.mark_solution_viewed(settings, 1, 3) is None


# --- 응답 캐시 --------------------------------------------------------------------------


def test_answer_cache_roundtrip_and_hash_invalidation(settings):
    code = "print(1)\n"
    c = coach.load_answers(settings, 7, code)
    c.hints = [{"level": 1, "markdown": "힌트1"}]
    c.review = {"markdown": "평가"}
    c.solution = {"markdown": "풀이"}
    assert coach.save_answers(settings, c)
    same = coach.load_answers(settings, 7, "print(1)\r\n")  # 개행 정규화
    assert same.hints[0]["markdown"] == "힌트1" and same.review["markdown"] == "평가"
    changed = coach.load_answers(settings, 7, "print(2)\n")
    assert changed.hints == [] and changed.review is None and changed.solution["markdown"] == "풀이"  # solution 은 유지


def test_answer_cache_corrupt_ignored(settings):
    coach.save_answers(settings, coach.AnswerCache(7, coach.code_hash("x")))
    (settings.coach_dir / coach.ANSWERS_DIR / "7.json").write_text("garbage", encoding="utf-8")
    c = coach.load_answers(settings, 7, "x")
    assert c.hints == [] and c.solution is None


def test_answer_cache_lru_prune(settings, monkeypatch):
    import os

    monkeypatch.setattr(coach, "MAX_ANSWER_FILES", 3)
    d = settings.coach_dir / coach.ANSWERS_DIR
    for n in range(1, 6):
        coach.save_answers(settings, coach.AnswerCache(n, "h"))
        os.utime(d / f"{n}.json", (n, n))  # mtime 을 번호순으로 고정
    coach.save_answers(settings, replace(coach.AnswerCache(6, "h")))
    assert sorted(int(p.stem) for p in d.glob("*.json")) == [4, 5, 6]


def test_clear_removes_everything_and_counts(settings, config_dir):
    submit(settings, wrong())
    coach.save_answers(settings, coach.AnswerCache(1, "h"))
    assert coach.clear(config_dir) == 2
    assert not settings.coach_dir.exists()
    assert coach.clear(config_dir) == 0
