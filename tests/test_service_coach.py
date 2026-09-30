"""service: AI 코치 통합 (제출 훅·ask_coach·logout). 엔진(run)은 대체하고 네트워크·실제 CLI 는 쓰지 않는다."""

from __future__ import annotations

import pytest

from swea_fetcher import ai_engine, ai_prompts, coach, content_cache, service
from swea_fetcher.ai_engine import AiResult, EngineInfo
from swea_fetcher.errors import AiEngineMissing, AiRunFailed, AiTimeout, NetworkError, SubmitError
from swea_fetcher.models import ProblemContent
from swea_fetcher.submit import SubmitContext, SubmitResult

NUM = 1234
CODE = "# 1234. A+B\nT = int(input())\nprint('#1 3')\n"


@pytest.fixture
def problem(settings):
    d = settings.root / "sim" / str(NUM)
    d.mkdir(parents=True)
    (d / f"{NUM}.py").write_text(CODE, encoding="utf-8")
    (d / "input.txt").write_text("1\n1 2\n", encoding="utf-8")
    (d / "output.txt").write_text("#1 3\n", encoding="utf-8")
    return d


# --- submit_problem 훅 --------------------------------------------------------------------


@pytest.fixture
def submit_stub(settings, problem, monkeypatch):
    """제출 경계 스텁. results 큐에서 SubmitResult 를 꺼내거나 예외를 던진다."""
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


def test_submit_records_wrong_count(settings, submit_stub):
    submit_stub["results"] += [SubmitResult(False, "오답: 10개 중 7개"), SubmitResult(False, "오답: 10개 중 8개")]
    service.submit_problem(settings, "sim", NUM)
    oc = service.submit_problem(settings, "sim", NUM)
    assert oc.submit.passed is False and oc.coach.wrong_count == 2
    assert oc.coach.title == "A+B" and oc.coach.topic == "sim"


def test_submit_pass_resets(settings, submit_stub):
    submit_stub["results"] += [SubmitResult(False, "오답"), SubmitResult(True, "Pass")]
    service.submit_problem(settings, "sim", NUM)
    oc = service.submit_problem(settings, "sim", NUM)
    assert oc.coach.wrong_count == 0 and oc.coach.last_result == "pass"


def test_submit_error_is_not_counted(settings, submit_stub):
    submit_stub["results"] += [SubmitError("컴파일 오류")]
    with pytest.raises(SubmitError):
        service.submit_problem(settings, "sim", NUM)
    assert coach.get_record(settings, NUM) is None


def test_submit_result_survives_coach_failure(settings, submit_stub, monkeypatch):
    submit_stub["results"] += [SubmitResult(False, "오답")]
    monkeypatch.setattr(coach, "_atomic_write", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    oc = service.submit_problem(settings, "sim", NUM)
    assert oc.submit.summary == "오답"  # 제출 결과는 그대로


# --- ask_coach -----------------------------------------------------------------------------


@pytest.fixture
def ai(monkeypatch):
    """엔진 해석/실행 대체. calls 에 (prompt, kwargs) 기록, replies 큐 소진 후 마지막 응답 반복."""
    st = {"calls": [], "replies": ["기본 응답"], "engine": EngineInfo("codex", "C:/c/codex.cmd")}
    monkeypatch.setattr(service.ai_engine, "resolve", lambda pref="auto": st["engine"])

    def run(engine, prompt, **kw):
        st["calls"].append((prompt, kw))
        reply = st["replies"].pop(0) if len(st["replies"]) > 1 else st["replies"][0]
        if isinstance(reply, Exception):
            raise reply
        return AiResult(reply, ["codex", "exec"], 1.5)

    monkeypatch.setattr(service.ai_engine, "run", run)
    return st


@pytest.fixture
def cached_statement(settings, problem):
    body = "<p>두 수를 더하세요</p>"
    content_cache.save(settings, NUM, "sim", "A+B", ProblemContent(body_html=body))


@pytest.fixture
def no_fetch(monkeypatch):
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: pytest.fail("지문 캐시가 있으면 네트워크를 쓰지 않는다"))


