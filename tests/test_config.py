"""config.load_settings / Settings / keyring helper / .env helper."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from swea_fetcher import config
from swea_fetcher.config import KEYRING_SERVICE, Settings, load_settings
from swea_fetcher.errors import ConfigMissing
from tests.conftest import DUMMY_ID, DUMMY_PW


def _write_env(config_dir: Path, **kv: str) -> Path:
    env_file = config_dir / ".env"
    env_file.write_text("".join(f"{k}={v}\n" for k, v in kv.items()), encoding="utf-8")
    return env_file


@pytest.fixture
def env_with_id(root_dir: Path, config_dir: Path) -> Path:
    return _write_env(config_dir, SWEA_ROOT=str(root_dir), SWEA_ID=DUMMY_ID)


# =============================================================================
# 비밀번호 출처: env → dotenv → keyring
# =============================================================================


def test_password_from_keyring(env_with_id, root_dir, config_dir, fake_keyring):
    fake_keyring.store[(KEYRING_SERVICE, DUMMY_ID)] = DUMMY_PW
    s = load_settings(config_dir)
    assert s.root == root_dir
    assert s.user_id == DUMMY_ID
    assert s.password == DUMMY_PW
    assert s.password_source == "keyring"
    assert ("get", KEYRING_SERVICE, DUMMY_ID) in fake_keyring.calls
    assert s.input_name == "input.txt" and s.output_name == "output.txt"
    assert s.config_dir == config_dir
    assert s.session_file == config_dir / "session.json"
    assert s.login_state_file == config_dir / "login_state.json"


def test_password_from_process_env_skips_keyring(env_with_id, config_dir, fake_keyring, monkeypatch):
    monkeypatch.setenv("SWEA_PW", "from-env")
    s = load_settings(config_dir)
    assert (s.password, s.password_source) == ("from-env", "env")
    assert fake_keyring.calls == []


def test_password_from_dotenv_warns(root_dir, config_dir, fake_keyring, caplog):
    _write_env(config_dir, SWEA_ROOT=str(root_dir), SWEA_ID=DUMMY_ID, SWEA_PW="plain-pw")
    with caplog.at_level(logging.WARNING, logger="swea_fetcher.config"):
        s = load_settings(config_dir)
    assert (s.password, s.password_source) == ("plain-pw", "dotenv")
    assert any("migrate" in r.getMessage() for r in caplog.records)
    assert "plain-pw" not in caplog.text
    assert fake_keyring.calls == []


def test_env_password_beats_dotenv(root_dir, config_dir, monkeypatch):
    _write_env(config_dir, SWEA_ROOT=str(root_dir), SWEA_ID=DUMMY_ID, SWEA_PW="plain-pw")
    monkeypatch.setenv("SWEA_PW", "env-pw")
    assert load_settings(config_dir).password == "env-pw"


def test_password_nowhere_raises(env_with_id, config_dir):
    with pytest.raises(ConfigMissing) as ei:
        load_settings(config_dir)
    msg = str(ei.value)
    assert "SWEA_PW" in msg and KEYRING_SERVICE in msg and DUMMY_ID in msg


def test_keyring_backend_error_becomes_config_missing(env_with_id, config_dir, fake_keyring):
    fake_keyring.fail = fake_keyring.errors.KeyringError("no backend")
    with pytest.raises(ConfigMissing, match="자격 증명 관리자"):
        load_settings(config_dir)


def test_load_settings_does_not_touch_os_environ(env_with_id, config_dir, fake_keyring):
    fake_keyring.store[(KEYRING_SERVICE, DUMMY_ID)] = DUMMY_PW
    load_settings(config_dir)
    assert "SWEA_ID" not in os.environ and "SWEA_ROOT" not in os.environ


# =============================================================================
# 필수 키 / 우선순위 / 정규화
# =============================================================================


def test_loads_from_process_env_without_env_file(root_dir, config_dir, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(root_dir))
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    s = load_settings(config_dir)
    assert s.root == root_dir and s.user_id == DUMMY_ID


def test_process_env_takes_precedence_over_env_file(root_dir, config_dir, monkeypatch):
    _write_env(config_dir, SWEA_ROOT=str(root_dir), SWEA_ID="from_file", SWEA_PW="pw_file")
    monkeypatch.setenv("SWEA_ID", "from_env")
    s = load_settings(config_dir)
    assert s.user_id == "from_env"
    assert s.password == "pw_file"


def test_optional_file_names(root_dir, config_dir, monkeypatch):
    _write_env(
        config_dir, SWEA_ROOT=str(root_dir), SWEA_ID=DUMMY_ID, SWEA_PW=DUMMY_PW,
        SWEA_INPUT_NAME="in.txt", SWEA_OUTPUT_NAME="out.txt",
    )
    s = load_settings(config_dir)
    assert (s.input_name, s.output_name) == ("in.txt", "out.txt")


def test_blank_optional_names_fall_back_to_default(root_dir, config_dir, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(root_dir))
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    monkeypatch.setenv("SWEA_INPUT_NAME", "   ")
    assert load_settings(config_dir).input_name == "input.txt"


def test_root_and_id_are_stripped_but_password_is_not(root_dir, config_dir, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", f"  {root_dir}  ")
    monkeypatch.setenv("SWEA_ID", f" {DUMMY_ID} ")
    monkeypatch.setenv("SWEA_PW", " pw ")
    s = load_settings(config_dir)
    assert s.root == root_dir and s.user_id == DUMMY_ID and s.password == " pw "


def test_root_tilde_is_expanded(config_dir, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", "~")
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    assert load_settings(config_dir).root == Path.home()


def test_keyring_lookup_uses_stripped_id(root_dir, config_dir, fake_keyring):
    _write_env(config_dir, SWEA_ROOT=str(root_dir), SWEA_ID=f"  {DUMMY_ID}  ")
    fake_keyring.store[(KEYRING_SERVICE, DUMMY_ID)] = DUMMY_PW
    assert load_settings(config_dir).password == DUMMY_PW


def test_missing_everything(config_dir):
    with pytest.raises(ConfigMissing) as ei:
        load_settings(config_dir)
    msg = str(ei.value)
    assert "SWEA_ROOT" in msg and "SWEA_ID" in msg and "SWEA_PW" in msg
    assert "swea-fetch init" in msg


def test_missing_id_but_env_pw_does_not_list_pw(root_dir, config_dir, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(root_dir))
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    with pytest.raises(ConfigMissing) as ei:
        load_settings(config_dir)
    listed = str(ei.value).split("설정이 없습니다:")[1].split(".")[0]
    assert "SWEA_ID" in listed and "SWEA_PW" not in listed and "SWEA_ROOT" not in listed


def test_whitespace_only_value_counts_as_missing(root_dir, config_dir, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(root_dir))
    monkeypatch.setenv("SWEA_ID", "   ")
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    with pytest.raises(ConfigMissing):
        load_settings(config_dir)


def test_root_not_a_directory(tmp_path, config_dir, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(tmp_path / "nope"))
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    with pytest.raises(ConfigMissing, match="SWEA_ROOT"):
        load_settings(config_dir)


def test_root_is_a_file_not_dir(tmp_path, config_dir, monkeypatch):
    f = tmp_path / "file.txt"
    f.write_text("x")
    monkeypatch.setenv("SWEA_ROOT", str(f))
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    with pytest.raises(ConfigMissing):
        load_settings(config_dir)


def test_default_config_dir_is_used_when_none(root_dir, monkeypatch):
    """config_dir=None 이면 config.CONFIG_DIR (테스트에선 tmp 로 패치됨)."""
    _write_env(config.CONFIG_DIR, SWEA_ROOT=str(root_dir), SWEA_ID=DUMMY_ID, SWEA_PW=DUMMY_PW)
    s = load_settings()
    assert s.config_dir == config.CONFIG_DIR


# =============================================================================
# 비밀번호 유출 방지
# =============================================================================


def test_repr_and_str_mask_password(settings: Settings):
    for rendered in (repr(settings), str(settings)):
        assert DUMMY_PW not in rendered
        assert "***" in rendered
        assert DUMMY_ID in rendered


def test_settings_is_frozen(settings: Settings):
    with pytest.raises(Exception):
        settings.user_id = "x"  # type: ignore[misc]


def test_load_settings_does_not_leak_password_in_exception(root_dir, config_dir, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(root_dir / "missing"))
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    with pytest.raises(ConfigMissing) as ei:
        load_settings(config_dir)
    assert DUMMY_PW not in str(ei.value)


# =============================================================================
# keyring helper
# =============================================================================


def test_save_get_delete_password_roundtrip(fake_keyring):
    assert config.get_password(DUMMY_ID) is None
    config.save_password(DUMMY_ID, DUMMY_PW)
    assert fake_keyring.store == {(KEYRING_SERVICE, DUMMY_ID): DUMMY_PW}
    assert config.get_password(DUMMY_ID) == DUMMY_PW
    assert config.delete_password(DUMMY_ID) is True
    assert config.get_password(DUMMY_ID) is None


def test_delete_password_missing_returns_false(fake_keyring):
    assert config.delete_password("nobody") is False


@pytest.mark.parametrize("fn", [lambda: config.get_password("u"), lambda: config.save_password("u", "p"), lambda: config.delete_password("u")])
def test_keyring_error_is_config_missing(fake_keyring, fn):
    fake_keyring.fail = fake_keyring.errors.KeyringError("locked")
    with pytest.raises(ConfigMissing, match="SWEA_PW"):
        fn()


# =============================================================================
# .env helper
# =============================================================================


def test_read_env_file_missing_is_empty(config_dir):
    assert config.read_env_file(config_dir) == {}


def test_read_env_file_values(root_dir, config_dir):
    _write_env(config_dir, SWEA_ROOT=str(root_dir), SWEA_ID=DUMMY_ID)
    v = config.read_env_file(config_dir)
    assert v["SWEA_ROOT"] == str(root_dir) and v["SWEA_ID"] == DUMMY_ID


def test_strip_password_from_env_file(config_dir):
    (config_dir / ".env").write_text(
        "SWEA_ROOT=C:/x\n  SWEA_PW=secret\nSWEA_ID=me\nexport SWEA_PW=secret2\nSWEA_PW_OTHER=keep\n", encoding="utf-8"
    )
    assert config.strip_password_from_env_file(config_dir) is True
    text = (config_dir / ".env").read_text(encoding="utf-8")
    assert "secret" not in text
    assert "SWEA_ROOT=C:/x" in text and "SWEA_ID=me" in text and "SWEA_PW_OTHER=keep" in text


def test_strip_password_noop(config_dir):
    assert config.strip_password_from_env_file(config_dir) is False  # 파일 없음
    (config_dir / ".env").write_text("SWEA_ID=me\n", encoding="utf-8")
    assert config.strip_password_from_env_file(config_dir) is False
    assert (config_dir / ".env").read_text(encoding="utf-8") == "SWEA_ID=me\n"


# =============================================================================
# v0.3.3: SWEA_PYTHON
# =============================================================================


def test_python_default_none(env_with_id, config_dir, fake_keyring):
    fake_keyring.store[(KEYRING_SERVICE, DUMMY_ID)] = DUMMY_PW
    assert load_settings(config_dir).python is None


def test_python_from_env_file_and_env_var(root_dir, config_dir, fake_keyring, monkeypatch):
    _write_env(config_dir, SWEA_ROOT=str(root_dir), SWEA_ID=DUMMY_ID, SWEA_PYTHON="C:/py/python.exe")
    fake_keyring.store[(KEYRING_SERVICE, DUMMY_ID)] = DUMMY_PW
    assert load_settings(config_dir).python == "C:/py/python.exe"
    monkeypatch.setenv("SWEA_PYTHON", "  D:/other/python.exe  ")
    assert load_settings(config_dir).python == "D:/other/python.exe"


# =============================================================================
# M17: AI 코치 설정 (SWEA_AI_ENGINE / SWEA_AI_WRONG_THRESHOLD / SWEA_REVIEW_DAYS)
# =============================================================================


def _load_ai(root_dir, config_dir, fake_keyring, **kv):
    fake_keyring.store[(KEYRING_SERVICE, DUMMY_ID)] = DUMMY_PW
    _write_env(config_dir, SWEA_ROOT=str(root_dir), SWEA_ID=DUMMY_ID, **kv)
    return load_settings(config_dir)


def test_ai_settings_defaults(root_dir, config_dir, fake_keyring):
    s = _load_ai(root_dir, config_dir, fake_keyring)
    assert (s.ai_engine, s.ai_wrong_threshold, s.review_days) == ("auto", 3, 3)
    assert s.coach_dir == config_dir / "coach"
    s2 = Settings(root=root_dir, user_id="u", password="p")  # 기존 생성 코드 호환
    assert s2.ai_engine == "auto" and "ai_engine" not in repr(s2)


def test_ai_settings_parsed(root_dir, config_dir, fake_keyring):
    s = _load_ai(root_dir, config_dir, fake_keyring, SWEA_AI_ENGINE="Claude", SWEA_AI_WRONG_THRESHOLD="5", SWEA_REVIEW_DAYS="7")
    assert (s.ai_engine, s.ai_wrong_threshold, s.review_days) == ("claude", 5, 7)


@pytest.mark.parametrize("raw, expect", [("0", 1), ("99", 20), ("-3", 1)])
def test_ai_threshold_clamped(root_dir, config_dir, fake_keyring, caplog, raw, expect):
    with caplog.at_level(logging.WARNING, logger="swea_fetcher.config"):
        s = _load_ai(root_dir, config_dir, fake_keyring, SWEA_AI_WRONG_THRESHOLD=raw)
    assert s.ai_wrong_threshold == expect and "SWEA_AI_WRONG_THRESHOLD" in caplog.text


def test_review_days_clamped_and_invalid(root_dir, config_dir, fake_keyring, caplog):
    with caplog.at_level(logging.WARNING, logger="swea_fetcher.config"):
        assert _load_ai(root_dir, config_dir, fake_keyring, SWEA_REVIEW_DAYS="100").review_days == 30
        assert _load_ai(root_dir, config_dir, fake_keyring, SWEA_REVIEW_DAYS="abc").review_days == 3
    assert caplog.text.count("SWEA_REVIEW_DAYS") == 2


def test_ai_engine_invalid_falls_back_to_auto(root_dir, config_dir, fake_keyring, caplog):
    with caplog.at_level(logging.WARNING, logger="swea_fetcher.config"):
        assert _load_ai(root_dir, config_dir, fake_keyring, SWEA_AI_ENGINE="gemini").ai_engine == "auto"
    assert "SWEA_AI_ENGINE" in caplog.text


def test_ai_engine_both_allowed(root_dir, config_dir, fake_keyring):
    assert _load_ai(root_dir, config_dir, fake_keyring, SWEA_AI_ENGINE="Both").ai_engine == "both"


# =============================================================================
# M19: 성장 기록 (SWEA_GROWTH / SWEA_GROWTH_COMMENT)
# =============================================================================


def test_growth_settings_defaults_and_parsing(root_dir, config_dir, fake_keyring):
    s = _load_ai(root_dir, config_dir, fake_keyring)
    assert (s.growth, s.growth_comment) == (True, True)
    s = _load_ai(root_dir, config_dir, fake_keyring, SWEA_GROWTH="0", SWEA_GROWTH_COMMENT="off")
    assert (s.growth, s.growth_comment) == (False, False)
    s = _load_ai(root_dir, config_dir, fake_keyring, SWEA_GROWTH="TRUE", SWEA_GROWTH_COMMENT="no")
    assert (s.growth, s.growth_comment) == (True, False)
    s2 = Settings(root=root_dir, user_id="u", password="p")  # 기존 생성 코드 호환
    assert s2.growth is True and "growth=" not in repr(s2)


def test_growth_settings_invalid_falls_back_to_default(root_dir, config_dir, fake_keyring, caplog):
    with caplog.at_level(logging.WARNING, logger="swea_fetcher.config"):
        s = _load_ai(root_dir, config_dir, fake_keyring, SWEA_GROWTH="maybe", SWEA_GROWTH_COMMENT="2")
    assert (s.growth, s.growth_comment) == (True, True)
    assert "SWEA_GROWTH " in caplog.text and "SWEA_GROWTH_COMMENT" in caplog.text


# =============================================================================
# M24: 오늘의 추천 (SWEA_RECOMMEND / SWEA_RECOMMEND_AI)
# =============================================================================


def test_recommend_settings_defaults_and_parsing(root_dir, config_dir, fake_keyring):
    s = _load_ai(root_dir, config_dir, fake_keyring)
    assert (s.recommend, s.recommend_ai) == (True, True)
    s = _load_ai(root_dir, config_dir, fake_keyring, SWEA_RECOMMEND="0", SWEA_RECOMMEND_AI="off")
    assert (s.recommend, s.recommend_ai) == (False, False)
    s = _load_ai(root_dir, config_dir, fake_keyring, SWEA_RECOMMEND="true", SWEA_RECOMMEND_AI="no")
    assert (s.recommend, s.recommend_ai) == (True, False)
    s2 = Settings(root=root_dir, user_id="u", password="p")  # 기존 생성 코드 호환
    assert s2.recommend is True and s2.recommend_ai is True and "recommend=" not in repr(s2)


def test_recommend_settings_invalid_falls_back_to_default(root_dir, config_dir, fake_keyring, caplog):
    with caplog.at_level(logging.WARNING, logger="swea_fetcher.config"):
        s = _load_ai(root_dir, config_dir, fake_keyring, SWEA_RECOMMEND="maybe", SWEA_RECOMMEND_AI="2")
    assert (s.recommend, s.recommend_ai) == (True, True)
    assert "SWEA_RECOMMEND " in caplog.text and "SWEA_RECOMMEND_AI" in caplog.text
