"""설정 로드. 계정 정보는 프로젝트 밖 `~/.swea-fetch/.env` + Windows 자격 증명 관리자(keyring).

.env 키: SWEA_ROOT (풀이 저장소 경로), SWEA_ID, 선택: SWEA_INPUT_NAME, SWEA_OUTPUT_NAME.
비밀번호는 keyring 에 저장한다 (서비스 "swea-fetch", 사용자명 = SWEA_ID).
결정 순서: 환경변수 SWEA_PW → .env 의 SWEA_PW (경고, 이관 권장) → keyring → 없으면 ConfigMissing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from .errors import ConfigMissing

log = logging.getLogger("swea_fetcher.config")

CONFIG_DIR = Path.home() / ".swea-fetch"
ENV_FILE_NAME = ".env"
SESSION_FILE_NAME = "session.json"
LOGIN_STATE_FILE_NAME = "login_state.json"

REQUIRED_KEYS = ("SWEA_ROOT", "SWEA_ID")  # SWEA_PW 는 별도 검사 (keyring)
PASSWORD_KEY = "SWEA_PW"
KEYRING_SERVICE = "swea-fetch"


@dataclass(frozen=True)
class Settings:
    root: Path
    user_id: str
    password: str = field(repr=False)  # repr/로그 유출 방지
    input_name: str = "input.txt"
    output_name: str = "output.txt"
    config_dir: Path = CONFIG_DIR
    password_source: str = field(default="keyring", repr=False)  # "env" | "dotenv" | "keyring"

    @property
    def session_file(self) -> Path:
        return self.config_dir / SESSION_FILE_NAME

    @property
    def login_state_file(self) -> Path:
        return self.config_dir / LOGIN_STATE_FILE_NAME

    def __repr__(self) -> str:  # 비밀번호 마스킹
        return (
            f"Settings(root={str(self.root)!r}, user_id={self.user_id!r}, password='***', "
            f"input_name={self.input_name!r}, output_name={self.output_name!r}, "
            f"config_dir={str(self.config_dir)!r})"
        )


# --- keyring helper (cli 가 keyring 을 직접 import 하지 않도록 여기로 모은다) ------------


def _keyring():
    """keyring 모듈을 지연 import. 백엔드 문제는 ConfigMissing 으로 통일한다."""
    try:
        import keyring  # noqa: WPS433 — 지연 import
        import keyring.errors  # noqa: F401

        return keyring
    except ImportError as e:  # pragma: no cover — 의존성 누락
        raise ConfigMissing("keyring 패키지가 없습니다. `pip install -e .` 를 다시 실행하세요") from e


def _keyring_unavailable(e: Exception) -> ConfigMissing:
    return ConfigMissing(
        f"자격 증명 관리자를 쓸 수 없는 환경입니다 ({type(e).__name__}: {e}). "
        "환경변수 SWEA_PW 로 대체할 수 있습니다"
    )


def get_password(user_id: str) -> str | None:
    """keyring 에서 비밀번호를 읽는다. 없으면 None. 백엔드 오류는 ConfigMissing."""
    kr = _keyring()
    try:
        return kr.get_password(KEYRING_SERVICE, user_id)
    except kr.errors.KeyringError as e:
        raise _keyring_unavailable(e) from e


def save_password(user_id: str, password: str) -> None:
    kr = _keyring()
    try:
        kr.set_password(KEYRING_SERVICE, user_id, password)
    except kr.errors.KeyringError as e:
        raise _keyring_unavailable(e) from e


def delete_password(user_id: str) -> bool:
    """저장된 비밀번호를 지운다. 없었으면 False."""
    kr = _keyring()
    try:
        kr.delete_password(KEYRING_SERVICE, user_id)
        return True
    except kr.errors.PasswordDeleteError:
        return False
    except kr.errors.KeyringError as e:
        raise _keyring_unavailable(e) from e


# --- .env -----------------------------------------------------------------------------


def read_env_file(config_dir: Path | None = None) -> dict[str, str | None]:
    """`.env` 를 dict 로 읽는다 (없으면 빈 dict). os.environ 은 건드리지 않는다."""
    config_dir = Path(config_dir) if config_dir is not None else CONFIG_DIR
    env_file = config_dir / ENV_FILE_NAME
    return dotenv_values(env_file) if env_file.is_file() else {}


def strip_password_from_env_file(config_dir: Path | None = None) -> bool:
    """`.env` 에서 SWEA_PW 줄을 제거한다. 제거했으면 True."""
    config_dir = Path(config_dir) if config_dir is not None else CONFIG_DIR
    env_file = config_dir / ENV_FILE_NAME
    if not env_file.is_file():
        return False
    lines = env_file.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [ln for ln in lines if not ln.lstrip().startswith(f"{PASSWORD_KEY}=") and not ln.lstrip().startswith(f"export {PASSWORD_KEY}=")]
    if len(kept) == len(lines):
        return False
    env_file.write_text("".join(kept), encoding="utf-8")
    return True


# --- 로드 -----------------------------------------------------------------------------


def load_settings(config_dir: Path | None = None) -> Settings:
    """`config_dir/.env` + keyring 으로 Settings 를 만든다. 환경변수가 우선한다.

    필수 키 누락, SWEA_ROOT 가 디렉터리가 아님, 비밀번호를 어디서도 못 찾음 → ConfigMissing.
    """
    config_dir = Path(config_dir) if config_dir is not None else CONFIG_DIR
    env_file = config_dir / ENV_FILE_NAME
    file_values = read_env_file(config_dir)

    def get(key: str) -> str:
        return os.environ.get(key) or (file_values.get(key) or "")

    missing = [k for k in REQUIRED_KEYS if not get(k).strip()]
    if missing:
        if "SWEA_ID" in missing and not os.environ.get(PASSWORD_KEY) and not file_values.get(PASSWORD_KEY):
            missing.append(PASSWORD_KEY)  # ID 가 없으면 keyring 조회도 불가 → 비밀번호도 없는 것으로 안내
        raise ConfigMissing(
            f"설정이 없습니다: {', '.join(missing)}. `swea-fetch init` 을 실행하거나 {env_file} 를 작성하세요."
        )

    root = Path(get("SWEA_ROOT").strip()).expanduser()
    if not root.is_dir():
        raise ConfigMissing(f"SWEA_ROOT 가 존재하는 폴더가 아닙니다: {root}")
    user_id = get("SWEA_ID").strip()

    # 비밀번호: 환경변수 → .env(경고) → keyring
    password: str | None
    source: str
    if os.environ.get(PASSWORD_KEY):
        password, source = os.environ[PASSWORD_KEY], "env"
    elif file_values.get(PASSWORD_KEY):
        password, source = file_values[PASSWORD_KEY], "dotenv"
        log.warning(
            "평문 비밀번호가 %s 에 있습니다. `swea-fetch init --migrate` 를 실행하면 자격 증명 관리자로 옮깁니다",
            env_file,
        )
    else:
        password, source = get_password(user_id), "keyring"
    if not password:
        raise ConfigMissing(
            f"설정이 없습니다: {PASSWORD_KEY} (자격 증명 관리자 '{KEYRING_SERVICE}' 에 '{user_id}' 항목 없음). "
            "`swea-fetch init` 을 실행하세요"
        )

    return Settings(
        root=root,
        user_id=user_id,
        password=password,
        input_name=get("SWEA_INPUT_NAME").strip() or "input.txt",
        output_name=get("SWEA_OUTPUT_NAME").strip() or "output.txt",
        config_dir=config_dir,
        password_source=source,
    )