def test_engine_missing_fails_before_collecting(settings, problem, monkeypatch):
    def boom(*a, **k):
        pytest.fail("엔진이 없으면 자료 수집 전에 실패해야 한다")

    monkeypatch.setattr(service, "fetch_problem", boom)
    monkeypatch.setattr(service.submit, "read_solution", boom)
    with pytest.raises(AiEngineMissing):
        service.ask_coach(settings, "review", "sim", NUM)


def test_review_uses_cached_statement_and_caches(settings, problem, ai, cached_statement, no_fetch):
    ai["replies"] = ["## 총평\n좋아요"]
    a = service.ask_coach(settings, "review", "sim", NUM)
    assert a.markdown.startswith("## 총평") and a.engine == "GPT (Codex)" and a.engine_key == "codex" and not a.from_cache and a.notes == []
    prompt = ai["calls"][0][0]
    assert "두 수를 더하세요" in prompt and "T = int(input())" in prompt and "1 2" in prompt and "#1 3" in prompt
    a2 = service.ask_coach(settings, "review", "sim", NUM)
    assert a2.from_cache and a2.markdown == a.markdown and len(ai["calls"]) == 1  # 엔진 재호출 없음
    service.ask_coach(settings, "review", "sim", NUM, force_new=True)
    assert len(ai["calls"]) == 2


def test_prompt_has_no_paths_or_credentials(settings, problem, ai, cached_statement, no_fetch):
    service.ask_coach(settings, "review", "sim", NUM)
    prompt = ai["calls"][0][0]
    for secret in (settings.user_id, settings.password, str(settings.root), str(settings.config_dir)):
        assert secret not in prompt


def test_no_cache_and_fetch_failure_proceeds_without_statement(settings, problem, ai, monkeypatch):
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: (_ for _ in ()).throw(NetworkError("offline")))
    a = service.ask_coach(settings, "review", "sim", NUM)
    assert "지문 없이 코드만으로 답했습니다" in a.notes
    assert "지문을 받지 못했습니다" in ai["calls"][0][0]


def test_hint_progression_accumulates_and_filters(settings, problem, ai, cached_statement, no_fetch):
    long_code = "```python\n" + "\n".join("x = 1" for _ in range(8)) + "\n```"
    ai["replies"] = [f"방향 힌트\n{long_code}", "위치 힌트", "수정 힌트"]
    kw = dict(submit_summary="오답: 10개 중 7개")
    h1 = service.ask_coach(settings, "hint", "sim", NUM, **kw)
    assert (h1.level, h1.max_level) == (1, 3) and "긴 코드 블록을 제거했습니다" in h1.notes
    assert ai_prompts.CODE_REMOVED in h1.markdown and "x = 1" not in h1.markdown
    h2 = service.ask_coach(settings, "hint", "sim", NUM, **kw)
    assert h2.level == 2 and "방향 힌트" in h2.markdown and "위치 힌트" in h2.markdown
    assert "방향 힌트" in ai["calls"][1][0] and "<previous_hints>" in ai["calls"][1][0]  # 이전 힌트가 다음 프롬프트에
    h3 = service.ask_coach(settings, "hint", "sim", NUM, **kw)
    assert h3.level == 3 and service.hint_level(settings, "sim", NUM) == 3
    h4 = service.ask_coach(settings, "hint", "sim", NUM, **kw)
    assert h4.from_cache and h4.level == 3 and len(ai["calls"]) == 3  # 3단계 이후엔 호출 없음
    h3b = service.ask_coach(settings, "hint", "sim", NUM, force_new=True, **kw)  # [다시 받기]: 마지막 단계만
    assert h3b.level == 3 and not h3b.from_cache and len(ai["calls"]) == 4


