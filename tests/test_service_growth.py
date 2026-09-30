"""service: 성장 기록 통합 (제출 훅, ask_coach_multi 의 태그 추출·이벤트, generate_growth). 엔진(run)은 대체하고 네트워크·실제 CLI 는 쓰지 않는다."""

from __future__ import annotations

import dataclasses
import json
import threading
from datetime import date, datetime

import pytest

from swea_fetcher import ai_engine, coach, content_cache, growth, growth_tags, service
from swea_fetcher.ai_engine import AiResult, EngineInfo
from swea_fetcher.errors import AiEngineMissing, AiRunFailed, SubmitError
from swea_fetcher.growth_tags import Parsed, Tag
from swea_fetcher.models import ProblemContent
from swea_fetcher.submit import SubmitContext, SubmitResult

NUM = 1234
CODE = "# 1234. A+B\nSECRET_IDENT_ZZZ = int(input())\nprint('#1 3')\n"
NOW = datetime(2026, 9, 30, 12, 0, 0)
W1, W2 = date(2026, 9, 21), date(2026, 9, 14)
CODEX = EngineInfo("codex", "C:/c/codex.cmd")
CLAUDE = EngineInfo("claude", "C:/c/claude.exe")


def block(*tags: tuple[str, str, int]) -> str:
    items = ",".join(f'{{"c":"{c}","k":"{k}","s":{s}}}' for c, k, s in tags)
    return f'```profile\n{{"v":1,"tags":[{items}]}}\n```'


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(growth, "now", lambda: NOW)


@pytest.fixture
def problem(settings):
    d = settings.root / "sim" / str(NUM)
    d.mkdir(parents=True)
    (d / f"{NUM}.py").write_text(CODE, encoding="utf-8")
    (d / "input.txt").write_text("1\n1 2\n", encoding="utf-8")
    (d / "output.txt").write_text("#1 3\n", encoding="utf-8")
    return d


@pytest.fixture
def cached_statement(settings, problem, monkeypatch):
    content_cache.save(settings, NUM, "sim", "A+B", ProblemContent(body_html="<p>두 수를 더하세요</p>"))
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: pytest.fail("지문 캐시가 있으면 네트워크를 쓰지 않는다"))


@pytest.fixture
def ai(monkeypatch):
    """엔진 fake. st["replies"][key] 큐 (소진 후 마지막 반복), st["found"] 설치된 엔진, st["calls"] = [(key, prompt)]."""
    st = {"calls": [], "replies": {"codex": ["## 총평\n좋아요"], "claude": ["## 총평\n괜찮아요"]}, "found": [CODEX], "lock": threading.Lock()}

    def resolve_all(pref="auto"):
        if not st["found"]:
            raise AiEngineMissing("없음")
        return ai_engine.EngineSelection(list(st["found"]), [k for k in ("codex", "claude") if k not in [e.name for e in st["found"]]])

    def run(engine, prompt, **kw):
        with st["lock"]:
            st["calls"].append((engine.name, prompt))
            q = st["replies"][engine.name]
            reply = q.pop(0) if len(q) > 1 else q[0]
        if kw.get("on_start"):
            kw["on_start"](object())
        if isinstance(reply, Exception):
            raise reply
        return AiResult(reply, [engine.name], 1.0)

    monkeypatch.setattr(service.ai_engine, "resolve_all", resolve_all)
    monkeypatch.setattr(service.ai_engine, "run", run)
    return st


def prompts(ai, key=None):
    return [p for k, p in ai["calls"] if key in (None, k)]


def events(settings):
    return growth.read_events(settings)


def no_profile_anywhere(settings, *texts: str) -> None:
    for t in texts:
        assert "```profile" not in t
    for p in settings.coach_dir.rglob("answers/*.json"):
        assert "profile" not in p.read_text(encoding="utf-8")


# --- submit_problem 훅 --------------------------------------------------------------------


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


def test_submit_hook_records_wb_before_this_submit(settings, submit_stub):
    submit_stub["results"] += [SubmitResult(False, "오답"), SubmitResult(False, "오답"), SubmitResult(True, "Pass")]
    for _ in range(3):
        service.submit_problem(settings, "sim", NUM)
    got = [(e.res, e.wb) for e in events(settings)]
    assert got == [("wrong", 0), ("wrong", 1), ("pass", 2)]  # 오답 2회 뒤 Pass -> wb=2
    assert events(settings)[0].num == NUM and events(settings)[0].topic == "sim"


