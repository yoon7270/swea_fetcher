"""service: AI 코치 통합 (제출 훅·ask_coach·logout). 엔진(run)은 대체하고 네트워크·실제 CLI 는 쓰지 않는다."""

from __future__ import annotations

import pytest

from swea_fetcher import ai_engine, ai_prompts, coach, content_cache, service
from swea_fetcher.ai_engine import AiResult, EngineInfo
from swea_fetcher.errors import AiEngineMissing, AiRunFailed, NetworkError, SubmitError
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
    assert a.markdown.startswith("## 총평") and a.engine == "Codex" and not a.from_cache and a.notes == []
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
    assert coach.load_answers(settings, NUM, CODE).solution is None


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