def test_hint_progress_reset_when_code_changes(settings, problem, ai, cached_statement, no_fetch):
    service.ask_coach(settings, "hint", "sim", NUM)
    (problem / f"{NUM}.py").write_text(CODE + "# edited\n", encoding="utf-8")
    assert service.hint_level(settings, "sim", NUM) == 0
    assert service.ask_coach(settings, "hint", "sim", NUM).level == 1


def test_solution_sets_review_and_leaves_solution_file_alone(settings, problem, ai, cached_statement, no_fetch):
    before = (problem / f"{NUM}.py").read_bytes()
    files_before = sorted(p.name for p in problem.parent.iterdir())
    for _ in range(3):
        coach.record_submit(settings, NUM, "sim", "A+B", SubmitResult(False, "오답"))
    ai["replies"] = ["## 접근 설명\n...\n## 정답 코드\n```python\nprint(1)\n```\n"]
    a = service.ask_coach(settings, "solution", "sim", NUM)
    assert a.code == "print(1)" and a.review_due is not None
    rec = coach.get_record(settings, NUM)
    assert rec.wrong_count == 0 and rec.review_due == a.review_due.isoformat() and rec.solution_viewed_at
    assert (a.review_due - __import__("datetime").date.today()).days == settings.review_days
    assert (problem / f"{NUM}.py").read_bytes() == before  # 바이트 불변
    assert sorted(p.name for p in problem.parent.iterdir()) == files_before
    assert not any("정답 코드" in p.read_text(encoding="utf-8", errors="ignore") for p in settings.root.rglob("*") if p.is_file())
    again = service.ask_coach(settings, "solution", "sim", NUM)
    assert again.from_cache and again.code == "print(1)" and len(ai["calls"]) == 1


def test_solution_failure_does_not_mark_viewed(settings, problem, ai, cached_statement, no_fetch):
    coach.record_submit(settings, NUM, "sim", "A+B", SubmitResult(False, "오답"))
    ai["replies"] = [AiRunFailed("실패")]
    with pytest.raises(AiRunFailed):
        service.ask_coach(settings, "solution", "sim", NUM)
    rec = coach.get_record(settings, NUM)
    assert rec.wrong_count == 1 and rec.review_due is None


def test_cancelled_result_is_not_cached(settings, problem, ai, cached_statement, no_fetch, monkeypatch):
    monkeypatch.setattr(service.ai_engine, "run", lambda *a, **k: AiResult("", [], 0.1, cancelled=True))
    a = service.ask_coach(settings, "solution", "sim", NUM)
    assert a.cancelled and coach.get_record(settings, NUM) is None
    assert coach.load_answers(settings, NUM, CODE).slot("codex").solution is None


def test_cancel_before_engine_when_flag_set(settings, problem, ai, cached_statement, no_fetch):
    a = service.ask_coach(settings, "review", "sim", NUM, is_cancelled=lambda: True)
    assert a.cancelled and ai["calls"] == []


def test_ping_needs_no_material_and_adds_argv_on_failure(settings, ai):
    a = service.ask_coach(settings, "ping")
    assert a.markdown == "기본 응답" and ai["calls"][0][0] == "`OK` 라고만 답하세요."
    ai["replies"] = [AiRunFailed("실패 (코드 2)", hint="stderr 내용", argv=["codex", "exec", "--bogus"])]
    with pytest.raises(AiRunFailed) as ei:
        service.ask_coach(settings, "ping")
    assert "codex exec --bogus" in ei.value.hint and "stderr 내용" in ei.value.hint


def test_missing_solution_file_and_bad_kind(settings, ai):
    with pytest.raises(SubmitError):
        service.ask_coach(settings, "review", "sim", 999)
    with pytest.raises(ValueError):
        service.ask_coach(settings, "bogus", "sim", NUM)


def test_review_items_and_wrappers(settings):
    coach.mark_solution_viewed(settings, 7, 3)
    assert [i.num for i in service.review_items(settings)] == [7]
    assert service.due_count(settings) == 0
    service.dismiss_review(settings, 7)
    assert service.review_items(settings) == []
    service.dismiss_offer(settings, 99)  # 기록 없음 — 예외 없음