def test_submit_hook_classifies_timeout_and_runtime_error(settings, submit_stub):
    submit_stub["results"] += [SubmitResult(False, "제한시간 초과", timed_out=True), SubmitResult(False, "런타임 에러", run_error="ZeroDivisionError")]
    service.submit_problem(settings, "sim", NUM)
    service.submit_problem(settings, "sim", NUM)
    assert [e.res for e in events(settings)] == ["timeout", "runtime_error"]


def test_submit_error_is_not_recorded(settings, submit_stub):
    submit_stub["results"] += [SubmitError("컴파일 오류")]
    with pytest.raises(SubmitError):
        service.submit_problem(settings, "sim", NUM)
    assert events(settings) == []


def test_growth_record_failure_does_not_change_submit_result(settings, submit_stub, monkeypatch):
    submit_stub["results"] += [SubmitResult(False, "오답")]
    monkeypatch.setattr(growth, "record_submit", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    oc = service.submit_problem(settings, "sim", NUM)
    assert oc.submit.summary == "오답" and oc.coach.wrong_count == 1


def test_growth_off_records_no_submit_event(settings, submit_stub):
    off = dataclasses.replace(settings, growth=False)
    submit_stub["results"] += [SubmitResult(True, "Pass")]
    service.submit_problem(off, "sim", NUM)
    assert events(settings) == []


# --- ask_coach_multi: 태그 추출 · 이벤트 -----------------------------------------------------------


def test_review_block_is_stripped_from_answer_cache_and_events_recorded(settings, problem, ai, cached_statement):
    ai["replies"]["codex"] = ["## 총평\n좋아요\n\n" + block(("edge", "weak", 2), ("pythonic", "strong", 1))]
    res = service.ask_coach_multi(settings, "review", "sim", NUM)
    a = res.outcomes[0].answer
    assert a.markdown == "## 총평\n좋아요" and not a.from_cache
    no_profile_anywhere(settings, a.markdown)
    ev = events(settings)
    assert len(ev) == 1 and ev[0].t == "coach" and ev[0].k == "review" and ev[0].ok and ev[0].eng == "codex" and ev[0].num == NUM and ev[0].topic == "sim"
    assert ev[0].tags == (Tag("edge", "weak", 2), Tag("pythonic", "strong", 1))
    assert "[성장 기록용 분류]" in prompts(ai)[0] and "```profile" in prompts(ai)[0]  # 요청 수는 그대로 1번
    assert len(ai["calls"]) == 1
    text = (settings.coach_dir / "profile" / "events.jsonl").read_text(encoding="utf-8")
    assert "SECRET_IDENT_ZZZ" not in text and "두 수를" not in text and "총평" not in text  # 코드·지문·응답 원문 미저장


def test_cache_hit_creates_no_event(settings, problem, ai, cached_statement):
    ai["replies"]["codex"] = ["## 총평\n좋아요\n" + block(("edge", "weak", 2))]
    service.ask_coach_multi(settings, "review", "sim", NUM)
    again = service.ask_coach_multi(settings, "review", "sim", NUM)
    assert again.outcomes[0].answer.from_cache and len(events(settings)) == 1 and len(ai["calls"]) == 1
    service.ask_coach_multi(settings, "review", "sim", NUM, force_new=True)  # 다시 받기: 새 응답이라 이벤트는 쌓이되 주 집계에서 1건으로 합쳐진다
    assert len(events(settings)) == 2
    assert growth.compute_stats(events(settings)).reviews == 1


def test_missing_or_broken_block_still_shows_answer(settings, problem, ai, cached_statement):
    ai["replies"]["codex"] = ["## 총평\n블록 없음", "## 총평\n깨짐\n```profile\n{oops\n```"]
    r1 = service.ask_coach_multi(settings, "review", "sim", NUM)
    r2 = service.ask_coach_multi(settings, "review", "sim", NUM, force_new=True)
    assert r1.outcomes[0].answer.markdown == "## 총평\n블록 없음" and r2.outcomes[0].answer.markdown == "## 총평\n깨짐"
    assert [e.ok for e in events(settings)] == [False, False]  # 통계 분모에서 제외
    assert growth.compute_stats(events(settings)).tagged == 0


def test_empty_after_stripping_is_a_failure_not_a_blank_answer(settings, problem, ai, cached_statement):
    ai["replies"]["codex"] = [block(("edge", "weak", 1))]
    res = service.ask_coach_multi(settings, "review", "sim", NUM)
    assert res.outcomes[0].answer is None and res.outcomes[0].failure is not None and events(settings) == []


def test_growth_off_has_no_section_no_events_and_block_still_stripped(settings, problem, ai, cached_statement):
    off = dataclasses.replace(settings, growth=False)
    ai["replies"]["codex"] = ["## 총평\n좋아요\n\n" + block(("edge", "weak", 2))]  # AI 가 요청 없이 블록을 낸 경우
    res = service.ask_coach_multi(off, "review", "sim", NUM)
    assert "[성장 기록용 분류]" not in prompts(ai)[0]
    assert res.outcomes[0].answer.markdown == "## 총평\n좋아요" and events(settings) == [] and res.growth_tip is None
    no_profile_anywhere(settings, res.outcomes[0].answer.markdown)
    assert not (settings.coach_dir / "profile").exists()


def test_hint_level_one_requests_no_tags_but_records_usage(settings, problem, ai, cached_statement):
    ai["replies"]["codex"] = ["## 방향\n힌트1\n" + block(("edge", "weak", 3))]  # 요청하지 않았는데 AI 가 낸 블록: 제거하되 태그는 버림
    res = service.ask_coach_multi(settings, "hint", "sim", NUM, submit_summary="오답")
    assert "[성장 기록용 분류]" not in prompts(ai)[0]
    assert "profile" not in res.outcomes[0].answer.markdown
    ev = events(settings)
    assert len(ev) == 1 and (ev[0].k, ev[0].lv, ev[0].ok, ev[0].tags) == ("hint", 1, False, ())
    assert growth.compute_stats(ev).hints == 1


def test_hint_level_two_records_weak_only_and_previous_hints_stay_clean(settings, problem, ai, cached_statement):
    ai["replies"]["codex"] = ["## 방향\n힌트1", "## 위치\n힌트2\n" + block(("edge", "weak", 2), ("pythonic", "strong", 2))]
    service.ask_coach_multi(settings, "hint", "sim", NUM, submit_summary="오답")
    res = service.ask_coach_multi(settings, "hint", "sim", NUM, submit_summary="오답")
    assert "[성장 기록용 분류]" in prompts(ai)[1] and "`weak` 만" in prompts(ai)[1]
    ev = events(settings)
    assert (ev[1].lv, ev[1].ok, ev[1].tags) == (2, True, (Tag("edge", "weak", 2),))  # 힌트의 strong 은 버림
    no_profile_anywhere(settings, res.outcomes[0].answer.markdown)
    ai["replies"]["codex"] = ["## 수정\n힌트3\n" + block(("impl", "weak", 1))]
    service.ask_coach_multi(settings, "hint", "sim", NUM, submit_summary="오답")
    third = prompts(ai)[2]
    assert "힌트2" in third and "profile" not in third.split("<previous_hints>")[1].split("</previous_hints>")[0]  # 다음 힌트 프롬프트로 새지 않음


def test_solution_code_extraction_is_not_polluted(settings, problem, ai, cached_statement):
    ai["replies"]["codex"] = ["## 접근 설명\n설명\n## 정답 코드\n```python\nprint(1)\n```\n\n" + block(("dp", "weak", 2))]
    res = service.ask_coach_multi(settings, "solution", "sim", NUM)
    a = res.outcomes[0].answer
    assert a.code == "print(1)" and "profile" not in a.markdown
    assert events(settings)[0].k == "solution" and events(settings)[0].tags == (Tag("dp", "weak", 2),)
    cached = service.ask_coach_multi(settings, "solution", "sim", NUM).outcomes[0].answer
    assert cached.from_cache and cached.code == "print(1)"


def test_both_mode_two_engine_tags_merge_into_one_group(settings, problem, ai, cached_statement):
    ai["found"] = [CODEX, CLAUDE]
    ai["replies"]["codex"] = ["## 총평\nA\n" + block(("edge", "weak", 1), ("time", "weak", 2))]
    ai["replies"]["claude"] = ["## 총평\nB\n" + block(("edge", "weak", 3))]
    res = service.ask_coach_multi(settings, "review", "sim", NUM)
    assert len(res.succeeded) == 2 and len(events(settings)) == 2 and len(ai["calls"]) == 2
    st = growth.compute_stats(events(settings))
    assert st.reviews == 1 and st.tagged == 1 and st.weak == {"edge": 3, "time": 2}


def test_ping_and_failed_requests_record_nothing(settings, problem, ai, cached_statement):
    ai["replies"]["codex"] = ["OK"]
    service.ask_coach_multi(settings, "ping")
    ai["replies"]["codex"] = [AiRunFailed("boom")]
    res = service.ask_coach_multi(settings, "review", "sim", NUM)
    assert res.all_failed and events(settings) == [] and "profile" not in "".join(prompts(ai)[:1])


def make_problem(settings, num):
    d = settings.root / "sim" / str(num)
    d.mkdir(parents=True)
    (d / f"{num}.py").write_text(CODE.replace("1234", str(num)), encoding="utf-8")
    return d


def test_growth_tip_once_then_cooldown(settings, problem, ai, cached_statement, monkeypatch):
    for n in (1235, 1236, 1237):
        make_problem(settings, n)
    monkeypatch.setattr(service, "_gather_statement", lambda *a, **k: ("", "", []))
    ai["replies"]["codex"] = ["## 총평\nx\n" + block(("edge", "weak", 2))]
    tips = [service.ask_coach_multi(settings, "review", "sim", n).growth_tip for n in (NUM, 1235, 1236, 1237)]
    assert tips[0] is None and tips[1] is None and tips[2] and "경계·예외 조건" in tips[2] and growth_tags.tip_of("edge") in tips[2]
    assert tips[3] is None  # 7일 쿨다운
    assert service.ask_coach_multi(settings, "review", "sim", NUM).growth_tip is None  # 캐시 적중만이면 팁도 없음


def test_growth_write_failure_does_not_break_answer(settings, problem, ai, cached_statement, monkeypatch):
    monkeypatch.setattr(growth, "record_coach", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    res = service.ask_coach_multi(settings, "review", "sim", NUM)
    assert res.outcomes[0].answer is not None and res.growth_tip is None


def test_ask_coach_rejects_weekly_kind(settings, problem, ai):
    with pytest.raises(ValueError):
        service.ask_coach_multi(settings, "weekly", "sim", NUM)
    with pytest.raises(ValueError):
        service.ask_coach(settings, "weekly", "sim", NUM)


# --- generate_growth ------------------------------------------------------------------------


def seed(settings, week=W1, n=4, num0=50000):
    """week 에 Pass n 건 + 코치 3건 (약점 edge)."""
    for i in range(n):
        growth.record_submit(settings, num0 + i, "secret_topic", "pass", 0, at=datetime(week.year, week.month, week.day + i % 5, 10))
    for i in range(3):
        growth.record_coach(settings, num0 + i, "secret_topic", "review", 0, "codex", Parsed((Tag("edge", "weak", 2),)), at=datetime(week.year, week.month, week.day + i, 11))


def yes(_key):
    return True


def test_generate_growth_happy_path_single_call(settings, ai):
    seed(settings)
    ai["replies"]["codex"] = ["이번 주 잘하셨어요. 다음 주 초점: 경계.\n```python\nprint(1)\n```"]
    seen = {"stats": [], "comment": [], "begin": [], "start": 0}
    res = service.generate_growth(
        settings, now=NOW, consent_ok=yes, on_start=lambda p: seen.__setitem__("start", seen["start"] + 1),
        on_begin=seen["begin"].append, on_stats=seen["stats"].append, on_comment=lambda w, t: seen["comment"].append((w, t)),
    )
    assert res.new_weeks == [W1] and res.commented_week == W1 and res.blocked is None and res.failure is None
    assert len(ai["calls"]) == 1 and seen["stats"] == [[W1]] and seen["begin"] == [W1] and seen["start"] == 1
    assert seen["comment"] == [(W1, "이번 주 잘하셨어요. 다음 주 초점: 경계.")]  # 코드 펜스 제거
    snap = growth.load_snapshots(settings)[W1]
    assert snap.comment_status == "ok" and snap.comment["engine"] == CODEX.label and "잘하셨어요" in snap.comment["text"]
    again = service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert again.new_weeks == [] and again.commented_week is None and len(ai["calls"]) == 1  # 이미 코멘트가 있으면 호출 없음


def test_weekly_prompt_privacy(settings, ai):
    seed(settings)
    growth.record_submit(settings, 77123, "secret_topic", "wrong", 0, at=datetime(2026, 9, 22, 9))
    service.generate_growth(settings, now=NOW, consent_ok=yes)
    prompt = prompts(ai)[0]
    for private in (settings.user_id, settings.password, str(settings.root), str(settings.config_dir), "77123", "50000", "secret_topic", "SECRET_IDENT_ZZZ", "sim/"):
        assert private not in prompt
    assert "<weekly_stats>" in prompt and "경계·예외 조건" in prompt and "2026-09-21 ~ 2026-09-27" in prompt
    assert "```" not in prompt  # 프로필 요청 섹션·코드 블록이 붙지 않는다


def test_consent_false_means_no_call_and_no_attempt_used(settings, ai):
    seed(settings)
    res = service.generate_growth(settings, now=NOW, consent_ok=lambda k: False)
    assert res.blocked == "needs_consent" and res.engine_key == "codex" and ai["calls"] == []
    snap = growth.load_snapshots(settings)[W1]
    assert snap.comment_status == "pending" and snap.comment_attempts == 0 and res.new_weeks == [W1]  # 통계는 만들어짐
    ok = service.generate_growth(settings, now=NOW, consent_ok=yes)  # 동의 뒤 재시도
    assert ok.commented_week == W1


def test_consent_is_checked_for_the_engine_that_will_run(settings, ai):
    ai["found"] = [CODEX, CLAUDE]  # both: 첫 설치 엔진(Codex)만
    seed(settings)
    asked = []
    res = service.generate_growth(settings, now=NOW, consent_ok=lambda k: asked.append(k) or k == "codex")
    assert asked == ["codex"] and res.commented_week == W1 and [k for k, _ in ai["calls"]] == ["codex"]


def test_both_uses_only_first_installed_engine_codex_first(settings, ai):
    ai["found"] = [CODEX, CLAUDE]
    seed(settings)
    service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert [k for k, _ in ai["calls"]] == ["codex"]
    assert service.growth_comment_engine(settings).name == "codex"
    ai["found"] = [CLAUDE]
    assert service.growth_comment_engine(settings).name == "claude"


def test_no_engine(settings, ai):
    ai["found"] = []
    seed(settings)
    res = service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert res.blocked == "no_engine" and ai["calls"] == []
    assert growth.load_snapshots(settings)[W1].comment_attempts == 0


def test_pinned_engine_missing_has_no_fallback(settings, monkeypatch):
    seed(settings)
    monkeypatch.setattr(ai_engine, "_which", lambda name: "C:/c/codex.cmd" if name == "codex" else None)
    monkeypatch.setattr(ai_engine, "run", lambda *a, **k: pytest.fail("고정 엔진이 없으면 다른 엔진으로 보내지 않는다"))
    pinned = dataclasses.replace(settings, ai_engine="claude")
    res = service.generate_growth(pinned, now=NOW, consent_ok=yes)
    assert res.blocked == "no_engine"
    assert service.growth_comment_blocker(pinned, yes) == "no_engine"


def test_failure_keeps_stats_counts_attempts_and_stops_after_two(settings, ai):
    seed(settings)
    ai["replies"]["codex"] = [AiRunFailed("boom")]
    res = service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert res.failure is not None and res.commented_week is None and res.new_weeks == [W1]
    snap = growth.load_snapshots(settings)[W1]
    assert snap.comment_status == "failed" and snap.comment_attempts == 1 and snap.stats.passes == 4  # 통계 보존
    service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert growth.load_snapshots(settings)[W1].comment_attempts == 2 and len(ai["calls"]) == 2
    third = service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert len(ai["calls"]) == 2 and third.failure is None  # 자동 재시도는 총 2회까지
    ai["replies"]["codex"] = ["이제 됐어요"]
    manual = service.generate_growth(settings, now=NOW, consent_ok=yes, force_week=W1)  # 이후는 [다시 받기] 로만
    assert manual.commented_week == W1 and len(ai["calls"]) == 3


def test_empty_response_is_a_failure(settings, ai):
    seed(settings)
    ai["replies"]["codex"] = ["```python\nprint(1)\n```"]
    res = service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert res.failure is not None and growth.load_snapshots(settings)[W1].comment_status == "failed"


def test_low_data_week_never_calls_ai(settings, ai):
    growth.record_submit(settings, 1, "t", "pass", 0, at=datetime(2026, 9, 22, 9))
    growth.record_submit(settings, 2, "t", "wrong", 0, at=datetime(2026, 9, 22, 10))
    res = service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert res.new_weeks == [W1] and ai["calls"] == [] and res.commented_week is None
    assert growth.load_snapshots(settings)[W1].comment_status == "skipped_low_data"
    forced = service.generate_growth(settings, now=NOW, consent_ok=yes, force_week=W1)
    assert forced.blocked == "low_data" and ai["calls"] == []


def test_backlog_weeks_get_stats_only_and_latest_gets_comment(settings, ai):
    seed(settings, W2, num0=60000)
    seed(settings, W1, num0=70000)
    res = service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert res.new_weeks == [W2, W1] and res.commented_week == W1 and len(ai["calls"]) == 1
    snaps = growth.load_snapshots(settings)
    assert snaps[W2].comment_status == "skipped_backlog" and snaps[W2].comment is None
    assert snaps[W1].prev_week == W2


def test_manual_force_week_ignores_toggle_and_backlog(settings, ai):
    seed(settings, W2, num0=60000)
    seed(settings, W1, num0=70000)
    off = dataclasses.replace(settings, growth_comment=False)
    auto = service.generate_growth(off, now=NOW, consent_ok=yes)
    assert auto.new_weeks == [W2, W1] and ai["calls"] == [] and auto.commented_week is None  # 자동 끔: 통계만
    manual = service.generate_growth(off, now=NOW, consent_ok=yes, force_week=W2)
    assert manual.commented_week == W2 and len(ai["calls"]) == 1
    assert growth.load_snapshots(settings)[W2].comment_status == "ok"


def test_cancel_leaves_state_unchanged(settings, ai):
    seed(settings)
    res = service.generate_growth(settings, now=NOW, consent_ok=yes, is_cancelled=lambda: True)
    assert res.cancelled and ai["calls"] == []
    snap = growth.load_snapshots(settings)[W1]
    assert snap.comment_status == "pending" and snap.comment_attempts == 0


def test_cancel_during_run_leaves_state_unchanged(settings, ai, monkeypatch):
    seed(settings)
    monkeypatch.setattr(service.ai_engine, "run", lambda *a, **k: AiResult("", [], 0.1, cancelled=True))
    res = service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert res.cancelled and res.failure is None
    assert growth.load_snapshots(settings)[W1].comment_attempts == 0


def test_comment_strips_profile_block_defensively(settings, ai):
    seed(settings)
    ai["replies"]["codex"] = ["좋았어요.\n" + block(("edge", "weak", 1))]
    service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert growth.load_snapshots(settings)[W1].comment["text"] == "좋았어요."


def test_growth_off_returns_immediately(settings, ai):
    seed(settings)
    off = dataclasses.replace(settings, growth=False)
    res = service.generate_growth(off, now=NOW, consent_ok=yes)
    assert res.blocked == "off" and ai["calls"] == [] and growth.load_snapshots(settings) == {}
    assert service.growth_due(off, NOW) is False and service.growth_unseen_count(off) == 0
    assert service.growth_comment_blocker(off, yes) == "off"


def test_blocker_states(settings, ai):
    assert service.growth_comment_blocker(settings, yes) is None
    assert service.growth_comment_blocker(settings, lambda k: False) == "needs_consent"
    off = dataclasses.replace(settings, growth_comment=False)
    assert service.growth_comment_blocker(off, yes) == "comment_off"
    assert service.growth_comment_blocker(off, yes, manual=True) is None
    ai["found"] = []
    assert service.growth_comment_blocker(settings, yes) == "no_engine"


def test_due_overview_report_and_seen_wrappers(settings, ai):
    assert service.growth_due(settings, NOW) is False
    seed(settings)
    assert service.growth_due(settings, NOW) is True
    service.generate_growth(settings, now=NOW, consent_ok=yes)
    assert service.growth_due(settings, NOW) is False
    ov = service.growth_overview(settings, NOW)
    assert ov.unseen == 1 and service.growth_unseen_count(settings) == 1
    rep = service.growth_report(settings, W1, NOW)
    assert rep.confirmed and rep.comment_status == "ok"
    service.growth_mark_seen(settings, W1, NOW)
    assert service.growth_unseen_count(settings) == 0


# --- 삭제 ---------------------------------------------------------------------------------


def test_logout_all_and_clear_growth(settings, ai):
    seed(settings)
    service.generate_growth(settings, now=NOW, consent_ok=yes)
    (settings.coach_dir / "records.json").write_text("{}", encoding="utf-8")
    assert service.clear_growth(settings.config_dir) >= 2
    assert not (settings.coach_dir / "profile").exists() and (settings.coach_dir / "records.json").exists()  # profile/ 만
    seed(settings)
    removed = service.logout(settings.config_dir, all_=True)
    assert "AI 코치 기록" in removed and not settings.coach_dir.exists()  # logout --all 은 coach/ 전체 (성장 기록 포함)


def test_clear_coach_includes_growth(settings):
    seed(settings)
    service.clear_coach(settings.config_dir)
    assert not (settings.coach_dir / "profile").exists()
