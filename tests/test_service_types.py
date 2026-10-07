"""service: 풀이 유형 분류 (M24.1) — 대상 선정 · 동의/엔진 · 검증 · 일일 상한 · 실패 · 캐시 · 추천 세트 반영 · 삭제 범위 · 프라이버시.

네트워크(지문 페이지)와 AI(ai_engine.run)는 항상 스텁이다. 내 코드·계정·폴더 이름이 프롬프트에 없는지도 확인한다.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta

import pytest

from swea_fetcher import ai_engine, catalog, content_cache, growth, problem_types, recommend, service, solved
from swea_fetcher.ai_engine import AiResult, EngineInfo
from swea_fetcher.errors import AiRunFailed, NetworkError, ProblemNotFound
from swea_fetcher.models import ProblemContent
from tests.conftest import DUMMY_ID, DUMMY_PW
from tests.test_service_recommend import seed_catalog, seed_types

NOW = datetime(2026, 10, 6, 12, 0, 0)
CODEX = EngineInfo("codex", "C:/c/codex.cmd")
CLAUDE = EngineInfo("claude", "C:/c/claude.exe")
SECRET_TOPIC = "비밀주제ZZZ"


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(growth, "now", lambda: NOW)


def entries_of(prompt: str) -> list[dict]:
    body = re.search(r"<classify_input>\n(.*?)\n</classify_input>", prompt, re.S).group(1)
    return json.loads(body)


@pytest.fixture
def env(settings, monkeypatch):
    """엔진·지문 fake. replies[key] = 함수(prompt) → 텍스트 또는 예외. 기본은 모든 문제를 완전탐색으로."""
    st = {"calls": [], "found": [CODEX], "fetched": [], "lock": threading.Lock(), "fetch_fail": set(), "fetch_missing": set(), "session_fail": False}

    def brute_all(prompt):
        return json.dumps({"v": 2, "types": [{"n": e["n"], "plan": "모든 경우를 열거한다", "t": ["brute"], "why": "모든 경우를 직접 열거"} for e in entries_of(prompt)]})

    st["replies"] = {"codex": brute_all, "claude": brute_all}

    def resolve_all(pref="auto"):
        return ai_engine.EngineSelection(list(st["found"]), [])

    def run(engine, prompt, **kw):
        with st["lock"]:
            st["calls"].append((engine.name, prompt, kw))
        if kw.get("on_start"):
            kw["on_start"](object())
        reply = st["replies"][engine.name]
        reply = reply(prompt) if callable(reply) else reply
        if isinstance(reply, Exception):
            raise reply
        return AiResult(reply, [engine.name], 1.0)

    def get_session(s, explicit=False):
        if st["session_fail"]:
            raise NetworkError("연결 실패")
        return object()

    def fetch_page(session, s, cid):
        st["fetched"].append(cid)
        if cid in st["fetch_fail"]:
            raise NetworkError("지문 실패")
        if cid in st["fetch_missing"]:
            raise ProblemNotFound("없는 문제")
        return f"PAGE:{cid}", "detail"

    monkeypatch.setattr(service.ai_engine, "resolve_all", resolve_all)
    monkeypatch.setattr(service.ai_engine, "run", run)
    monkeypatch.setattr(service.auth, "get_session", get_session)
    monkeypatch.setattr(service.client, "fetch_problem_page", fetch_page)
    monkeypatch.setattr(service.parser, "parse_content", lambda html: ProblemContent("", f"<p>지문 본문 {html}</p>", {}))
    return st


def classify(settings, **kw):
    kw.setdefault("consent_ok", lambda _k: True)
    kw.setdefault("now", NOW)
    kw.setdefault("sleep", lambda _s: None)
    return service.classify_types(settings, **kw)


def solve(settings, nums, topic="t", title="x", ago=1):
    for i, n in enumerate(nums):
        solved.record(settings, n, topic, title, "swea", at=NOW - timedelta(days=ago, minutes=i))


def cached(settings) -> problem_types.TypeCache:
    return problem_types.load(settings)


def prompted_nums(env) -> list[int]:
    return [e["n"] for c in env["calls"] for e in entries_of(c[1])]


# --- 게이트: 꺼짐 · 할 일 없음 · 동의 · 엔진 -------------------------------------------------------------


def test_off_when_ai_analysis_is_disabled(settings, env):
    import dataclasses

    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    for off in ({"recommend_ai": False}, {"recommend": False}, {"growth": False}):
        assert classify(dataclasses.replace(settings, **off)).status == "off"
    assert env["calls"] == [] and env["fetched"] == []


def test_nothing_to_do_never_asks_for_consent_or_engine(settings, env):
    assert classify(settings).status == "nothing"  # 카탈로그가 없다
    items = seed_catalog(settings)
    seed_types(settings, items)  # 후보는 이미 분류됨, 푼 문제 없음
    asked = []
    res = classify(settings, consent_ok=lambda k: asked.append(k) or False)
    assert res.status == "nothing" and asked == [] and env["calls"] == []


def test_needs_consent_makes_zero_calls_and_zero_fetches(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    res = classify(settings, consent_ok=lambda _k: False)
    assert res.status == "needs_consent" and env["calls"] == [] and env["fetched"] == [] and cached(settings).entries == {}


def test_no_engine(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    env["found"] = []
    assert classify(settings).status == "no_engine" and env["calls"] == []


def test_uses_exactly_one_engine_first_consented_one(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    env["found"] = [CODEX, CLAUDE]
    res = classify(settings)
    assert res.status in ("ok", "partial") and {c[0] for c in env["calls"]} == {"codex"} and res.engine == "codex"  # 둘 다 있어도 Codex 하나만
    assert {e.eng for e in cached(settings).entries.values()} == {"codex"}
    env["calls"].clear()
    problem_types.clear(settings.config_dir)
    classify(settings, consent_ok=lambda k: k == "claude")
    assert {c[0] for c in env["calls"]} == {"claude"}  # 동의한 엔진 중 첫 번째


def test_cancelled_before_any_call(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    res = classify(settings, is_cancelled=lambda: True)
    assert res.status == "cancelled" and env["calls"] == [] and env["fetched"] == []


# --- 대상 · 순서 · 입력 --------------------------------------------------------------------------------


def test_solved_problems_are_classified_first_and_saved_with_engine_and_time(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    begun, progressed = [], []
    res = classify(settings, on_begin=begun.append, on_progress=progressed.append)
    assert begun == ["codex"] and progressed and res.changed and res.done == progressed[-1]
    first = {e["n"] for e in entries_of(env["calls"][0][1])}
    assert {3000, 3001, 3002} <= first  # 푼 문제부터
    entry = cached(settings).entries[3000]
    assert entry.t == ("brute",) and entry.src == "ai" and entry.eng == "codex" and entry.at == "2026-10-06T12:00:00"
    assert entry.why == "모든 경우를 직접 열거"  # 이유 한 줄은 저장하고 plan(풀이 설계)은 어디에도 저장하지 않는다
    assert "모든 경우를 열거한다" not in problem_types.cache_path(settings).read_text(encoding="utf-8")
    kw = env["calls"][0][2]
    assert kw["timeout"] == service.AI_CLASSIFY_TIMEOUT


def test_default_budget_constants():
    assert (recommend.CLASSIFY_BATCH, recommend.CLASSIFY_HOURLY_CAP, recommend.CLASSIFY_DAILY_CAP) == (5, 60, 400)


def test_batches_have_at_most_five_problems_and_the_daily_cap_applies(settings, env, monkeypatch):
    monkeypatch.setattr(recommend, "CLASSIFY_DAILY_CAP", 12)
    seed_catalog(settings, levels=(1, 2, 3, 4, 5), per=40)
    solve(settings, range(1000, 1040))  # 푼 문제가 많다
    res = classify(settings)
    sizes = [len(entries_of(c[1])) for c in env["calls"]]
    assert sizes == [5, 5, 2] and sum(sizes) == recommend.CLASSIFY_DAILY_CAP
    assert cached(settings).used_on(NOW.date()) == 12 == len(cached(settings).entries)
    assert res.status == "partial" and res.capped == "day"
    n_calls = len(env["calls"])
    again = classify(settings)
    assert again.status == "partial" and len(env["calls"]) == n_calls  # 같은 날은 더 부르지 않는다
    tomorrow = classify(settings, now=NOW + timedelta(days=1))
    assert len(env["calls"]) > n_calls and tomorrow.changed  # 다음 날 이어서


def test_the_hourly_cap_is_shared_and_reopens_next_hour(settings, env, monkeypatch):
    monkeypatch.setattr(recommend, "CLASSIFY_HOURLY_CAP", 7)
    seed_catalog(settings, levels=(1, 2, 3, 4, 5), per=40)
    solve(settings, range(1000, 1040))
    res = classify(settings)
    assert [len(entries_of(c[1])) for c in env["calls"]] == [5, 2] and res.status == "partial" and res.capped == "hour"
    assert cached(settings).used_in_hour(NOW) == 7
    n_calls = len(env["calls"])
    assert classify(settings).status == "partial" and len(env["calls"]) == n_calls  # 같은 시간에는 더 부르지 않는다
    assert classify(settings, now=NOW + timedelta(hours=1)).changed and len(env["calls"]) > n_calls  # 다음 시간에 이어서


def test_visit_classification_uses_the_light_model_and_ignores_the_coach_engine_setting(settings, env):
    import dataclasses

    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    env["found"] = [CODEX, CLAUDE]
    assert classify(dataclasses.replace(settings, ai_engine="claude")).changed  # AI 코치를 Claude 로 고정해도 분류는 모델 설정을 따른다
    kw = env["calls"][0][2]
    assert env["calls"][0][0] == "codex" and kw["effort"] == "low" and kw["model"] == ""  # models_cache.json 이 없으면 Codex 기본 모델 (-m 없음)
    env["calls"].clear()
    problem_types.clear(settings.config_dir)
    classify(dataclasses.replace(settings, type_model="claude:haiku"))
    assert env["calls"][0][0] == "claude" and env["calls"][0][2]["model"] == "haiku"


def test_per_run_solved_limit_leaves_budget_for_candidates(settings, env):
    seed_catalog(settings, levels=(1, 2, 3, 4, 5), per=40)
    solve(settings, range(1000, 1060))
    classify(settings)
    sent = prompted_nums(env)
    assert len([n for n in sent if n in range(1000, 1060)]) == recommend.CLASSIFY_SOLVED_MAX  # 푼 문제는 한 번에 24개까지
    assert any(n not in range(1000, 1060) for n in sent)  # 나머지 예산은 후보(새 유형·일반)에


def test_title_keyword_problems_are_still_checked_by_ai(settings, env):
    """제목 단어("부분집합")만으로 유형을 정하지 않는다 — 지문의 제약(N≤100)을 봐야 하므로 AI 로 확인한다."""
    seed_catalog(settings, over={3000: {"title": "BFS 연습"}, 3001: {"title": "[S/W 문제해결] 부분집합의 합"}})
    solve(settings, (3000, 3001, 3002))
    classify(settings)
    assert {3000, 3001, 3002} <= set(prompted_nums(env))


def test_title_guess_never_qualifies_an_unsolved_candidate(settings):
    """푼 문제는 제목 추정까지 아는 유형으로 세지만, 추천 후보는 AI 분류가 없으면 유형 미확인이다."""
    seed_catalog(settings, over={3000: {"title": "[S/W 문제해결] 부분집합의 합"}, 3005: {"title": "[S/W 문제해결 최적화] 3일차 - 부분 집합의 합"}})
    solve(settings, (3000,))
    res = service.recommend_today(settings, now=NOW)
    assert res.type_counts == {"brute": 1}
    for it in res.items:
        if it.num == 3005:
            assert it.types == ()


def test_statement_comes_from_content_cache_else_catalog_id_and_nothing_is_saved(settings, env):
    items = seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    content = ProblemContent("", "<p>캐시된 지문 CACHED_BODY</p>", {})
    assert content_cache.save(settings, 3000, "t", "x", content)
    before = sorted(p.name for p in (settings.cache_dir / "statements").glob("*"))
    classify(settings)
    assert len(env["fetched"]) == len(prompted_nums(env)) - 1  # 캐시에 있는 한 문제만 받지 않았다
    by_n = {e["n"]: e for e in entries_of(env["calls"][0][1])}
    assert "CACHED_BODY" in by_n[3000]["text"] and "PAGE:" not in by_n[3000]["text"]  # 캐시된 지문은 그대로
    assert f"PAGE:{items[3001].id}" in by_n[3001]["text"]  # 없으면 카탈로그 id 로 지문 페이지만
    assert sorted(p.name for p in (settings.cache_dir / "statements").glob("*")) == before  # 지문 캐시(최근 50건)를 밀어내지 않는다
    assert not list(settings.root.rglob("*"))  # 폴더·저장 없음


def test_statement_text_is_clipped(settings, env, monkeypatch):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    monkeypatch.setattr(service.parser, "parse_content", lambda html: ProblemContent("", "<p>" + "가" * 9000 + "</p>", {}))
    classify(settings)
    assert all(len(e["text"]) < 2_600 for c in env["calls"] for e in entries_of(c[1]))


def test_network_failure_stops_the_run_without_caching_or_ai_call(settings, env):
    items = seed_catalog(settings, over={3001: {"id": "FAILFAILFAILFAIL"}})
    solve(settings, (3000, 3001, 3002))
    env["fetch_fail"] = {items[3001].id}
    res = classify(settings)
    assert res.status == "network" and env["calls"] == [] and cached(settings).entries == {}  # 연결 문제는 이번 실행을 멈춘다 (캐시에 "정하지 못함" 으로 남기지 않는다)
    assert len(env["fetched"]) <= 2  # 실패 뒤에는 더 받지 않는다


def test_missing_statement_is_remembered_as_undecided_and_the_rest_continue(settings, env):
    items = seed_catalog(settings, over={3001: {"id": "GONEGONEGONEGONE"}})
    solve(settings, (3000, 3001, 3002))
    env["fetch_missing"] = {items[3001].id}
    res = classify(settings)
    tc = cached(settings)
    assert res.status in ("ok", "partial") and tc.entries[3001].t == () and tc.fresh(3001, NOW.date())  # 없는 지문은 14일 뒤에 다시
    assert 3001 not in prompted_nums(env) and tc.entries[3000].t == ("brute",)


def test_session_failure_stops_fetching_and_makes_no_ai_call(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    env["session_fail"] = True
    res = classify(settings)
    assert env["calls"] == [] and env["fetched"] == [] and res.status == "network" and not res.changed  # 지문을 못 구하면 AI 도 안 부른다


def test_fetches_are_paced_one_second_apart(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    sleeps: list[float] = []
    classify(settings, sleep=sleeps.append)
    assert service.CLASSIFY_FETCH_PACE >= 1.0 and sleeps and set(sleeps) == {service.CLASSIFY_FETCH_PACE}
    assert len(sleeps) == len(env["fetched"]) - 1  # 첫 요청 앞에서는 기다리지 않는다


def test_rate_limit_error_stops_for_the_day(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    env["replies"]["codex"] = AiRunFailed("GPT (Codex) 실행 실패 (코드 1)", stderr="Error: 429 Too Many Requests — usage limit reached")
    res = classify(settings)
    assert res.status == "limit" and cached(settings).limit_day == "2026-10-06" and cached(settings).fail_day == ""
    assert len(env["calls"]) == 1
    assert classify(settings).status == "limit" and len(env["calls"]) == 1  # 그날은 더 부르지 않는다
    env["replies"]["codex"] = lambda p: json.dumps({"v": 2, "types": [{"n": e["n"], "t": ["dp"], "why": "점화식"} for e in entries_of(p)]})
    assert classify(settings, retry=True).changed and cached(settings).limit_day == ""  # [다시 시도] 가 통하면 한도 표시를 지운다
    assert classify(settings, now=NOW + timedelta(days=1)).status != "limit"


def test_new_type_candidates_come_after_solved_and_target_one_step_easier_level(settings, env):
    items = seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))  # D3 3문제 → 수준 D3
    seed_types(settings, (3000, 3001, 3002))  # 푼 문제는 이미 완전탐색으로 분류됨
    classify(settings)
    first = [e["n"] for e in entries_of(env["calls"][0][1])]
    assert first and all(items[n].lv == 2 for n in first)  # 완전탐색 다음 유형을 찾을 한 단계 쉬운 D2 후보부터


def test_new_type_candidate_search_stops_when_the_next_type_already_has_candidates(settings, env):
    items = seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    seed_types(settings, (3000, 3001, 3002))
    seed_types(settings, [n for n, it in items.items() if it.lv == 2][:3], types=("recursion",))  # D2 에 다음 유형(재귀·분할정복) 문제가 이미 있다
    classify(settings)
    assert not any(items[n].lv == 2 for n in prompted_nums(env))


def test_normal_candidate_classification_stops_when_enough_are_typed(settings, env):
    items = seed_catalog(settings)
    seed_types(settings, [n for n, it in items.items() if it.lv in (2, 3)])  # 후보 풀(D2, D3)이 이미 분류됨
    res = classify(settings)
    assert res.status == "nothing" and env["calls"] == []


# --- 응답 검증 · 실패 ----------------------------------------------------------------------------------


def test_invalid_rows_become_undecided_and_are_retried_after_two_weeks(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))

    def mixed(prompt):
        return json.dumps({"v": 1, "types": [
            {"n": 3000, "t": ["bfs"]}, {"n": 3001, "t": ["not-a-type"]}, {"n": 3002, "t": ["a", "b", "c"]}, {"n": 999999, "t": ["bfs"]}]})

    env["replies"]["codex"] = mixed
    classify(settings)
    tc = cached(settings)
    assert tc.entries[3000].t == ("bfs",) and tc.entries[3001].t == () and tc.entries[3002].t == ()  # 잘못된 id·3개는 "정하지 못함"
    assert 999999 not in tc.entries  # 요청하지 않은 번호는 무시
    assert tc.fresh(3001, NOW.date()) and not tc.fresh(3001, NOW.date() + timedelta(days=15))
    assert service.recommend_today(settings, now=NOW).type_counts == {"bfs": 1}  # 정하지 못한 문제는 유형으로 세지 않는다


def test_garbage_or_engine_error_fails_today_without_automatic_retry(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    env["replies"]["codex"] = "죄송합니다. 분류할 수 없습니다"
    res = classify(settings)
    assert res.status == "failed" and not res.changed and cached(settings).entries == {} and cached(settings).fail_day == "2026-10-06"
    assert len(env["calls"]) == 1
    assert classify(settings).status == "failed" and len(env["calls"]) == 1  # 같은 날 자동 재시도 없음
    env["replies"]["codex"] = AiRunFailed("x")
    assert classify(settings, retry=True).status == "failed" and len(env["calls"]) == 2  # [다시 시도] 는 한다
    env["replies"]["codex"] = lambda p: json.dumps({"v": 1, "types": [{"n": e["n"], "t": ["dp"]} for e in entries_of(p)]})
    assert classify(settings, retry=True).changed
    assert classify(settings, now=NOW + timedelta(days=1)).status != "failed"  # 다음 날은 다시 자동


def test_mid_run_failure_keeps_what_was_done(settings, env):
    seed_catalog(settings, levels=(1, 2, 3, 4, 5), per=40)
    solve(settings, range(1000, 1030))
    replies = iter([env["replies"]["codex"], AiRunFailed("두 번째 실패")])

    def flaky(prompt):
        r = next(replies)
        return r(prompt) if callable(r) else r

    env["replies"]["codex"] = flaky
    res = classify(settings)
    assert res.status == "partial" and res.changed and len(cached(settings).entries) == recommend.CLASSIFY_BATCH  # 앞 배치는 남는다


def test_cancel_during_run_is_not_a_failure(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    flag = {"c": False}

    def cancel_midway(prompt):
        flag["c"] = True
        return env["replies"]["claude"](prompt)

    env["replies"]["codex"] = cancel_midway
    res = classify(settings, is_cancelled=lambda: flag["c"])
    assert res.status == "cancelled" and cached(settings).fail_day == "" and cached(settings).entries == {}


# --- 프라이버시 -----------------------------------------------------------------------------------------


def test_prompt_has_only_public_problem_data(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002), topic=SECRET_TOPIC, title="일반 제목")
    (settings.root / SECRET_TOPIC / "3000").mkdir(parents=True)
    (settings.root / SECRET_TOPIC / "3000" / "3000.py").write_text("SECRET_CODE_ZZZ = input()\n", encoding="utf-8")
    growth.record_submit(settings, 3000, SECRET_TOPIC, "pass", wb=2, at=NOW - timedelta(days=1))
    classify(settings)
    assert env["calls"]
    for _name, prompt, _kw in env["calls"]:
        for forbidden in (DUMMY_ID, DUMMY_PW, str(settings.root), str(settings.config_dir), SECRET_TOPIC, "SECRET_CODE_ZZZ", "wrong_count", "session"):
            assert forbidden not in prompt, forbidden
        assert all(set(e) == {"n", "title", "text"} for e in entries_of(prompt))  # 번호·제목·지문 앞부분뿐


# --- 추천 세트 반영 ------------------------------------------------------------------------------------


def test_folder_names_are_not_evidence_of_a_known_type(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002), topic="BFS")  # BFS 폴더에 저장했지만 푼 문제는 완전탐색이다
    classify(settings)
    res = service.recommend_today(settings, now=NOW)
    assert res.type_counts == {"brute": 3}
    assert not any("bfs" in i.types for i in res.items if i.kind != "newtype")


def test_known_types_shape_the_set_and_bfs_never_appears_in_normal_slots(settings, env):
    items = seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    seed_types(settings, (3000, 3001, 3002))
    types = {n: (("brute",) if n % 2 == 0 else ("bfs",)) for n in items if n not in (3000, 3001, 3002)}
    for n, t in types.items():
        seed_types(settings, [n], types=t)
    res = service.recommend_today(settings, now=NOW)
    normal = [i for i in res.items if i.kind in ("fit", "stretch", "fill")]
    assert normal and all(i.types == ("brute",) for i in normal)
    assert res.level.level == 3 and res.type_counts == {"brute": 3}


def test_new_type_slot_appears_after_brute_and_is_one_step_easier(settings, env):
    items = seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    seed_types(settings, [n for n in items if n not in (3000, 3001, 3002)], types=("brute",))
    seed_types(settings, (3000, 3001, 3002))
    seed_types(settings, [n for n, it in items.items() if it.lv == 2][:5], types=("backtrack",))
    res = service.recommend_today(settings, now=NOW)
    new = [i for i in res.items if i.kind == "newtype"]
    assert len(new) == 1 and new[0].types == ("backtrack",) and new[0].level == 2 and "DFS·백트래킹 첫걸음" in new[0].reason
    assert len(res.items) == 4
    again = service.recommend_today(settings, now=NOW + timedelta(hours=3))
    assert [(i.num, i.kind, i.types) for i in again.items] == [(i.num, i.kind, i.types) for i in res.items]  # 하루 동안 안정적


def test_stored_set_keeps_its_types_but_unknown_ones_are_filled_in_later(settings, env):
    items = seed_catalog(settings)
    res = service.recommend_today(settings, now=NOW)  # 유형 캐시 없음 → 전부 미확인
    assert all(i.types == () for i in res.items)
    assert all("ty" not in r for r in recommend.load_day(settings).items)
    target = res.items[0].num
    seed_types(settings, [target], types=("dp",))
    later = service.recommend_today(settings, now=NOW)
    assert later.items[0].types == ("dp",) and [i.num for i in later.items] == [i.num for i in res.items]  # 세트는 그대로, 유형만 채운다


def test_rebuild_after_learning_types_replaces_unknown_cells_unless_user_shuffled(settings, env):
    items = seed_catalog(settings)
    first = service.recommend_today(settings, now=NOW)
    assert all(i.types == () for i in first.items)
    seed_types(settings, items)  # 분류가 끝나 모든 후보의 유형을 알게 됨
    rebuilt = service.recommend_today(settings, now=NOW, rebuild=True)
    assert all(i.types == ("brute",) for i in rebuilt.items if i.kind != "retry") and len(rebuilt.items) == 4
    assert recommend.load_day(settings).shuffle == 0
    # 이미 [다른 추천] 을 눌렀다면 보던 화면을 바꾸지 않는다
    service.recommend_today(settings, now=NOW + timedelta(days=1))
    shuf = service.recommend_today(settings, now=NOW + timedelta(days=1), shuffle=True)
    same = service.recommend_today(settings, now=NOW + timedelta(days=1), rebuild=True)
    assert [i.num for i in same.items] == [i.num for i in shuf.items] and same.shuffle == 1


def test_rebuild_is_a_no_op_when_the_set_has_no_unknown_cells(settings, env):
    items = seed_catalog(settings)
    seed_types(settings, items)
    a = service.recommend_today(settings, now=NOW)
    b = service.recommend_today(settings, now=NOW, rebuild=True)
    assert [i.num for i in a.items] == [i.num for i in b.items]


def test_has_day_set(settings, env):
    seed_catalog(settings)
    assert service.has_day_set(settings, NOW) is False
    service.recommend_today(settings, now=NOW)
    assert service.has_day_set(settings, NOW) is True and service.has_day_set(settings, NOW + timedelta(days=1)) is False


def test_end_to_end_classify_then_set_uses_the_learned_types(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    classify(settings)
    res = service.recommend_today(settings, now=NOW)
    assert res.type_counts == {"brute": 3}
    assert all(i.types == ("brute",) for i in res.items if i.kind in ("fit", "stretch", "fill"))


# --- 약점 AI 층에 유형이 들어간다 ---------------------------------------------------------------------------


def test_weak_ai_pool_and_prompt_use_known_types_and_reject_violations(settings, env):
    from tests.test_service_recommend import add_tags, pool_from

    items = seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    seed_types(settings, (3000, 3001, 3002))
    seed_types(settings, [n for n in items if n % 2 == 0 and n not in (3000, 3002)], types=("brute",))
    seed_types(settings, [n for n in items if n % 2 == 1 and n not in (3001,)], types=("bfs",))
    add_tags(settings)

    def greedy_ai(prompt):
        pool = pool_from(prompt)
        assert pool and all(p["ty"] == ["완전탐색"] for p in pool)  # 풀 전체가 풀어 본 유형 안
        payload = json.loads(re.search(r"<recommend_input>\n(.*?)\n</recommend_input>", prompt, re.S).group(1))
        assert payload["known"] == ["완전탐색"]
        bad = next(n for n, it in items.items() if it.lv == 3 and n % 2 == 1 and n not in (3001,))  # 풀 밖 BFS 문제를 슬쩍 끼워 넣는다
        return json.dumps({"v": 1, "picks": [{"n": bad}] + [{"n": p["n"], "r": "ok"} for p in pool[:7]]})

    env["replies"]["codex"] = greedy_ai
    base = service.recommend_today(settings, now=NOW)
    res = service.recommend_ai(settings, base, now=NOW, consent_ok=lambda _k: True)
    assert res.ai_status == "ok"
    assert all(i.types == ("brute",) for i in res.items if i.kind in ("fit", "stretch"))


# --- 삭제 · 위치 ------------------------------------------------------------------------------------------


def test_logout_all_removes_the_type_cache_but_plain_logout_and_growth_clear_keep_it(settings, env):
    seed_catalog(settings)
    seed_types(settings, (3000,))
    (settings.config_dir / "session.json").write_text("{}")
    service.logout(settings.config_dir)
    service.clear_growth(settings.config_dir)
    assert problem_types.cache_path(settings).exists()  # 공개 데이터라 [성장 기록 지우기] 로는 안 지운다
    (settings.config_dir / ".env").write_text(f"SWEA_ID={DUMMY_ID}\n")
    (settings.cache_dir / "statements").mkdir(parents=True)
    (settings.cache_dir / "statements" / "1.json").write_text("{}", encoding="utf-8")
    removed = service.logout(settings.config_dir, all_=True)
    assert "풀이 유형 캐시" in removed and not problem_types.cache_path(settings).exists()
    assert not settings.cache_dir.exists()  # 비어 있으면 cache/ 폴더도 정리 (카탈로그·유형 캐시를 먼저 지운 뒤)


def test_nothing_is_written_to_the_root_folder(settings, env):
    seed_catalog(settings)
    solve(settings, (3000, 3001, 3002))
    classify(settings)
    service.recommend_today(settings, now=NOW)
    assert list(settings.root.rglob("*")) == []
    assert problem_types.cache_path(settings).parent == settings.cache_dir