def test_detect_engines_wrapper(settings, monkeypatch):
    monkeypatch.setattr(service.ai_engine, "detect", lambda: [EngineInfo("codex", "p", "1.0")])
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    st = service.detect_engines(settings)
    assert st.engines[0].version == "1.0" and "OPENAI_API_KEY" in st.api_keys


def test_logout_all_removes_coach_dir(settings, config_dir):
    coach.mark_solution_viewed(settings, 7, 3)
    assert (config_dir / "coach").is_dir()
    removed = service.logout(config_dir, all_=False)
    assert "AI 코치 기록" not in removed and (config_dir / "coach").is_dir()  # 세션만 삭제는 유지
    removed = service.logout(config_dir, all_=True)
    assert "AI 코치 기록" in removed and not (config_dir / "coach").exists()
    assert service.clear_coach(config_dir) == 0


def test_merge_hints_drops_ai_title():
    merged = service._merge_hints([{"level": 1, "markdown": "# 힌트 1단계: 방향 잡기\n\n## 핵심\n본문"}, {"level": 2, "markdown": "## 위치\n본문2"}])
    assert merged.count("힌트 1단계") == 1 and "방향 잡기" not in merged
    assert merged.startswith("### 힌트 1단계\n\n## 핵심") and "### 힌트 2단계\n\n## 위치" in merged


def test_prompt_code_excludes_lines_removed_on_submit(monkeypatch, tmp_path):
    from swea_fetcher import submit

    src = '# 1. t\nimport sys\nsys.stdin = open("input.txt", "r")\n\n\n\nT = int(input())\nx = sys.stdin.readline\n'
    out = submit.strip_io_lines(src)
    assert "import sys" not in out and "open(" not in out
    assert "sys.stdin.readline" in out  # 제출이 거부되는 사용은 남겨 AI 가 지적하게 한다


# --- M18: 둘 다 모드 (ask_coach_multi) ------------------------------------------------------

CODEX = EngineInfo("codex", "C:/c/codex.cmd")
CLAUDE = EngineInfo("claude", "C:/c/claude.exe")


@pytest.fixture
def dual(monkeypatch, settings):
    """both 설정 + 엔진별 가짜 run. st["reply"][key] = 문자열 | 예외 | callable(engine, prompt, kw). st["calls"] = [(key, prompt)]."""
    import threading

    st = {"calls": [], "reply": {"codex": "GPT 응답", "claude": "Claude 응답"}, "found": [CODEX, CLAUDE], "lock": threading.Lock()}

    def resolve_all(pref="auto"):
        missing = [k for k in ("codex", "claude") if k not in [e.name for e in st["found"]]]
        if not st["found"]:
            raise AiEngineMissing("없음")
        return ai_engine.EngineSelection(list(st["found"]), missing)

    def run(engine, prompt, **kw):
        with st["lock"]:
            st["calls"].append((engine.name, prompt))
        if kw.get("on_start"):
            kw["on_start"](object())
        reply = st["reply"][engine.name]
        if callable(reply):
            reply = reply(engine, prompt, kw)
        if isinstance(reply, Exception):
            raise reply
        return AiResult(reply, [engine.name], 1.0 if engine.name == "codex" else 2.0)

    monkeypatch.setattr(service.ai_engine, "resolve_all", resolve_all)
    monkeypatch.setattr(service.ai_engine, "run", run)
    st["called"] = lambda: sorted(k for k, _ in st["calls"])
    return st


