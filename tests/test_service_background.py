"""service.classify_background: 앱이 한가할 때 한 묶음(5문제)씩 분류하는 배경 분류 (M24.2) — 게이트 · 순서 · 상한 · 한도/실패/네트워크 멈춤 · 잠금 · 모델.

네트워크(지문 페이지)와 AI(ai_engine.run)는 항상 스텁이다 (tests.test_service_types 의 env 픽스처를 쓴다).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta

import pytest

from swea_fetcher import ai_engine, ai_models, problem_types, recommend, service
from swea_fetcher.errors import AiRunFailed
from tests.test_service_recommend import seed_catalog, seed_types
from tests.test_service_types import CLAUDE, CODEX, NOW, cached, entries_of, env, fixed_now, prompted_nums, solve  # noqa: F401 (픽스처)


def bg(settings, **kw):
    kw.setdefault("consent_ok", lambda _k: True)
    kw.setdefault("now", NOW)
    kw.setdefault("sleep", lambda _s: None)
    return service.classify_background(settings, **kw)


def many(settings):
    """D1~D5 각 20문제 (번호 = 레벨*1000 + i) + D3 3문제를 푼 상태 (내 수준 D3)."""
    items = seed_catalog(settings, levels=(1, 2, 3, 4, 5), per=20)
    solve(settings, (3000, 3001, 3002))
    return items


# --- 게이트 ---------------------------------------------------------------------------------------------


def test_off_when_background_toggle_or_ai_analysis_is_off(settings, env):
    many(settings)
    for off in ({"type_bg": False}, {"recommend_ai": False}, {"recommend": False}, {"growth": False}):
        assert bg(dataclasses.replace(settings, **off)).status == "off"
    assert env["calls"] == [] and env["fetched"] == []


def test_no_catalog_or_nothing_left_never_asks_for_consent_or_engine(settings, env):
    assert bg(settings).status == "nothing"  # 카탈로그가 없다
    items = seed_catalog(settings)
    seed_types(settings, items)
    asked = []
    res = bg(settings, consent_ok=lambda k: asked.append(k) or False)
    assert res.status == "nothing" and asked == [] and env["calls"] == [] and res.progress == (100, 100)


def test_needs_consent_and_no_engine_make_no_calls(settings, env):
    many(settings)
    assert bg(settings, consent_ok=lambda _k: False).status == "needs_consent"
    env["found"] = []
    assert bg(settings).status == "no_engine"
    assert env["calls"] == [] and env["fetched"] == [] and cached(settings).entries == {}


def test_cancelled_before_the_call(settings, env):
    many(settings)
    res = bg(settings, is_cancelled=lambda: True)
    assert res.status == "cancelled" and env["calls"] == [] and env["fetched"] == []


# --- 한 번에 한 묶음 · 순서 ------------------------------------------------------------------------------


def test_one_run_classifies_exactly_one_batch_of_five(settings, env):
    many(settings)
    res = bg(settings)
    assert len(env["calls"]) == 1 and len(entries_of(env["calls"][0][1])) == recommend.CLASSIFY_BATCH == 5
    assert res.status == "ok" and res.done == 5 and res.changed and res.engine == "codex" and len(res.attempted) == 5
    assert res.progress == (5, 100) and res.capped == "" and len(cached(settings).entries) == 5
    assert all(e.eng == "codex" and e.src == "ai" and e.why for e in cached(settings).entries.values())


def test_order_is_solved_then_todays_set_then_my_level_then_nearby_levels(settings, env):
    items = many(settings)
    service.recommend_today(settings, now=NOW)  # 오늘 세트를 만들어 둔다
    todays = [r["n"] for r in recommend.load_day(settings).items if r["n"] not in (3000, 3001, 3002)]
    assert todays
    for i in range(20):
        if bg(settings, now=NOW + timedelta(hours=i // 10)).status != "ok":
            break
    order = prompted_nums(env)
    assert set(order[:3]) == {3000, 3001, 3002}  # ① 푼 문제 (최근 날짜부터)
    assert order[3 : 3 + len(todays)] == todays  # ② 오늘 추천 세트
    rest = [n for n in order[3 + len(todays) :]]
    levels = [items[n].lv for n in rest]
    assert levels[0] == 3  # ③ 내 수준
    rank = {3: 0, 4: 1, 2: 2, 5: 3, 1: 4}  # 내 수준 → 한 단계 위 → 한 단계 아래 → …
    first_levels = []
    for lv in levels:
        if not first_levels or first_levels[-1] != lv:
            first_levels.append(lv)
    assert first_levels[:5] == [3, 4, 2, 5, 1] and [rank[x] for x in first_levels[:5]] == sorted(rank[x] for x in first_levels[:5])
    assert len(set(order)) == len(order)  # 같은 문제를 두 번 보내지 않는다


def test_classified_and_recently_undecided_problems_are_skipped_but_old_undecided_are_retried(settings, env):
    many(settings)
    seed_types(settings, (3000, 3001))
    tc = cached(settings)
    tc.entries[3002] = problem_types.TypeEntry((), "ai", "codex", NOW.isoformat(timespec="seconds"))  # 방금 정하지 못함 → 14일 동안 건너뜀
    tc.entries[2000] = problem_types.TypeEntry((), "ai", "codex", (NOW - timedelta(days=15)).isoformat(timespec="seconds"))  # 오래된 실패 → 다시
    problem_types.save(settings, tc)
    bg(settings)
    sent = prompted_nums(env)
    assert not {3000, 3001, 3002} & set(sent)
    for _ in range(25):
        if bg(settings).status != "ok":
            break
    assert 2000 in prompted_nums(env) and cached(settings).entries[2000].t == ("brute",)


def test_whole_catalog_is_covered_over_many_runs(settings, env):
    many(settings)
    runs = 0
    while bg(settings, now=NOW + timedelta(hours=runs // 10)).status == "ok":  # 시간당 상한(60)을 피해 시간을 넘긴다
        runs += 1
        assert runs < 40
    assert runs == 20 and cached(settings).entries.keys() == set(service.catalog.load(settings).items)  # 100문제 = 5문제 x 20회
    last = bg(settings, now=NOW + timedelta(hours=3))
    assert last.status == "nothing" and last.progress == (100, 100)


def test_exclude_skips_problems_from_a_failed_batch(settings, env):
    many(settings)
    env["replies"]["codex"] = AiRunFailed("x")
    res = bg(settings)
    assert res.status == "failed" and len(res.attempted) == 5 and cached(settings).entries == {} and cached(settings).fail_day == ""
    env["replies"]["codex"] = lambda p: json.dumps({"v": 2, "types": [{"n": e["n"], "t": ["dp"], "why": "점화식"} for e in entries_of(p)]})
    again = bg(settings, exclude=res.attempted)
    assert again.status == "ok" and not set(res.attempted) & set(again.attempted)


# --- 상한 (시간당 · 하루 · 방문 분류와 공유) --------------------------------------------------------------


def test_hourly_cap_limits_the_batch_then_blocks_until_next_hour(settings, env, monkeypatch):
    monkeypatch.setattr(recommend, "CLASSIFY_HOURLY_CAP", 7)
    many(settings)
    assert bg(settings).done == 5
    second = bg(settings)
    assert second.done == 2 and second.capped == "hour" and len(entries_of(env["calls"][1][1])) == 2  # 남은 만큼만
    n = len(env["calls"])
    blocked = bg(settings)
    assert blocked.status == "capped" and blocked.capped == "hour" and len(env["calls"]) == n and blocked.progress == (7, 100)
    assert bg(settings, now=NOW + timedelta(hours=1)).status == "ok"  # 다음 시간에 이어서


def test_daily_cap_blocks_for_the_rest_of_the_day(settings, env, monkeypatch):
    monkeypatch.setattr(recommend, "CLASSIFY_DAILY_CAP", 8)
    many(settings)
    bg(settings)
    last = bg(settings, now=NOW + timedelta(hours=1))
    assert last.done == 3 and last.capped == "day"
    n = len(env["calls"])
    blocked = bg(settings, now=NOW + timedelta(hours=3))
    assert blocked.status == "capped" and blocked.capped == "day" and len(env["calls"]) == n
    assert bg(settings, now=NOW + timedelta(days=1)).status == "ok"


def test_background_and_visit_share_the_same_counters_and_cache(settings, env, monkeypatch):
    monkeypatch.setattr(recommend, "CLASSIFY_HOURLY_CAP", 8)
    many(settings)
    visit = service.classify_types(settings, consent_ok=lambda _k: True, now=NOW, sleep=lambda _s: None)
    assert visit.capped == "hour" and cached(settings).used_in_hour(NOW) == 8  # 방문 분류가 시간당 상한까지 썼다
    n = len(env["calls"])
    assert bg(settings).status == "capped" and len(env["calls"]) == n
    done_before = len(cached(settings).entries)
    again = bg(settings, now=NOW + timedelta(hours=1))
    assert again.status == "ok" and len(cached(settings).entries) == done_before + 5  # 같은 캐시에 이어서 쌓는다


# --- 멈춤 규칙 -------------------------------------------------------------------------------------------


def test_usage_limit_error_stops_for_the_day_and_persists(settings, env):
    many(settings)
    env["replies"]["codex"] = AiRunFailed("GPT (Codex) 실행 실패 (코드 1)", stderr="You've hit your usage limit. Try again later")
    res = bg(settings)
    assert res.status == "limit" and cached(settings).limit_day == "2026-10-06"
    n = len(env["calls"])
    again = bg(settings)  # 앱을 다시 켠 것처럼 새 호출 — 파일에 남은 표시를 본다
    assert again.status == "limit" and again.capped == "day" and len(env["calls"]) == n
    env["replies"]["codex"] = lambda p: json.dumps({"v": 2, "types": [{"n": e["n"], "t": ["dp"]} for e in entries_of(p)]})
    assert bg(settings, now=NOW + timedelta(days=1)).status == "ok"


@pytest.mark.parametrize("message", ["rate limit exceeded", "HTTP 429", "quota exhausted"])
def test_limit_heuristics(settings, env, message):
    many(settings)
    env["replies"]["codex"] = AiRunFailed("실행 실패", stderr=message)
    assert bg(settings).status == "limit"


def test_ordinary_failure_is_failed_not_limit_and_does_not_mark_the_day(settings, env):
    many(settings)
    env["replies"]["codex"] = "죄송합니다. 분류할 수 없습니다"  # JSON 이 아님
    res = bg(settings)
    assert res.status == "failed" and not res.changed and cached(settings).entries == {} and cached(settings).limit_day == "" and cached(settings).fail_day == ""
    env["replies"]["codex"] = AiRunFailed("exit 1", stderr="boom")
    assert bg(settings).status == "failed"


def test_a_failed_visit_today_pauses_background_classification(settings, env):
    many(settings)
    env["replies"]["codex"] = "not json"
    service.classify_types(settings, consent_ok=lambda _k: True, now=NOW, sleep=lambda _s: None)
    assert cached(settings).fail_day == "2026-10-06"
    n = len(env["calls"])
    assert bg(settings).status == "paused" and len(env["calls"]) == n
    env["replies"]["codex"] = lambda p: json.dumps({"v": 2, "types": [{"n": e["n"], "t": ["dp"]} for e in entries_of(p)]})
    assert bg(settings, now=NOW + timedelta(days=1)).status == "ok"


def test_network_or_login_failure_stops_the_run_with_one_login_attempt_and_no_retry(settings, env, monkeypatch):
    many(settings)
    env["session_fail"] = True
    attempts = []
    real = service.auth.get_session

    def counting(s, explicit=False):
        attempts.append(explicit)
        return real(s, explicit=explicit)

    monkeypatch.setattr(service.auth, "get_session", counting)
    res = bg(settings)
    assert res.status == "network" and attempts == [False] and env["calls"] == [] and cached(settings).entries == {}  # 비명시 로그인 1회, 재시도·AI 호출 없음


def test_missing_statement_is_remembered_and_does_not_block_the_catalog(settings, env):
    items = many(settings)
    env["fetch_missing"] = {items[3000].id}  # 모든 문제의 id 가 같아서 전부 "없는 지문" 이 된다
    res = bg(settings)
    assert res.status == "ok" and res.done == 0 and res.changed and env["calls"] == []
    assert all(e.t == () for e in cached(settings).entries.values()) and len(cached(settings).entries) == 5
    before = set(cached(settings).entries)
    nxt = bg(settings)
    assert nxt.attempted and not set(nxt.attempted) & before  # 다음 묶음은 다른 문제부터 (같은 문제가 계속 막지 않는다)


def test_fetches_are_paced_one_second_apart(settings, env):
    many(settings)
    sleeps: list[float] = []
    bg(settings, sleep=sleeps.append)
    assert sleeps and set(sleeps) == {service.CLASSIFY_FETCH_PACE} and service.CLASSIFY_FETCH_PACE >= 1.0
    assert len(sleeps) == len(env["fetched"]) - 1


# --- 잠금 · 모델 ----------------------------------------------------------------------------------------


def test_busy_when_another_classification_is_running(settings, env):
    many(settings)
    assert service._CLASSIFY_LOCK.acquire(blocking=False)
    try:
        res = bg(settings)
    finally:
        service._CLASSIFY_LOCK.release()
    assert res.status == "busy" and env["calls"] == []
    assert bg(settings).status == "ok"  # 잠금은 항상 풀린다


def test_lock_is_released_after_failures_and_exceptions(settings, env, monkeypatch):
    many(settings)
    env["replies"]["codex"] = AiRunFailed("x")
    bg(settings)
    monkeypatch.setattr(service.problem_types, "save", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk")))
    assert bg(settings).status in ("failed", "ok")  # 내부 오류도 예외로 새지 않는다
    monkeypatch.undo()
    assert service._CLASSIFY_LOCK.acquire(blocking=False)
    service._CLASSIFY_LOCK.release()


def test_uses_the_light_codex_model_from_the_models_cache_with_low_effort(settings, env, monkeypatch):
    home = ai_models.codex_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "gpt-6-sol", "display_name": "S", "visibility": "list", "priority": 3, "supported_reasoning_levels": [{"effort": "low"}]},
        {"slug": "gpt-6-luna", "display_name": "L", "visibility": "list", "priority": 4, "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}]},
    ]}), encoding="utf-8")
    many(settings)
    bg(settings)
    name, _prompt, kw = env["calls"][0]
    assert name == "codex" and kw["model"] == "gpt-6-luna" and kw["effort"] == "low"
    env["calls"].clear()
    bg(dataclasses.replace(settings, type_model="codex:gpt-6-sol"), now=NOW + timedelta(hours=1))
    assert env["calls"][0][2]["model"] == "gpt-6-sol"  # 설정에서 고른 모델


def test_claude_only_uses_haiku_and_the_coach_engine_setting_is_ignored(settings, env):
    many(settings)
    env["found"] = [CLAUDE]
    bg(dataclasses.replace(settings, ai_engine="codex"))  # 코치 엔진이 codex 로 고정이어도 분류 엔진은 독립
    name, _p, kw = env["calls"][0]
    assert name == "claude" and kw["model"] == "haiku"
    env["found"] = [CODEX, CLAUDE]
    env["calls"].clear()
    res = bg(settings, consent_ok=lambda k: k == "claude", now=NOW + timedelta(hours=1))  # 동의한 엔진만 쓴다
    assert res.engine == "claude" and {c[0] for c in env["calls"]} == {"claude"}


def test_prompt_is_the_solution_design_prompt_with_public_data_only(settings, env):
    many(settings)
    bg(settings)
    prompt = env["calls"][0][1]
    assert "`plan`" in prompt and "`why`" in prompt and '"v":2' in prompt
    assert all(set(e) == {"n", "title", "text"} for e in entries_of(prompt))


# --- 추천 결과에 반영 ------------------------------------------------------------------------------------


def test_recommend_result_carries_progress_cap_and_the_why_of_each_item(settings, env, monkeypatch):
    many(settings)
    before = service.recommend_today(settings, now=NOW)
    assert before.type_progress == (0, 100) and before.type_capped == "" and all(i.why == "" for i in before.items)
    for i in range(20):
        if bg(settings, now=NOW + timedelta(hours=i // 10)).status != "ok":
            break
    after = service.recommend_today(settings, now=NOW + timedelta(hours=3))
    assert after.type_progress == (100, 100)
    typed = [i for i in after.items if i.types]
    assert typed and all(i.why == "모든 경우를 직접 열거" for i in typed)  # 칩 툴팁 "왜 이 유형?" 의 근거
    monkeypatch.setattr(recommend, "CLASSIFY_HOURLY_CAP", 1)
    tc = cached(settings)
    tc.add_used_at(NOW + timedelta(hours=5), 1)
    problem_types.save(settings, tc)
    assert service.recommend_today(settings, now=NOW + timedelta(hours=5)).type_capped == "hour"


def test_a_reclassified_problem_does_not_keep_a_stale_why(settings, env):
    items = many(settings)
    seed_types(settings, items)  # 모든 후보가 이미 분류돼 있다 → 오늘 세트에 유형이 저장된다
    service.recommend_today(settings, now=NOW)
    target = next(r["n"] for r in recommend.load_day(settings).items if r["k"] != "retry" and r.get("ty"))
    tc = cached(settings)
    tc.entries[target] = problem_types.TypeEntry(("brute",), "ai", "codex", "x", "모든 경우를 열거")
    problem_types.save(settings, tc)
    item = next(i for i in service.recommend_today(settings, now=NOW).items if i.num == target)
    assert item.types == ("brute",) and item.why == "모든 경우를 열거"
    tc.entries[target] = problem_types.TypeEntry(("graph",), "ai", "codex", "x", "간선 모델링")  # 나중에 다시 분류돼 유형이 달라졌다
    problem_types.save(settings, tc)
    assert next(i for i in service.recommend_today(settings, now=NOW).items if i.num == target).why == ""  # 세트에 저장된 유형(brute)과 다르면 옛 이유는 쓰지 않는다
