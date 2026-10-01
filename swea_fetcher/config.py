"""설정 로드. 계정 정보는 프로젝트 밖 `~/.swea-fetch/.env` + Windows 자격 증명 관리자(keyring).

.env 키: SWEA_ROOT (풀이 저장소 경로), SWEA_ID, 선택: SWEA_INPUT_NAME, SWEA_OUTPUT_NAME, SWEA_PYTHON(검증용 인터프리터), SWEA_EDITOR(auto|vscode|pycharm|default),
SWEA_AI_ENGINE(auto|codex|claude|both), SWEA_AI_WRONG_THRESHOLD(1~20), SWEA_REVIEW_DAYS(1~30) (M17 AI 코치),
SWEA_GROWTH(1|0, 성장 기록), SWEA_GROWTH_COMMENT(1|0, 주간 AI 코멘트 자동 생성) (M19), SWEA_SOLVED_SYNC(1|0|빈 값=자동, 잔디 기록을 풀이 저장소에 함께 저장) (M23).
비밀번호는 keyring 에 저장한다 (서비스 "swea-fetch", 사용자명 = SWEA_ID).
결정 순서: 환경변수 SWEA_PW → .env 의 SWEA_PW (경고, 이관 권장) → keyring → 없으면 ConfigMissing.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from .errors import ConfigMissing
from .opener import EDITOR_CHOICES

log = logging.getLogger("swea_fetcher.config")

CONFIG_DIR = Path.home() / ".swea-fetch"
ENV_FILE_NAME = ".env"
SESSION_FILE_NAME = "session.json"
LOGIN_STATE_FILE_NAME = "login_state.json"
CACHE_DIR_NAME = "cache"
COACH_DIR_NAME = "coach"

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
    python: str | None = None  # 검증에 쓸 Python 실행 파일 (SWEA_PYTHON). None 이면 자동 탐색
    commit_template: str = "solve: {num}. {title} ({topic})"  # SWEA_COMMIT_TEMPLATE (M7)
    auto_push_on_pass: bool = False  # SWEA_AUTO_PUSH=1 이고 시점에 pass 포함 (M7 하위호환, load_settings 에서 계산)
    auto_push: bool = False  # SWEA_AUTO_PUSH=1: 자동 동기화 켜짐 (M11)
    auto_push_scope: str = "problem"  # SWEA_AUTO_PUSH_SCOPE: "problem" | "root" (M11)
    auto_push_on: frozenset = field(default_factory=frozenset)  # SWEA_AUTO_PUSH_ON: {"pass","check","save","watch"} (M11)
    editor: str = "auto"  # SWEA_EDITOR: "auto" | "vscode" | "pycharm" | "default" (M13)
    password_source: str = field(default="keyring", repr=False)  # "env" | "dotenv" | "keyring"
    ai_engine: str = "auto"  # SWEA_AI_ENGINE: "auto" | "codex" | "claude" | "both" (M17, both=M18)
    ai_wrong_threshold: int = 3  # SWEA_AI_WRONG_THRESHOLD: 이 횟수 이상 오답이면 정답 풀이 제안 (M17)
    review_days: int = 3  # SWEA_REVIEW_DAYS: 정답 풀이를 본 뒤 복습 권유까지의 일수 (M17)
    growth: bool = True  # SWEA_GROWTH: 성장 기록 (AI 응답의 분류 태그·제출 결과 이벤트·주간 리포트) (M19)
    growth_comment: bool = True  # SWEA_GROWTH_COMMENT: 주간 AI 코멘트 자동 생성 (M19)
    solved_sync: bool | None = None  # SWEA_SOLVED_SYNC: 잔디 기록을 풀이 저장소에 함께 저장 (M23). None = 자동 (루트가 git 저장소+원격이면 켜짐)

    @property
    def session_file(self) -> Path:
        return self.config_dir / SESSION_FILE_NAME

    @property
    def login_state_file(self) -> Path:
        return self.config_dir / LOGIN_STATE_FILE_NAME

    @property
    def coach_dir(self) -> Path:
        """AI 코치 기록 위치 (M17). 루트 폴더 밖 config_dir 아래 — GitHub 로 올라가지 않는다."""
        return self.config_dir / COACH_DIR_NAME

    @property
    def cache_dir(self) -> Path:
        """앱 캐시 위치 (M12 지문 캐시 등). 루트 폴더 밖 config_dir 아래."""
        return self.config_dir / CACHE_DIR_NAME

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

        if getattr(sys, "frozen", False) and sys.platform == "win32":
            # PyInstaller exe 에서는 entry-point 기반 백엔드 탐색이 실패할 수 있어 명시 지정
            from keyring.backends import Windows as _win  # noqa: WPS433

            if not isinstance(keyring.get_keyring(), _win.WinVaultKeyring):
                keyring.set_keyring(_win.WinVaultKeyring())
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


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


AUTO_PUSH_SCOPES = ("problem", "root")
AUTO_PUSH_MOMENTS = ("pass", "check", "save", "watch")


def _editor_setting(raw: str) -> str:
    """SWEA_EDITOR 파싱 (M13). 허용값 외는 auto + WARNING."""
    value = (raw or "").strip().lower() or "auto"
    if value not in EDITOR_CHOICES:
        log.warning("SWEA_EDITOR 값이 올바르지 않습니다: %r — 'auto' 로 대체", raw)
        return "auto"
    return value


AI_ENGINE_CHOICES = ("auto", "codex", "claude", "both")  # both: GPT 와 Claude 동시 요청 (M18)
AI_WRONG_THRESHOLD_RANGE = (1, 20)
REVIEW_DAYS_RANGE = (1, 30)


def _ai_engine_setting(raw: str) -> str:
    """SWEA_AI_ENGINE 파싱 (M17). 허용값 외는 auto + WARNING."""
    value = (raw or "").strip().lower() or "auto"
    if value not in AI_ENGINE_CHOICES:
        log.warning("SWEA_AI_ENGINE 값이 올바르지 않습니다: %r — 'auto' 로 대체", raw)
        return "auto"
    return value


def _int_setting(key: str, raw: str, default: int, bounds: tuple[int, int]) -> int:
    """정수 설정 파싱 (M17). 숫자가 아니면 기본값 + WARNING, 범위 밖은 clamp + WARNING."""
    text = (raw or "").strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        log.warning("%s 값이 올바르지 않습니다: %r — %d 로 대체", key, raw, default)
        return default
    lo, hi = bounds
    if not lo <= value <= hi:
        log.warning("%s 값이 범위(%d~%d)를 벗어났습니다: %d — 조정", key, lo, hi, value)
        return max(lo, min(hi, value))
    return value


_FALSY = ("0", "false", "no", "off")


def _bool_setting(key: str, raw: str, default: bool) -> bool:
    """1/0 (true/false/yes/no/on/off) 설정 파싱 (M19). 비어 있으면 기본값, 알 수 없는 값은 기본값 + WARNING."""
    text = (raw or "").strip().lower()
    if not text:
        return default
    if text in ("1", "true", "yes", "on"):
        return True
    if text in _FALSY:
        return False
    log.warning("%s 값이 올바르지 않습니다: %r — %s 로 대체", key, raw, "1" if default else "0")
    return default


def _tristate_setting(key: str, raw: str) -> bool | None:
    """1/0 또는 비어 있음(=None, 자동) (M23). 알 수 없는 값은 자동 + WARNING."""
    text = (raw or "").strip().lower()
    if not text:
        return None
    if text in ("1", "true", "yes", "on"):
        return True
    if text in _FALSY:
        return False
    log.warning("%s 값이 올바르지 않습니다: %r — 자동으로 대체", key, raw)
    return None


def _auto_push_settings(raw_on: str, raw_scope: str, raw_moments: str) -> dict:
    """SWEA_AUTO_PUSH / _SCOPE / _ON 을 파싱 (M11). 잘못된 값은 기본값 + WARNING.

    하위호환: SWEA_AUTO_PUSH=1 만 있으면 scope=problem, on={pass} → auto_push_on_pass=True (M7 과 동일).
    """
    on = _truthy(raw_on)
    scope = (raw_scope or "").strip().lower() or "problem"
    if scope not in AUTO_PUSH_SCOPES:
        log.warning("SWEA_AUTO_PUSH_SCOPE 값이 올바르지 않습니다: %r — 'problem' 으로 대체", raw_scope)
        scope = "problem"
    moments = {m.strip().lower() for m in (raw_moments or "").split(",") if m.strip()}
    bad = moments - set(AUTO_PUSH_MOMENTS)
    if bad:
        log.warning("SWEA_AUTO_PUSH_ON 에 알 수 없는 시점: %s — 무시", ", ".join(sorted(bad)))
    moments &= set(AUTO_PUSH_MOMENTS)
    if not moments:
        moments = {"pass"}  # 비어 있으면 기본 pass
    return {
        "auto_push": on,
        "auto_push_scope": scope,
        "auto_push_on": frozenset(moments),
        "auto_push_on_pass": on and "pass" in moments,
    }


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
        python=get("SWEA_PYTHON").strip() or None,
        commit_template=get("SWEA_COMMIT_TEMPLATE").strip() or Settings.commit_template,
        password_source=source,
        editor=_editor_setting(get("SWEA_EDITOR")),
        ai_engine=_ai_engine_setting(get("SWEA_AI_ENGINE")),
        ai_wrong_threshold=_int_setting("SWEA_AI_WRONG_THRESHOLD", get("SWEA_AI_WRONG_THRESHOLD"), 3, AI_WRONG_THRESHOLD_RANGE),
        review_days=_int_setting("SWEA_REVIEW_DAYS", get("SWEA_REVIEW_DAYS"), 3, REVIEW_DAYS_RANGE),
        growth=_bool_setting("SWEA_GROWTH", get("SWEA_GROWTH"), True),
        growth_comment=_bool_setting("SWEA_GROWTH_COMMENT", get("SWEA_GROWTH_COMMENT"), True),
        solved_sync=_tristate_setting("SWEA_SOLVED_SYNC", get("SWEA_SOLVED_SYNC")),
        **_auto_push_settings(get("SWEA_AUTO_PUSH"), get("SWEA_AUTO_PUSH_SCOPE"), get("SWEA_AUTO_PUSH_ON")),
    )