def test_multi_runs_both_and_reports_in_completion_order(settings, problem, dual, cached_statement, no_fetch):
    import threading

    codex_may_finish = threading.Event()
    seen_threads = []

    def slow_codex(engine, prompt, kw):
        assert codex_may_finish.wait(5)
        return "GPT 늦은 답"

    def fast_claude(engine, prompt, kw):
        codex_may_finish.set()  # codex 가 이미 시작되어 있어야 (동시 기동) claude 도 여기 도달한다
        return "Claude 빠른 답"

    dual["reply"] = {"codex": slow_codex, "claude": fast_claude}
    order = []
    main = threading.current_thread()
    res = service.ask_coach_multi(
        settings, "review", "sim", NUM,
        on_engine_done=lambda o: (order.append(o.engine), seen_threads.append(threading.current_thread())),
    )
    assert order == ["claude", "codex"] and all(t is main for t in seen_threads)
    assert [o.engine for o in res.outcomes] == ["codex", "claude"]  # 결과는 codex, claude 순
    assert [o.answer.engine for o in res.outcomes] == ["GPT (Codex)", "Claude (Claude Code)"]
    assert len(res.succeeded) == 2 and not res.all_failed and not res.cancelled


def test_multi_shares_material_and_prompts_are_clean(settings, problem, dual, monkeypatch):
    fetches = []
    monkeypatch.setattr(service, "_gather_statement", lambda *a, **k: (fetches.append(1) or "지문", "A+B", []))
    service.ask_coach_multi(settings, "review", "sim", NUM)
    assert len(fetches) == 1 and dual["called"]() == ["claude", "codex"]
    for _key, prompt in dual["calls"]:
        for secret in (settings.user_id, settings.password, str(settings.root), str(settings.config_dir)):
            assert secret not in prompt
    service.ask_coach_multi(settings, "review", "sim", NUM)  # 둘 다 캐시 적중 -> 수집도 호출도 없음
    assert len(fetches) == 1 and len(dual["calls"]) == 2


def test_multi_partial_failure_keeps_other_answer(settings, problem, dual, cached_statement, no_fetch):
    dual["reply"]["claude"] = AiTimeout("Claude 응답이 300초를 넘어 중단했습니다", argv=["claude", "-p"])
    res = service.ask_coach_multi(settings, "review", "sim", NUM)
    codex, claude = res.outcomes
    assert codex.answer.markdown == "GPT 응답" and codex.failure is None
    assert claude.answer is None and claude.failure.code == "timeout" and claude.failure.argv == ["claude", "-p"]
    assert not res.all_failed and [o.engine for o in res.succeeded] == ["codex"]
    dual["reply"]["codex"] = RuntimeError("boom")  # 예상 밖 예외도 다른 엔진을 죽이지 않고 failed 로
    dual["reply"]["claude"] = AiRunFailed("실패 (코드 1)", stderr="tail")
    res = service.ask_coach_multi(settings, "solution", "sim", NUM)
    assert res.all_failed and res.outcomes[0].failure.title.startswith("내부 오류") and res.outcomes[1].failure.stderr == "tail"


def test_multi_missing_engine_slot(settings, problem, dual, cached_statement, no_fetch):
    dual["found"] = [CLAUDE]
    seen = []
    res = service.ask_coach_multi(settings, "review", "sim", NUM, on_engine_done=seen.append)
    assert dual["called"]() == ["claude"]
    assert res.outcomes[0].failure.code == "missing" and "Codex CLI" in res.outcomes[0].failure.title
    assert res.outcomes[1].answer is not None and seen[0].engine == "codex"  # 미설치 슬롯은 시작 직후
    dual["found"] = []
    with pytest.raises(AiEngineMissing):
        service.ask_coach_multi(settings, "review", "sim", NUM)


def test_multi_engines_subset(settings, problem, dual, cached_statement, no_fetch):
    res = service.ask_coach_multi(settings, "review", "sim", NUM, engines=["claude"])
    assert dual["called"]() == ["claude"] and [o.engine for o in res.outcomes] == ["claude"]


def test_multi_per_engine_cache(settings, problem, dual, cached_statement, no_fetch):
    service.ask_coach_multi(settings, "review", "sim", NUM, engines=["codex"])
    dual["calls"].clear()
    res = service.ask_coach_multi(settings, "review", "sim", NUM)
    assert dual["called"]() == ["claude"]  # codex 는 캐시, claude 만 호출
    assert res.outcomes[0].answer.from_cache and not res.outcomes[1].answer.from_cache
    service.ask_coach_multi(settings, "review", "sim", NUM, engines=["claude"], force_new=True)
    assert dual["called"]() == ["claude", "claude"]


