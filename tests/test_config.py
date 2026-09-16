"""config.load_settings / Settings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from swea_fetcher.config import Settings, load_settings
from swea_fetcher.errors import ConfigMissing
from tests.conftest import DUMMY_ID, DUMMY_PW


def _write_env(config_dir: Path, **kv: str) -> Path:
    env_file = config_dir / ".env"
    env_file.write_text("".join(f"{k}={v}\n" for k, v in kv.items()), encoding="utf-8")
    return env_file


# --- 정상 ------------------------------------------------------------------------


def test_loads_from_env_file(root_dir: Path, config_dir: Path):
    _write_env(config_dir, SWEA_ROOT=str(root_dir), SWEA_ID=DUMMY_ID, SWEA_PW=DUMMY_PW)
    s = load_settings(config_dir)
    assert s.root == root_dir
    assert s.user_id == DUMMY_ID
    assert s.password == DUMMY_PW
    assert s.input_name == "input.txt"
    assert s.output_name == "output.txt"
    assert s.config_dir == config_dir
    assert s.session_file == config_dir / "session.json"
    assert s.login_state_file == config_dir / "login_state.json"


def test_loads_from_process_env_without_env_file(root_dir: Path, config_dir: Path, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(root_dir))
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    s = load_settings(config_dir)
    assert s.root == root_dir and s.user_id == DUMMY_ID


def test_process_env_takes_precedence_over_env_file(root_dir: Path, config_dir: Path, monkeypatch):
    _write_env(config_dir, SWEA_ROOT=str(root_dir), SWEA_ID="from_file", SWEA_PW="pw_file")
    monkeypatch.setenv("SWEA_ID", "from_env")
    s = load_settings(config_dir)
    assert s.user_id == "from_env"
    assert s.password == "pw_file"  # 파일에서만 온 값은 그대로


def test_optional_file_names(root_dir: Path, config_dir: Path):
    _write_env(
        config_dir,
        SWEA_ROOT=str(root_dir),
        SWEA_ID=DUMMY_ID,
        SWEA_PW=DUMMY_PW,
        SWEA_INPUT_NAME="in.txt",
        SWEA_OUTPUT_NAME="out.txt",
    )
    s = load_settings(config_dir)
    assert (s.input_name, s.output_name) == ("in.txt", "out.txt")


def test_blank_optional_names_fall_back_to_default(root_dir: Path, config_dir: Path, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(root_dir))
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    monkeypatch.setenv("SWEA_INPUT_NAME", "   ")
    s = load_settings(config_dir)
    assert s.input_name == "input.txt"


def test_root_and_id_are_stripped_but_password_is_not(root_dir: Path, config_dir: Path, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", f"  {root_dir}  ")
    monkeypatch.setenv("SWEA_ID", f" {DUMMY_ID} ")
    monkeypatch.setenv("SWEA_PW", " pw ")
    s = load_settings(config_dir)
    assert s.root == root_dir
    assert s.user_id == DUMMY_ID
    assert s.password == " pw "


def test_root_tilde_is_expanded(config_dir: Path, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", "~")
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    s = load_settings(config_dir)
    assert s.root == Path.home()


# --- 에러 ------------------------------------------------------------------------


def test_missing_env_file_and_env_raises_config_missing(config_dir: Path):
    with pytest.raises(ConfigMissing) as ei:
        load_settings(config_dir)
    msg = str(ei.value)
    assert "SWEA_ROOT" in msg and "SWEA_ID" in msg and "SWEA_PW" in msg
    assert str(config_dir / ".env") in msg


def test_partial_keys_lists_only_missing(root_dir: Path, config_dir: Path, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(root_dir))
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    with pytest.raises(ConfigMissing) as ei:
        load_settings(config_dir)
    assert "SWEA_PW" in str(ei.value)
    assert "SWEA_ID" not in str(ei.value).split("설정이 없습니다:")[1].split(".")[0]


def test_whitespace_only_value_counts_as_missing(root_dir: Path, config_dir: Path, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(root_dir))
    monkeypatch.setenv("SWEA_ID", "   ")
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    with pytest.raises(ConfigMissing):
        load_settings(config_dir)


def test_root_not_a_directory(tmp_path: Path, config_dir: Path, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(tmp_path / "nope"))
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    with pytest.raises(ConfigMissing) as ei:
        load_settings(config_dir)
    assert "SWEA_ROOT" in str(ei.value)


def test_root_is_a_file_not_dir(tmp_path: Path, config_dir: Path, monkeypatch):
    f = tmp_path / "file.txt"
    f.write_text("x")
    monkeypatch.setenv("SWEA_ROOT", str(f))
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    with pytest.raises(ConfigMissing):
        load_settings(config_dir)


# --- 비밀번호 유출 방지 ------------------------------------------------------------


def test_repr_and_str_mask_password(settings: Settings):
    for rendered in (repr(settings), str(settings)):
        assert DUMMY_PW not in rendered
        assert "***" in rendered
        assert DUMMY_ID in rendered


def test_settings_is_frozen(settings: Settings):
    with pytest.raises(Exception):
        settings.user_id = "x"  # type: ignore[misc]


def test_load_settings_does_not_leak_password_in_exception(root_dir: Path, config_dir: Path, monkeypatch):
    monkeypatch.setenv("SWEA_ROOT", str(root_dir / "missing"))
    monkeypatch.setenv("SWEA_ID", DUMMY_ID)
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    with pytest.raises(ConfigMissing) as ei:
        load_settings(config_dir)
    assert DUMMY_PW not in str(ei.value)
