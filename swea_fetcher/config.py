"""설정 로드. 계정 정보는 프로젝트 밖 `~/.swea-fetch/.env` 에서만 읽는다.

환경변수 키: SWEA_ROOT (풀이 저장소 경로), SWEA_ID, SWEA_PW,
선택: SWEA_INPUT_NAME, SWEA_OUTPUT_NAME.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from .errors import ConfigMissing

CONFIG_DIR = Path.home() / ".swea-fetch"
ENV_FILE_NAME = ".env"
SESSION_FILE_NAME = "session.json"
LOGIN_STATE_FILE_NAME = "login_state.json"

REQUIRED_KEYS = ("SWEA_ROOT", "SWEA_ID", "SWEA_PW")


@dataclass(frozen=True)
class Settings:
    root: Path
    user_id: str
    password: str = field(repr=False)  # repr/로그 유출 방지
    input_name: str = "input.txt"
    output_name: str = "output.txt"
    config_dir: Path = CONFIG_DIR

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


def load_settings(config_dir: Path | None = None) -> Settings:
    """`config_dir/.env` 를 읽어 Settings 를 만든다. 이미 있는 환경변수가 우선한다.

    필수 키 누락 또는 SWEA_ROOT 가 디렉터리가 아니면 ConfigMissing.
    """
    config_dir = Path(config_dir) if config_dir is not None else CONFIG_DIR
    env_file = config_dir / ENV_FILE_NAME
    file_values: dict[str, str | None] = dotenv_values(env_file) if env_file.is_file() else {}

    def get(key: str) -> str:
        """환경변수 우선, 없으면 .env 값. os.environ 은 건드리지 않는다."""
        return os.environ.get(key) or (file_values.get(key) or "")

    missing = [k for k in REQUIRED_KEYS if not get(k).strip()]
    if missing:
        raise ConfigMissing(
            f"설정이 없습니다: {', '.join(missing)}. "
            f"{env_file} 파일에 SWEA_ROOT, SWEA_ID, SWEA_PW 를 작성하세요."
        )

    root = Path(get("SWEA_ROOT").strip()).expanduser()
    if not root.is_dir():
        raise ConfigMissing(f"SWEA_ROOT 가 존재하는 폴더가 아닙니다: {root}")

    return Settings(
        root=root,
        user_id=get("SWEA_ID").strip(),
        password=get("SWEA_PW"),
        input_name=get("SWEA_INPUT_NAME").strip() or "input.txt",
        output_name=get("SWEA_OUTPUT_NAME").strip() or "output.txt",
        config_dir=config_dir,
    )