def _seed_hints(settings, **counts):
    cache = coach.load_answers(settings, NUM, CODE)
    for key, n in counts.items():
        cache.slot(key).hints = [{"level": i, "markdown": f"{key}힌트{i}", "at": "t"} for i in range(1, n + 1)]
    coach.save_answers(settings, cache)


def test_multi_hint_common_level(settings, problem, dual, cached_statement, no_fetch):
    _seed_hints(settings, codex=1)
    res = service.ask_coach_multi(settings, "hint", "sim", NUM)
    assert dual["called"]() == ["claude"]  # (A=1, B=0) -> L=1: A 는 캐시
    a, b = (o.answer for o in res.outcomes)
    assert a.from_cache and a.level == 1 and b.level == 1 and not b.from_cache
    assert res.hint_done == 1
    dual["calls"].clear()
    res = service.ask_coach_multi(settings, "hint", "sim", NUM)  # (1,1) -> L=2, 둘 다 호출
    assert dual["called"]() == ["claude", "codex"] and res.hint_done == 2
    assert all(o.answer.level == 2 for o in res.outcomes)
    # 엔진별 previous_hints 는 자기 힌트만
    by_key = {k: p for k, p in dual["calls"]}
    assert "codex힌트1" in by_key["codex"] and "claude힌트1" not in by_key["codex"]


def test_multi_hint_ahead_engine_shows_prefix_only(settings, problem, dual, cached_statement, no_fetch):
    _seed_hints(settings, codex=2, claude=1)
    res = service.ask_coach_multi(settings, "hint", "sim", NUM)
    assert dual["called"]() == ["claude"]  # L=2: codex 는 hints[:2] 캐시
    assert res.outcomes[0].answer.from_cache and res.outcomes[0].answer.level == 2
    _seed_hints(settings, codex=3, claude=3)
    dual["calls"].clear()
    res = service.ask_coach_multi(settings, "hint", "sim", NUM)
    assert dual["calls"] == [] and all(o.answer.level == 3 and o.answer.from_cache for o in res.outcomes)


def test_multi_hint_failed_engine_catches_up_next_click(settings, problem, dual, cached_statement, no_fetch):
    dual["reply"]["claude"] = AiRunFailed("실패")
    res = service.ask_coach_multi(settings, "hint", "sim", NUM)
    assert res.hint_done == 0 and res.outcomes[0].answer.level == 1
    dual["reply"]["claude"] = "Claude 응답"
    dual["calls"].clear()
    res = service.ask_coach_multi(settings, "hint", "sim", NUM)
    assert dual["called"]() == ["claude"] and res.hint_done == 1  # 뒤처진 쪽만 호출 (L=1)


def test_multi_hint_force_new_pops_target_engine_last_only(settings, problem, dual, cached_statement, no_fetch):
    _seed_hints(settings, codex=2, claude=2)
    res = service.ask_coach_multi(settings, "hint", "sim", NUM, force_new=True, engines=["claude"])
    assert dual["called"]() == ["claude"] and res.outcomes[0].answer.level == 2
    cache = coach.load_answers(settings, NUM, CODE)
    assert [h["markdown"] for h in cache.slot("codex").hints] == ["codex힌트1", "codex힌트2"]
    assert len(cache.slot("claude").hints) == 2 and cache.slot("claude").hints[0]["markdown"] == "claude힌트1"


