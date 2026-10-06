"""recommend: 수준 모델(사다리) · 후보 선정 · 오늘의 세트 · 시드 · 세트 저장 · AI payload/파서/합산 (순수 — 네트워크·AI·Qt 없음) (M24)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pytest

from swea_fetcher import catalog, growth, recommend
from swea_fetcher.catalog import CatalogItem
from swea_fetcher.config import Settings
from swea_fetcher.recommend import AiPick, LevelEstimate, RetryCand, SolveFact
from tests.conftest import DUMMY_ID, DUMMY_PW

TODAY = date(2026, 10, 6)


def F(num, level, ago=0, struggle=0, source="app", solved=True):
    return SolveFact(num, level, None if source == "swea" else TODAY - timedelta(days=ago), struggle, source, solved)


def clean(level, n, ago=0, start=1000):
    return [F(start + level * 100 + i, level, ago) for i in range(n)]


# --- 수준 모델 ---------------------------------------------------------------------------


def test_cold_start_defaults_to_d2():
    est = recommend.estimate_level([], TODAY)
    assert (est.level, est.confidence, est.source) == (2, "cold", "cold") and est.cold
    assert est.levels == (2, 3) and "D2" in est.basis


def test_cold_start_uses_selected_start_level_and_clamps():
    assert recommend.estimate_level([], TODAY, 4).level == 4
    assert recommend.estimate_level([], TODAY, 99).level == 8
    assert recommend.estimate_level([], TODAY, 0).level == 2  # 0/None → 기본


def test_cold_start_follows_highest_solved_level_when_above_start():
    est = recommend.estimate_level(clean(5, 1) + clean(3, 1), TODAY, 2)
    assert est.level == 5 and est.cold  # 판명 해결 2개 < 3 → 아직 콜드, 선택기 노출


def test_three_clean_passes_exactly_masters_level():
    est = recommend.estimate_level(clean(3, 3), TODAY)
    assert (est.level, est.confidence, est.n_known) == (3, "low", 3)
    assert est.basis == "최근 90일 3문제 기준" and est.levels == (3, 4)


def test_two_clean_passes_do_not_master():
    est = recommend.estimate_level(clean(3, 2), TODAY)
    assert est.cold and est.level == 3  # 콜드: max(시작 2, 가장 높은 해결 3)


def test_highest_mastered_level_wins():
    est = recommend.estimate_level(clean(2, 3) + clean(4, 3), TODAY)
    assert est.level == 4
    assert est.clean_n[4] == 3


def test_hard_ratio_exactly_half_keeps_mastery():
    hard = [F(9000 + i, 3, 0, struggle=3) for i in range(3)]  # hard 3 vs clean 6 → 정확히 0.5
    est = recommend.estimate_level(clean(2, 3) + clean(3, 6) + hard, TODAY)
    assert est.level == 3
    assert est.per_level[3] == (6.0, 3.0)


def test_hard_ratio_above_half_loses_mastery():
    hard = [F(9000 + i, 3, 0, struggle=3) for i in range(4)]  # 4 > 3
    est = recommend.estimate_level(clean(2, 3) + clean(3, 6) + hard, TODAY)
    assert est.level == 2


def test_unsolved_with_many_wrongs_counts_as_hard():
    unsolved = [F(8000 + i, 3, 0, struggle=4, solved=False) for i in range(4)]
    est = recommend.estimate_level(clean(2, 3) + clean(3, 3) + unsolved, TODAY)
    assert est.level == 2  # D3 의 hard 4 > 0.5 x clean 3


def test_half_life_weights_recent_struggle_more():
    base = clean(2, 3) + clean(3, 3, ago=60)  # D3 clean 가중 0.25 x 3 = 0.75
    recent_hard = [F(9001, 3, 0, struggle=3)]  # 1.0 > 0.375 → D3 숙달 실패
    old_hard = [F(9001, 3, 90, struggle=3)]  # 0.125 <= 0.375 → D3 숙달 유지
    assert recommend.estimate_level(base + recent_hard, TODAY).level == 2
    assert recommend.estimate_level(base + old_hard, TODAY).level == 3


def test_window_90_days_boundary():
    assert recommend.estimate_level(clean(4, 3, ago=90), TODAY).level == 4  # 정확히 90일은 포함
    est = recommend.estimate_level(clean(4, 3, ago=91), TODAY)
    assert est.cold and est.level == 4  # 91일은 창 밖: 사실로는 안 세고(콜드), 콜드의 "가장 높은 해결" 로만 반영
    assert est.n_known == 0


def test_unknown_level_is_excluded_and_reported():
    facts = clean(3, 3) + [F(7000, None, 1), F(7001, None, 2)]
    est = recommend.estimate_level(facts, TODAY)
    assert est.level == 3 and est.n_unknown == 2 and est.n_known == 3
    assert "난이도를 모르는 2문제 제외" in est.basis


def test_median_when_nobody_is_mastered():
    facts = [F(1, 2, 0), F(2, 2, 0), F(3, 4, 0), F(4, 4, 0)]  # 깨끗한 3개 미만, 판명 4개
    est = recommend.estimate_level(facts, TODAY)
    assert est.level == 3 and not est.cold and est.confidence == "low"  # 가중 중앙값 (2+4)/2 = 3 (반올림)


def test_median_leans_to_recent_facts():
    facts = [F(1, 2, 80), F(2, 2, 80), F(3, 5, 0), F(4, 5, 1), F(5, 5, 2)]
    assert recommend.estimate_level(facts, TODAY).level == 5


def test_confidence_ok_from_six_known():
    assert recommend.estimate_level(clean(3, 5), TODAY).confidence == "low"
    assert recommend.estimate_level(clean(3, 6), TODAY).confidence == "ok"


def test_level_8_clamps_candidate_band():
    est = recommend.estimate_level(clean(8, 3), TODAY)
    assert est.level == 8 and est.levels == (8,)


def test_swea_passed_list_approximates_level_when_app_facts_are_few():
    facts = [F(1, 2, source="swea"), F(2, 3, source="swea"), F(3, 3, source="swea"), F(4, 4, source="swea")]
    est = recommend.estimate_level(facts, TODAY)
    assert est.source == "swea" and est.confidence == "low" and est.level == 3  # 70분위 3.1 → 3
    assert est.basis == "SWEA 에서 푼 문제 기준"
    high = [F(i, lv, source="swea") for i, lv in enumerate([1, 1, 5, 5, 5])]
    assert recommend.estimate_level(high, TODAY).level == 5


def test_swea_list_is_ignored_when_app_facts_are_enough():
    swea = [F(100 + i, 1, source="swea") for i in range(5)]
    est = recommend.estimate_level(clean(4, 3) + swea, TODAY)
    assert est.level == 4 and est.source == "app"


def test_same_problem_prefers_app_fact_and_solved_over_unsolved():
    facts = [F(1, 3, source="swea"), F(1, 3, 0), F(2, 3, 0, struggle=4, solved=False), F(2, 3, 0)]
    est = recommend.estimate_level(facts + clean(3, 2, start=50), TODAY)
    assert est.n_known == 4  # 1, 2 는 한 번씩만


def test_facts_from_history_builds_app_unsolved_and_swea_facts():
    facts = recommend.facts_from_history(
        solved_first_day={1: TODAY, 2: TODAY - timedelta(days=5)},
        pass_wb={2: 3},
        unsolved=[(3, 4, TODAY), (4, 2, TODAY), (1, 5, TODAY)],  # 4: 오답 2회는 제외, 1: 이미 해결
        swea_passed=[5, 1],  # 1: 앱 기록이 우선
        levels={1: 2, 2: 3, 3: 4},
    )
    by = {f.num: f for f in facts}
    assert sorted(by) == [1, 2, 3, 5]
    assert (by[2].struggle, by[2].level, by[2].solved) == (3, 3, True)
    assert (by[3].solved, by[3].struggle) == (False, 4)
    assert by[5].source == "swea" and by[5].day is None and by[5].level is None
    assert by[1].source == "app"


def test_retry_candidates_sorted_and_filtered():
    rows = [(1, 3, "wrong"), (2, 5, "timeout"), (3, 2, "wrong"), (4, 9, "pass"), (5, 4, "wrong")]
    out = recommend.retry_candidates(rows, solved_nums={5})
    assert out == [RetryCand(2, 5), RetryCand(1, 3)]


# --- 시드 · 어간 -------------------------------------------------------------------------------


def test_day_seed_is_sha256_not_builtin_hash():
    expected = int(hashlib.sha256(b"2026-10-06:1:3").hexdigest()[:16], 16)
    assert recommend.day_seed(TODAY, 1, 3) == expected
    assert recommend.day_seed(TODAY, 1, 3) != recommend.day_seed(TODAY, 2, 3)
    assert recommend.day_seed(TODAY, 1, 3) != recommend.day_seed(TODAY + timedelta(days=1), 1, 3)


@pytest.mark.parametrize(
    "a,b",
    [("미로 1", "미로 2"), ("미로 [12]", "미로 [3]"), ("Maze I", "maze III"), ("탐색 Ⅱ", "탐색 Ⅲ"), ("달팽이 - 2", "달팽이 - 3"), ("A+B 12", "a+b")],
)
def test_stem_collapses_numbered_variants(a, b):
    assert recommend.stem(a) == recommend.stem(b)


def test_stem_keeps_distinct_titles_and_pure_numbers():
    assert recommend.stem("미로 탈출") != recommend.stem("미로")
    assert recommend.stem("1234") == "1234"  # 어간이 비면 원래 제목


# --- 후보 · 세트 -------------------------------------------------------------------------------


def make_catalog(levels=(2, 3, 4), per=20, over: dict | None = None) -> dict[int, CatalogItem]:
    out = {}
    for lv in levels:
        for i in range(per):
            n = lv * 1000 + i
            out[n] = CatalogItem(n, "X" * 16, f"주제{lv}{chr(0xAC00 + i * 7)}", lv, 20.0 + i * 3, 500 + i * 100, 100, i, 100)
    for n, kw in (over or {}).items():
        out[n] = CatalogItem(**{**out[n].__dict__, **kw})
    return out


EST3 = LevelEstimate(3, "ok", "근거", 6, 0, {3: (3.0, 0.0)}, {3: 4})
EST_COLD = LevelEstimate(2, "cold", "기록이 적어 D2 부터 시작해요", 0, 0, {}, {}, "cold")


def kinds(b):
    return [(p.kind, p.num // 1000) for p in b.picks]


def test_set_has_four_items_in_band_ordered_by_kind():
    cat = make_catalog()
    b = recommend.build_set(cat, EST3, day=TODAY)
    assert len(b.picks) == 4 and not b.short
    assert kinds(b) == [("fit", 3), ("fit", 3), ("stretch", 4), ("stretch", 4)]
    assert {cat[p.num].lv for p in b.picks} <= {3, 4}
    assert len({p.num for p in b.picks}) == 4


def test_set_is_deterministic_and_varies_by_day_and_shuffle():
    cat = make_catalog()
    base = [p.num for p in recommend.build_set(cat, EST3, day=TODAY).picks]
    assert base == [p.num for p in recommend.build_set(cat, EST3, day=TODAY).picks]
    others = {tuple(p.num for p in recommend.build_set(cat, EST3, day=TODAY, shuffle=k).picks) for k in range(1, 6)}
    others |= {tuple(p.num for p in recommend.build_set(cat, EST3, day=TODAY + timedelta(days=k)).picks) for k in range(1, 6)}
    assert len(others | {tuple(base)}) > 3


def test_solved_and_retry_and_recent_are_excluded():
    cat = make_catalog()
    solved = {3000 + i for i in range(10)}
    recent = {3010 + i: TODAY - timedelta(days=2) for i in range(4)}  # 2일 전 노출 → 제외 (RECENT_DAYS=3)
    old = {3014 + i: TODAY - timedelta(days=3) for i in range(2)}  # 3일 전은 허용
    for shuffle in range(8):
        b = recommend.build_set(cat, EST3, day=TODAY, shuffle=shuffle, solved_nums=solved, recent_shown={**recent, **old})
        nums = {p.num for p in b.picks}
        assert not nums & solved and not nums & set(recent)


def test_recent_exclusion_relaxes_when_pool_is_small():
    cat = make_catalog(levels=(3, 4), per=4)
    recent = {n: TODAY - timedelta(days=1) for n in cat}
    b = recommend.build_set(cat, EST3, day=TODAY, recent_shown=recent)
    assert len(b.picks) == 4  # 풀이 모자라 최근 노출 제외를 완화


def test_shuffle_avoids_already_shown_numbers_when_possible():
    cat = make_catalog()
    first = recommend.build_set(cat, EST3, day=TODAY)
    shown = {p.num for p in first.picks}
    second = recommend.build_set(cat, EST3, day=TODAY, shuffle=1, day_shown=shown)
    assert not shown & {p.num for p in second.picks}


def test_same_title_stem_appears_once_per_set():
    cat = make_catalog(levels=(3, 4), per=0)
    for i in range(12):
        cat[3000 + i] = CatalogItem(3000 + i, "X" * 16, f"미로 {i + 1}", 3, 50.0, 1000, 10, 1, 100)
    for i in range(12):
        cat[4000 + i] = CatalogItem(4000 + i, "X" * 16, f"탐색 {i + 1}", 4, 50.0, 1000, 10, 1, 100)
    for k in range(6):
        b = recommend.build_set(cat, EST3, day=TODAY, shuffle=k)
        stems = [recommend.stem(cat[p.num].title) for p in b.picks]
        assert len(stems) == len(set(stems))
        assert len(b.picks) == 2  # 어간이 같은 문제는 1개씩 → 풀 안에서는 2개뿐, 나머지는 확장 칸이 채울 수 없다


def test_retry_slot_comes_first_and_is_excluded_from_pools():
    cat = make_catalog()
    retry = [RetryCand(2005, 5), RetryCand(3001, 3)]
    b = recommend.build_set(cat, EST3, day=TODAY, retry=retry)
    assert b.picks[0].kind == "retry" and b.picks[0].num == 2005  # C-1 도 허용, 오답이 큰 순
    assert "오답 5회" in b.picks[0].reason and b.picks[0].source == "rule"
    assert [k for k, _ in kinds(b)] == ["retry", "fit", "stretch", "stretch"]
    assert 3001 not in {p.num for p in b.picks}  # 재도전 후보는 일반 풀에서도 빠진다


def test_retry_ignored_when_out_of_band_solved_or_missing():
    cat = make_catalog(levels=(1, 3, 4, 6))
    retry = [RetryCand(6001, 9), RetryCand(1001, 8), RetryCand(99999, 7), RetryCand(3002, 6)]  # D6/D1 은 |lv-C|>1, 없는 번호, 해결됨
    b = recommend.build_set(cat, EST3, day=TODAY, retry=retry, solved_nums={3002})
    assert all(p.kind != "retry" for p in b.picks)


def test_retry_not_repeated_on_shuffle():
    cat = make_catalog()
    retry = [RetryCand(3001, 4)]
    b = recommend.build_set(cat, EST3, day=TODAY, shuffle=1, retry=retry, day_shown={3001})
    assert all(p.kind != "retry" for p in b.picks)


def test_missing_pool_is_filled_by_other_pool_then_widened():
    cat = make_catalog(levels=(3,), per=5)  # D4 없음
    b = recommend.build_set(cat, EST3, day=TODAY)
    assert len(b.picks) == 4 and {cat[p.num].lv for p in b.picks} == {3}
    cat = make_catalog(levels=(2, 3), per=2)  # C 풀 2개 + C-1(D2) 2개 → fill
    b = recommend.build_set(cat, EST3, day=TODAY)
    assert len(b.picks) == 4
    assert [p.kind for p in b.picks].count("fill") == 2
    assert all("비슷한 난이도" in p.reason for p in b.picks if p.kind == "fill")


def test_c_plus_two_is_the_last_resort():
    cat = make_catalog(levels=(3, 5), per=3)
    b = recommend.build_set(cat, EST3, day=TODAY)
    assert {cat[p.num].lv for p in b.picks} == {3, 5} and len(b.picks) == 4


def test_short_set_when_catalog_is_tiny():
    cat = make_catalog(levels=(3,), per=2)
    b = recommend.build_set(cat, EST3, day=TODAY)
    assert len(b.picks) == 2 and b.short


def test_level_8_uses_only_level_8():
    cat = make_catalog(levels=(7, 8), per=10)
    est = LevelEstimate(8, "ok", "x", 6, 0, {}, {8: 3})
    b = recommend.build_set(cat, est, day=TODAY)
    assert len(b.picks) == 4 and all(cat[p.num].lv in (8, 7) for p in b.picks)  # 8 이 모자라면 C-1 확장


def test_quality_floor_is_soft():
    cat = make_catalog(levels=(3, 4), per=12)
    low = {3000 + i: {"pa": 50} for i in range(6)}  # D3 12개 중 6개가 참여자 50
    for n, kw in low.items():
        cat[n] = CatalogItem(**{**cat[n].__dict__, **kw})
    picked = {p.num for k in range(6) for p in recommend.build_set(cat, EST3, day=TODAY, shuffle=k).picks}
    assert not picked & set(low)  # 남은 풀이 충분하면 하한 적용 (필요 2 x 2 = 4 <= 6)
    tiny = make_catalog(levels=(3, 4), per=3)
    for n in list(tiny):
        tiny[n] = CatalogItem(**{**tiny[n].__dict__, "pa": 10})
    assert len(recommend.build_set(tiny, EST3, day=TODAY).picks) >= 3  # 풀이 작으면 하한 무시


def test_missing_metrics_are_neutral():
    items = [CatalogItem(1, "X" * 16, "a", 3, None, None, None, None, None), CatalogItem(2, "X" * 16, "b", 3, 10.0, 100, 1, 1, 1),
             CatalogItem(3, "X" * 16, "c", 3, 90.0, 9000, 1, 9, 1)]
    q = recommend.quality_scores(items, recommend.WEIGHTS_FIT)
    assert q[1] == pytest.approx(0.5) and q[3] > q[1] > q[2]
    assert recommend.quality_scores([], recommend.WEIGHTS_FIT) == {}


def test_reasons_follow_templates():
    r = recommend.reason_for
    assert r("retry", EST3, 4) == "오답 4회로 남아 있어요 · 다시 도전해 볼까요"
    assert r("fit", EST3) == "최근 D3 를 4문제 안정적으로 풀었어요 · 같은 수준으로 감을 굳혀요"
    assert r("stretch", EST3) == "D3 를 안정적으로 풀었어요 · 한 단계 올려 볼 때예요"
    assert r("fit", EST_COLD) == "기록이 적어 D2 부터 시작해요"
    assert r("stretch", EST_COLD) == "한 단계 위 문제로 가볍게 도전해요"
    assert r("fill", EST3) == "비슷한 난이도 중 많은 사람이 푼 문제예요"
    no_clean = LevelEstimate(3, "low", "x", 4, 0, {}, {})
    assert "안정적으로" not in r("fit", no_clean) and "안정적으로" not in r("stretch", no_clean)  # 근거 없는 숫자를 만들지 않는다


def test_ai_picks_fill_non_retry_slots_in_ai_order():
    cat = make_catalog()
    ai = [AiPick(3005, "DFS 약점 훈련"), AiPick(4002, "한 단계 위"), AiPick(3011, None), AiPick(4009, "x"), AiPick(3002, "y")]
    b = recommend.build_set(cat, EST3, day=TODAY, ai_picks=ai)
    assert [p.num for p in b.picks if p.source == "ai"] == [3005, 3011, 4002, 4009]  # kind 순서(fit→stretch), 안에서는 AI 순위
    assert b.ai_used == 4 and {p.source for p in b.picks} == {"ai"}
    first = next(p for p in b.picks if p.num == 3005)
    assert first.reason == "DFS 약점 훈련"
    nores = next(p for p in b.picks if p.num == 3011)
    assert nores.reason == recommend.reason_for("fit", EST3)  # 이유가 없으면 규칙 문구


def test_ai_picks_skip_invalid_and_continue_from_cursor():
    cat = make_catalog()
    ai = [AiPick(9999), AiPick(3001), AiPick(3001), AiPick(5001), AiPick(3002), AiPick(3003), AiPick(4001), AiPick(4002), AiPick(4003)]
    b = recommend.build_set(cat, EST3, day=TODAY, ai_picks=ai, solved_nums={3002})
    nums = [p.num for p in b.picks]
    assert 9999 not in nums and 5001 not in nums and 3002 not in nums and nums.count(3001) == 1  # 풀 밖·구간 밖·푼 문제·중복은 버림
    assert b.ai_used == 8  # 건너뛴 항목도 소비한 것으로 센다 (9번째 4003 은 다음 세트용)
    nxt = recommend.build_set(cat, EST3, day=TODAY, shuffle=1, ai_picks=ai, ai_cursor=b.ai_used, day_shown=nums)
    assert sum(1 for p in nxt.picks if p.source == "ai") == 1 and len(nxt.picks) == 4  # 남은 1개 + 규칙으로 채움


def test_ai_does_not_replace_retry_slot():
    cat = make_catalog()
    ai = [AiPick(3001), AiPick(3002), AiPick(4001), AiPick(4002)]
    b = recommend.build_set(cat, EST3, day=TODAY, retry=[RetryCand(3010, 5)], ai_picks=ai)
    assert b.picks[0].kind == "retry" and b.picks[0].source == "rule"
    assert sum(1 for p in b.picks if p.source == "ai") == 3 and len(b.picks) == 4


# --- 세트 저장 ----------------------------------------------------------------------------------


def make_day(**kw) -> recommend.DaySet:
    base = dict(date="2026-10-06", shuffle=1, level_c=3, conf="ok", start=2,
                items=[{"n": 3001, "k": "fit", "r": "이유", "src": "rule"}], day_shown=[3001], recent_shown={"3001": "2026-10-06"},
                ai={"status": "ok", "engines": ["codex"], "picks": [{"n": 3005, "r": "약점"}], "cursor": 4, "fail_count": 0})
    base.update(kw)
    return recommend.DaySet(**base)


def test_day_set_round_trip(settings):
    assert recommend.save_day(settings, make_day())
    path = recommend.day_path(settings)
    assert path.parent == growth.profile_dir(settings) and path.name == "recommend.json"
    ds = recommend.load_day(settings)
    assert ds == make_day()
    assert ds.ai_status() == "ok" and ds.ai_picks() == [AiPick(3005, "약점")]
    assert ds.recent_dates() == {3001: TODAY}
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["v"] == 1 and raw["level"] == {"c": 3, "conf": "ok", "start": 2}


def test_load_day_missing_corrupt_and_wrong_version(settings):
    assert recommend.load_day(settings) is None
    path = recommend.day_path(settings)
    path.parent.mkdir(parents=True)
    path.write_text("{oops", encoding="utf-8")
    assert recommend.load_day(settings) is None
    assert not path.exists() and path.with_suffix(".json.corrupt").exists()
    path.write_text(json.dumps({"v": 7, "date": "2026-10-06"}), encoding="utf-8")
    assert recommend.load_day(settings) is None
    path.write_text(json.dumps({"v": 1, "date": "not-a-date"}), encoding="utf-8")
    assert recommend.load_day(settings) is None


def test_load_day_cleans_bad_items(settings):
    path = recommend.day_path(settings)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"v": 1, "date": "2026-10-06", "items": [{"n": 1, "k": "weird", "r": 5, "src": "x"}, {"n": "2"}, "bad", {"n": True}],
                                "day_shown": [1, "x", 2], "ai": {"status": "bogus"}}), encoding="utf-8")
    ds = recommend.load_day(settings)
    assert ds.items == [{"n": 1, "k": "fill", "r": "5", "src": "rule"}] and ds.day_shown == [1, 2] and ds.ai_status() == "none"


def test_save_day_refuses_inside_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    s = Settings(root=root, user_id=DUMMY_ID, password=DUMMY_PW, config_dir=root / "cfg")
    assert recommend.save_day(s, make_day()) is False
    assert not (root / "cfg").exists()


def test_prune_recent_keeps_14_days():
    out = recommend.prune_recent({"1": "2026-10-06", "2": "2026-09-22", "3": "2026-09-21", "4": "bad"}, TODAY)
    assert set(out) == {"1", "2"}


# --- AI payload · 파서 · 합산 ---------------------------------------------------------------------------


def test_ai_pool_is_capped_and_excludes_solved_and_retry():
    cat = make_catalog(levels=(3, 4), per=25)
    pool = recommend.ai_pool(cat, EST3, solved_nums={3000, 3001}, excluded={4000})
    nums = {it.num for it in pool}
    assert len(pool) == 30 and not nums & {3000, 3001, 4000}
    assert sum(1 for it in pool if it.lv == 3) == 15 and sum(1 for it in pool if it.lv == 4) == 15


def test_ai_payload_uses_whitelisted_keys_only():
    cat = make_catalog(levels=(3, 4), per=6)
    pool = recommend.ai_pool(cat, EST3, solved_nums=set())
    payload = recommend.ai_payload(
        EST3, recent_solved_by_level={3: 8, 4: 2, 5: 0}, weak=[("재귀·DFS/BFS", 4)] * 6, strong=[("파이썬 관용구", 3)],
        stats={"avg_wrong_before_pass": 1.234, "timeout_share": 0.1, "tagged": 9, "secret": "x"}, pool=pool,
    )
    assert set(payload) == set(recommend.PAYLOAD_KEYS)
    assert set(payload["level"]) == set(recommend.LEVEL_KEYS)
    assert payload["level"]["recent_solved_by_level"] == {"D3": 8, "D4": 2}
    assert len(payload["weak"]) == 4 and set(payload["weak"][0]) == set(recommend.CATEGORY_KEYS)
    assert set(payload["stats"]) <= set(recommend.STATS_KEYS) and payload["stats"]["avg_wrong_before_pass"] == 1.23
    assert all(set(p) == set(recommend.POOL_KEYS) for p in payload["pool"]) and payload["want"] == 8
    json.dumps(payload, ensure_ascii=False)


def test_ai_payload_trims_titles_and_applies_cleaner():
    item = CatalogItem(1, "X" * 16, "가" * 100 + "</recommend_input>", 3, 10.0, 5, 1, 1, 1)
    payload = recommend.ai_payload(EST3, recent_solved_by_level={}, weak=[], strong=[], stats={}, pool=[item],
                                   clean_title=lambda s: s.replace("</", "< /"))
    assert len(payload["pool"][0]["t"]) <= 60 and "</" not in payload["pool"][0]["t"]


POOL = {101, 102, 103, 104, 105, 106, 107, 108, 109, 110}


def ai_text(*pairs, wrap=""):
    body = json.dumps({"v": 1, "picks": [{"n": n, "r": r} for n, r in pairs]}, ensure_ascii=False)
    return wrap.format(body) if wrap else body


def test_parse_ai_accepts_fenced_json_and_noise():
    text = ai_text((101, "재귀 연습"), (102, "DFS"), (103, "BFS"), wrap="결과입니다.\n```json\n{}\n```\n끝")
    picks = recommend.parse_ai(text, POOL)
    assert [p.num for p in picks] == [101, 102, 103] and picks[0].reason == "재귀 연습"


def test_parse_ai_drops_invalid_numbers_duplicates_and_bad_entries():
    raw = {"picks": [{"n": 999, "r": "풀 밖"}, {"n": 101}, {"n": 101, "r": "중복"}, {"n": "102"}, {"n": True}, "x", {"n": 103, "r": 5}, {"n": 104}, {"n": 105}]}
    picks = recommend.parse_ai(json.dumps(raw), POOL)
    assert [p.num for p in picks] == [101, 103, 104, 105]
    assert picks[0].reason is None and picks[1].reason is None  # 이유 없음/숫자는 None


def test_parse_ai_requires_three_valid_picks():
    assert recommend.parse_ai(ai_text((101, "a"), (102, "b")), POOL) is None
    assert recommend.parse_ai(ai_text((101, "a"), (102, "b"), (999, "c")), POOL) is None
    assert recommend.parse_ai(ai_text((101, "a"), (102, "b"), (103, "c")), POOL) is not None


@pytest.mark.parametrize("text", ["", "no json", "{bad", '{"picks": 3}', '{"v":1}', "[1,2,3]", "}{"])
def test_parse_ai_rejects_malformed(text):
    assert recommend.parse_ai(text, POOL) is None


def test_parse_ai_caps_at_eight():
    picks = recommend.parse_ai(ai_text(*[(n, "r") for n in sorted(POOL)]), POOL)
    assert len(picks) == 8 and [p.num for p in picks] == sorted(POOL)[:8]


def test_sanitize_reason():
    s = recommend.sanitize_reason
    assert s("  **좋은** 문제\n[링크](http://x.y) `코드` ```py``` https://evil.example/a  ") == "**좋은** 문제 링크 코드"
    assert s("a" * 200) == "a" * 60
    assert s("\x00\x07\n") is None and s("") is None and s(None) is None and s(5) is None


def test_merge_ai_votes_and_reason_priority():
    codex = [AiPick(1, "코덱스 이유"), AiPick(2, None), AiPick(3, "c3")]
    claude = [AiPick(2, "클로드 이유"), AiPick(4, "c4"), AiPick(1, None)]
    merged = recommend.merge_ai([codex, claude])
    assert [p.num for p in merged] == [2, 1, 4, 3] or [p.num for p in merged][:2] in ([1, 2], [2, 1])
    by = {p.num: p.reason for p in merged}
    assert by[1] == "코덱스 이유" and by[2] == "클로드 이유"  # 이유는 앞선 엔진 우선, 없으면 다음 엔진
    both = [p.num for p in merged][:2]
    assert set(both) == {1, 2}  # 두 엔진 모두 고른 문제가 앞


def test_merge_ai_tie_breaks_by_quality_then_number():
    merged = recommend.merge_ai([[AiPick(5), AiPick(6)], [AiPick(6), AiPick(5)]], {5: 0.2, 6: 0.9})
    assert [p.num for p in merged] == [6, 5]
    assert [p.num for p in recommend.merge_ai([[AiPick(9)]])] == [9]
