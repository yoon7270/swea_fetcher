"""M22: 최근 탭 상태 판정 (스펙 §17.12) — Qt 없이 표 기반."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from swea_fetcher import coach, service, solved

SUBMIT = "2026-09-30T14:44:00"
EARLIER = "2026-09-29T09:00:00"
LATER = "2026-10-01T09:00:00"


def rec(result: str, at: str = SUBMIT):
    return coach.ProblemRecord(1, last_result=result, last_submit_at=at)


def sol(at: str, via: str = "swea"):
    return solved.SolvedItem(1, "sim", "t", via, at)


def rev(days: int):
    return coach.ReviewItem(1, "sim", "t", date(2026, 10, 1), days)


@pytest.mark.parametrize(
    "r,s,expected",
    [
        (None, None, "none"),
        (rec("wrong"), None, "wrong"),
        (rec("wrong"), sol(LATER), "pass"),  # solved 가 마지막 제출보다 새롭다
        (rec("wrong"), sol(SUBMIT), "pass"),  # 같으면 Pass
        (rec("timeout"), sol(EARLIER), "timeout"),
        (rec("runtime_error"), sol(EARLIER), "runtime_error"),
        (rec("runtime_error"), None, "runtime_error"),
        (rec("pass"), None, "pass"),  # 400일 경과·백필 누락
        (rec("pass"), sol(EARLIER), "pass"),
        (None, sol(EARLIER), "pass"),
        (rec(""), None, "none"),
    ],
)
def test_problem_status_table(r, s, expected):
    st = service.problem_status(r, s)
    assert st.key == expected and st.label == service.STATUS_LABELS[expected]


def test_pass_detail_distinguishes_swea_and_local():
    assert service.problem_status(None, sol(EARLIER, "swea")).detail == "SWEA Pass"
    assert service.problem_status(None, sol(EARLIER, "local")).detail == "로컬 Pass"


@pytest.mark.parametrize(
    "days,tag",
    [(3, ("복습 3일 지남", "due")), (0, ("복습 오늘", "due")), (-2, ("복습 2일 뒤", "upcoming"))],
)
def test_review_tag_is_independent_of_status(days, tag):
    for r in (None, rec("wrong")):
        assert service.problem_status(r, None, rev(days)).review_tag == tag
    assert service.problem_status(rec("wrong"), None, None).review_tag is None


def test_problem_statuses_reads_files_and_survives_corruption(settings):
    ok = SimpleNamespace(passed=False, summary="오답", run_error="", timed_out=False)
    coach.record_submit(settings, 10, "sim", "a", ok)
    coach.record_submit(settings, 11, "sim", "b", SimpleNamespace(passed=True, summary="Pass", run_error="", timed_out=False))
    solved.record(settings, 12, "sim", "c", "local", at=datetime.now() - timedelta(days=1))
    got = service.problem_statuses(settings, [10, 11, 12, 13])
    assert [got[n].key for n in (10, 11, 12, 13)] == ["wrong", "pass", "pass", "none"]
    (settings.coach_dir / coach.RECORDS_FILE).write_text("{ 깨진 json", encoding="utf-8")
    got = service.problem_statuses(settings, [10])  # 예외 없이 (손상 기록은 비어 있는 것으로 취급)
    assert got.get(10) is None or got[10].key in ("none", "pass")