def test_multi_solution_marks_viewed_once(settings, problem, dual, cached_statement, no_fetch, monkeypatch):
    calls = []
    real = coach.mark_solution_viewed
    monkeypatch.setattr(coach, "mark_solution_viewed", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    before = (problem / f"{NUM}.py").read_bytes()
    for _ in range(3):
        coach.record_submit(settings, NUM, "sim", "A+B", SubmitResult(False, "오답"))
    dual["reply"] = {"codex": "## 정답 코드\n```python\nprint(1)\n```", "claude": "## 정답 코드\n```python\nprint(2)\n```"}
    res = service.ask_coach_multi(settings, "solution", "sim", NUM)
    assert len(calls) == 1 and res.review_due is not None
    assert [o.answer.code for o in res.outcomes] == ["print(1)", "print(2)"]
    assert all(o.answer.review_due == res.review_due for o in res.outcomes)
    assert (problem / f"{NUM}.py").read_bytes() == before
    # 한쪽만 성공해도 예약된다
    calls.clear()
    coach.dismiss_review(settings, NUM)
    dual["reply"]["claude"] = AiRunFailed("실패")
    res = service.ask_coach_multi(settings, "solution", "sim", NUM, force_new=True)
    assert len(calls) == 1 and res.review_due is not None


def test_multi_concurrent_saves_keep_both_slots(settings, problem, dual, cached_statement, no_fetch):
    import threading

    barrier = threading.Barrier(2, timeout=5)

    def meet(engine, prompt, kw):
        barrier.wait()  # 두 엔진이 거의 동시에 끝나 저장 경합을 만든다
        return f"{engine.name} 답"

    dual["reply"] = {"codex": meet, "claude": meet}
    service.ask_coach_multi(settings, "review", "sim", NUM)
    cache = coach.load_answers(settings, NUM, CODE)
    assert cache.slot("codex").review["markdown"] == "codex 답" and cache.slot("claude").review["markdown"] == "claude 답"


def test_multi_cancel(settings, problem, dual, cached_statement, no_fetch):
    res = service.ask_coach_multi(settings, "review", "sim", NUM, is_cancelled=lambda: True)
    assert res.cancelled and dual["calls"] == []
    assert all(o.cancelled for o in res.outcomes)
    # 실행 중 취소: run 이 cancelled 를 돌려주면 캐시하지 않고 다른 쪽 결과는 유지
    state = {"cancel": False}

    def codex(engine, prompt, kw):
        state["cancel"] = True
        return "GPT 답"

    dual["reply"]["codex"] = codex
    dual["reply"]["claude"] = lambda e, p, kw: (_ for _ in ()).throw(AiRunFailed("x"))
    res = service.ask_coach_multi(settings, "review", "sim", NUM, is_cancelled=lambda: state["cancel"])
    assert res.cancelled and coach.load_answers(settings, NUM, CODE).slot("codex").review is None


def test_multi_on_start_gets_engine_key(settings, problem, dual, cached_statement, no_fetch):
    keys = []
    service.ask_coach_multi(settings, "review", "sim", NUM, on_start=lambda key, proc: keys.append(key))
    assert sorted(keys) == ["claude", "codex"]


def test_multi_ping_parallel_partial(settings, dual):
    dual["reply"]["claude"] = AiRunFailed("실패 (코드 2)", hint="h", argv=["claude", "-p", "--bogus"])
    res = service.ask_coach_multi(settings, "ping")
    assert res.outcomes[0].answer.markdown == "GPT 응답" and res.outcomes[0].answer.kind == "ping"
    f = res.outcomes[1].failure
    assert f.code == "failed" and "claude -p --bogus" in f.hint
    assert dual["called"]() == ["claude", "codex"]


def test_ask_coach_wrapper_with_both_uses_first_installed(settings, problem, dual, cached_statement, no_fetch):
    a = service.ask_coach(settings, "review", "sim", NUM)
    assert a.engine_key == "codex" and dual["called"]() == ["codex"]
    dual["found"] = [CLAUDE]
    a = service.ask_coach(settings, "review", "sim", NUM)
    assert a.engine_key == "claude"


def test_hint_level_is_min_of_target_engines(settings, problem, dual):
    _seed_hints(settings, codex=2, claude=1)
    assert service.hint_level(settings, "sim", NUM) == 1
    dual["found"] = [CODEX]
    assert service.hint_level(settings, "sim", NUM) == 2  # 미설치 엔진은 제외
    dual["found"] = []
    assert service.hint_level(settings, "sim", NUM) == 0
