"""ai_models: Codex 모델 목록(models_cache.json) 읽기 · 가벼운 모델 자동 선택 · 분류용 엔진/모델 고르기 · 설정 콤보 항목 (M24.2). 순수 — 파일 읽기만."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from swea_fetcher import ai_models
from swea_fetcher.ai_models import ClassifyModel, CodexModel


def row(slug, name=None, vis="list", prio=1, efforts=("low", "medium", "high")):
    return {"slug": slug, "display_name": name or slug, "visibility": vis, "priority": prio, "supported_reasoning_levels": [{"effort": e, "description": "x"} for e in efforts]}


def write_cache(home: Path, models) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / "models_cache.json"
    path.write_text(json.dumps({"fetched_at": "x", "models": models}), encoding="utf-8")
    return path


@pytest.fixture
def home(tmp_path):
    return tmp_path / "codex_home"


REAL_SHAPE = [
    row("gpt-6.1-sol", "GPT-6.1-Sol", prio=1, efforts=("low", "medium", "ultra")),
    row("gpt-6-sol", "GPT-6-Sol", prio=3),
    row("gpt-6-luna", "GPT-6-Luna", prio=4, efforts=("low", "medium", "high", "xhigh", "max")),
    row("gpt-reserve", "GPT-Reserve", vis="hide", prio=4),
    row("gpt-5.6-luna", "GPT-5.6-Luna", prio=9),
]


# --- 모델 목록 읽기 ------------------------------------------------------------------------------------


def test_codex_home_prefers_env_then_dot_codex(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "elsewhere"))
    assert ai_models.codex_home() == tmp_path / "elsewhere"
    monkeypatch.delenv("CODEX_HOME")
    assert ai_models.codex_home() == Path.home() / ".codex"
    monkeypatch.setenv("CODEX_HOME", "   ")
    assert ai_models.codex_home() == Path.home() / ".codex"


def test_load_models_keeps_only_listed_ones_sorted_by_priority(home):
    write_cache(home, list(reversed(REAL_SHAPE)))
    models = ai_models.load_codex_models(home)
    assert [m.slug for m in models] == ["gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-luna"]  # hide 는 빠진다
    assert models[2] == CodexModel("gpt-6-luna", "GPT-6-Luna", 4, ("low", "medium", "high", "xhigh", "max"))


def test_load_models_uses_codex_home_env_by_default(monkeypatch, home):
    write_cache(home, REAL_SHAPE)
    monkeypatch.setenv("CODEX_HOME", str(home))
    assert [m.slug for m in ai_models.load_codex_models()][:1] == ["gpt-6.1-sol"]


@pytest.mark.parametrize("content", ["", "{broken", "[]", '{"models": "x"}', '{"models": [1, "a", {"slug": 5}, {"slug": "has space", "visibility": "list"}, {"slug": "a;b", "visibility": "list"}]}', "null"])
def test_load_models_tolerates_corrupt_or_odd_files(home, content):
    home.mkdir(parents=True)
    (home / "models_cache.json").write_text(content, encoding="utf-8")
    assert ai_models.load_codex_models(home) == []


def test_load_models_missing_file_or_folder_is_empty(home):
    assert ai_models.load_codex_models(home) == []
    home.mkdir()
    assert ai_models.load_codex_models(home) == []


def test_load_models_ignores_oversized_files(home):
    path = write_cache(home, REAL_SHAPE)
    path.write_text(" " * (ai_models.MAX_CACHE_BYTES + 1), encoding="utf-8")
    assert ai_models.load_codex_models(home) == []


def test_load_models_defaults_for_missing_fields(home):
    write_cache(home, [{"slug": "plain", "visibility": "list"}])
    assert ai_models.load_codex_models(home) == [CodexModel("plain", "plain", 999, ())]


def test_only_models_cache_is_opened_never_auth_json(home, monkeypatch):
    """같은 폴더의 로그인 정보 파일(auth.json)은 stat 도 읽기도 하지 않는다."""
    write_cache(home, REAL_SHAPE)
    (home / "auth.json").write_text('{"tokens": {"access_token": "SECRET_TOKEN_ZZZ"}}', encoding="utf-8")
    touched: list[str] = []
    real_open, real_read_text, real_stat = builtins.open, Path.read_text, Path.stat

    def spy_open(file, *a, **kw):
        touched.append(Path(str(file)).name)
        return real_open(file, *a, **kw)

    def spy_read_text(self, *a, **kw):
        touched.append(self.name)
        return real_read_text(self, *a, **kw)

    def spy_stat(self, *a, **kw):
        touched.append(self.name)
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(Path, "read_text", spy_read_text)
    monkeypatch.setattr(Path, "stat", spy_stat)
    models = ai_models.load_codex_models(home)
    monkeypatch.undo()
    assert models and touched and set(touched) == {"models_cache.json"}
    assert "SECRET_TOKEN_ZZZ" not in repr(models)


# --- 가벼운 모델 · 선택 --------------------------------------------------------------------------------


def test_light_model_picks_lowest_priority_luna():
    ms = [CodexModel("gpt-5.6-luna", "L5", 9), CodexModel("gpt-6-luna", "L6", 4), CodexModel("gpt-6-sol", "S", 3)]
    assert ai_models.light_model(ms).slug == "gpt-6-luna"  # priority 숫자가 작은 luna
    assert ai_models.light_model([CodexModel("gpt-6-sol", "S", 3)]) is None and ai_models.light_model([]) is None
    assert ai_models.light_model([CodexModel("GPT-X-LUNA", "x", 1)]).slug == "GPT-X-LUNA"


def test_auto_picks_luna_with_low_effort_from_a_real_shaped_cache(home):
    write_cache(home, REAL_SHAPE)
    got = ai_models.choose("auto", ["codex", "claude"], ai_models.load_codex_models(home))
    assert got == ClassifyModel("codex", "gpt-6-luna", "low") and got.label == "gpt-6-luna"


def test_auto_without_a_cache_uses_the_codex_default_model():
    got = ai_models.choose("auto", ["codex"], [])
    assert got == ClassifyModel("codex", "", "low") and got.label == "Codex 기본 모델"  # -m 없음


def test_auto_without_luna_uses_the_codex_default_model():
    got = ai_models.choose("auto", ["codex"], [CodexModel("gpt-6-sol", "S", 3, ("low",))])
    assert got.model == "" and got.effort == "low"


def test_low_effort_is_dropped_when_the_model_does_not_support_it():
    got = ai_models.choose("auto", ["codex"], [CodexModel("gpt-6-luna", "L", 4, ("medium", "high"))])
    assert got == ClassifyModel("codex", "gpt-6-luna", "")


def test_explicit_codex_model_and_removed_model_fallback():
    ms = [CodexModel("gpt-6-sol", "S", 3, ("low",)), CodexModel("gpt-6-luna", "L", 4, ("low",))]
    assert ai_models.choose("codex:gpt-6-sol", ["codex"], ms).model == "gpt-6-sol"
    assert ai_models.choose("codex:gone-model", ["codex"], ms).model == "gpt-6-luna"  # 목록에서 사라졌으면 자동 선택
    assert ai_models.choose("codex:anything", ["codex"], []).model == "anything"  # 목록을 못 읽었으면 저장된 값을 그대로


def test_claude_choice_and_engine_fallbacks():
    ms = [CodexModel("gpt-6-luna", "L", 4, ("low",))]
    assert ai_models.choose("claude:haiku", ["codex", "claude"], ms) == ClassifyModel("claude", "haiku")
    assert ai_models.choose("auto", ["claude"], ms) == ClassifyModel("claude", "haiku")  # Codex 가 없거나 동의 안 했으면 Claude Haiku
    assert ai_models.choose("claude:haiku", ["codex"], ms).engine == "codex"  # 고른 엔진을 못 쓰면 동의한 다른 엔진으로
    assert ai_models.choose("codex:gpt-6-luna", ["claude"], ms) == ClassifyModel("claude", "haiku")
    assert ai_models.choose("auto", [], ms) is None


@pytest.mark.parametrize("value", ["", "auto", "bogus", "codex:", "codex:a b", "codex:x;y", "claude:opus", "CLAUDE:haiku"])
def test_parse_pref_rejects_unknown_values(value):
    assert ai_models.parse_pref(value) == ("", "")


def test_parse_pref_accepts_known_values():
    assert ai_models.parse_pref("codex:gpt-6-luna") == ("codex", "gpt-6-luna") and ai_models.parse_pref(" claude:haiku ") == ("claude", "haiku")


def test_options_for_the_settings_combo():
    ms = [CodexModel("gpt-6-sol", "GPT-6-Sol", 3), CodexModel("gpt-6-luna", "GPT-6-Luna", 4)]
    assert ai_models.options(ms, claude_found=True) == [
        ("auto", "자동 (가벼운 모델)"), ("codex:gpt-6-sol", "GPT-6-Sol"), ("codex:gpt-6-luna", "GPT-6-Luna"), ("claude:haiku", "Claude Haiku")]
    assert ai_models.options(ms, claude_found=False)[-1] == ("codex:gpt-6-luna", "GPT-6-Luna")  # Claude 는 감지될 때만
    assert ai_models.options([], claude_found=False) == [("auto", "자동 (가벼운 모델)")]
    kept = ai_models.options([], claude_found=False, current="claude:haiku")  # 저장된 선택이 목록에 없어도 남긴다
    assert kept[-1][0] == "claude:haiku" and "설치 안 됨" in kept[-1][1]
    assert "목록에 없음" in ai_models.options(ms, claude_found=False, current="codex:old")[-1][1]
    assert ai_models.options(ms, claude_found=False, current="junk") == ai_models.options(ms, claude_found=False)
