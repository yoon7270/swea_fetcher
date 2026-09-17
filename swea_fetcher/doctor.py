"""진단 정보 (M6 §3): `swea-fetch doctor` 와 GUI 설정 페이지 [진단 정보 복사] 가 같은 내용을 만든다.

비밀번호·쿠키·토큰·SWEA ID 는 절대 포함하지 않는다 (이슈에 그대로 붙이는 용도).
offline=True 면 네트워크를 쓰는 항목(로그인 상태·최신 버전)을 생략한다.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import requests

from . import __version__, auth, checker, config, lookup, service, update
from .config import Settings
from .errors import ConfigMissing, NetworkError

Row = tuple[str, str]


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _python_row(settings: Settings | None) -> str:
    try:
        py = checker.resolve_python(settings)
    except checker.PythonNotFound:
        return "찾지 못함 — Python 을 설치해 PATH 에 두거나 .env 에 SWEA_PYTHON 을 지정하세요"
    if settings is not None and settings.python and Path(settings.python) == Path(py):
        source = "설정 SWEA_PYTHON"
    elif os.environ.get("SWEA_PYTHON") and Path(os.environ["SWEA_PYTHON"]) == Path(py):
        source = "환경변수 SWEA_PYTHON"
    elif not _is_frozen() and Path(sys.executable) == Path(py):
        source = "실행 중인 인터프리터"
    else:
        source = "PATH"
    try:
        creation = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        out = subprocess.run([*checker._python_cmd(py), "--version"], capture_output=True, text=True, timeout=5, creationflags=creation)
        ver = (out.stdout or out.stderr).strip().replace("Python ", "") or "?"
    except (OSError, subprocess.SubprocessError):
        ver = "버전 확인 실패"
    return f"{ver}  {py}  (출처: {source})"


def _count_json_entries(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return len(data) if isinstance(data, dict) else None
    except (ValueError, OSError):
        return None


def _config_row(config_dir: Path) -> str:
    parts = [
        f".env {'있음' if (config_dir / config.ENV_FILE_NAME).is_file() else '없음'}",
        f"session.json {'있음' if (config_dir / config.SESSION_FILE_NAME).is_file() else '없음'}",
        f"login_state 실패 {auth._read_failures(config_dir / config.LOGIN_STATE_FILE_NAME)}회",
    ]
    index_file = config_dir / lookup.INDEX_FILE_NAME
    if index_file.is_file():
        n = _count_json_entries(index_file)
        parts.append(f"problem_index {n if n is not None else '?'}건")
    else:
        parts.append("problem_index 없음")
    return f"{config_dir}  ({' / '.join(parts)})"


def _root_row(config_dir: Path) -> str:
    raw = os.environ.get("SWEA_ROOT") or config.read_env_file(config_dir).get("SWEA_ROOT") or ""
    if not raw.strip():
        return "(설정 없음)"
    root = Path(raw.strip()).expanduser()
    if not root.is_dir():
        return f"{root}  (폴더 없음)"
    return f"{root}  (존재함, 주제 폴더 {len(service.list_topics(root))}개)"


def _settings_row(settings: Settings | None, err: ConfigMissing | None) -> str:
    if settings is not None:
        return f"정상 (비밀번호 출처: {settings.password_source})"
    msg = str(err) if err is not None else "알 수 없음"
    return f"불완전 — {msg.split(' (')[0].split('. `')[0]}"  # ID 등이 들어갈 수 있는 괄호 안은 버린다


def _login_row(settings: Settings | None) -> str:
    if settings is None:
        return "확인 불가 (설정 없음)"
    s = requests.Session()
    if not auth.load_session(s, settings):
        return "세션 없음"
    try:
        return "세션 유효" if auth.is_logged_in(s) else "세션 만료 (다음 실행 때 다시 로그인)"
    except NetworkError:
        return "확인 실패 (네트워크)"


def _keyring_row(settings: Settings | None, config_dir: Path) -> str:
    user_id = settings.user_id if settings is not None else (
        os.environ.get("SWEA_ID") or config.read_env_file(config_dir).get("SWEA_ID") or ""
    ).strip()
    if not user_id:
        return "확인 불가 (SWEA_ID 없음)"
    try:
        return "항목 있음" if config.get_password(user_id) else "항목 없음"
    except Exception as e:  # noqa: BLE001
        return f"확인 실패 ({type(e).__name__})"


def _latest_row(config_dir: Path) -> str:
    info = update.check(config_dir, force=True)
    suffix = "  [알림 꺼짐]" if update.is_disabled(config_dir) else ""
    if info is None:
        return "확인 실패 (네트워크 또는 저장소 비공개)" + suffix
    if info.is_newer:
        return f"{info.latest} 있음 → {info.url}" + suffix
    return f"{info.latest} (현재와 같음)" + suffix


def collect(config_dir: Path | None = None, offline: bool = False) -> list[Row]:
    """(항목, 값) 목록. 어떤 항목이 실패해도 나머지는 채운다."""
    config_dir = Path(config_dir) if config_dir is not None else config.CONFIG_DIR
    settings: Settings | None = None
    err: ConfigMissing | None = None
    try:
        settings = config.load_settings(config_dir)
    except ConfigMissing as e:
        err = e
    except Exception as e:  # noqa: BLE001
        err = ConfigMissing(f"{type(e).__name__}: {e}")

    rows: list[Row] = [
        ("swea-fetch", f"{__version__}  ({'exe' if _is_frozen() else 'source'})"),
        ("Python", _safe(_python_row, settings)),
        ("OS", f"{platform.system()} {platform.release()} {platform.version()}"),
        ("설정 폴더", _safe(_config_row, config_dir)),
        ("루트", _safe(_root_row, config_dir)),
        ("설정", _settings_row(settings, err)),
    ]
    if not offline:
        rows.append(("로그인 상태", _safe(_login_row, settings)))
    rows.append(("keyring", _safe(_keyring_row, settings, config_dir)))
    if not offline:
        rows.append(("최신 버전", _safe(_latest_row, config_dir)))
    return rows


def _safe(fn, *args) -> str:
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001
        return f"확인 실패 ({type(e).__name__}: {e})"


def format_report(rows: list[Row]) -> str:
    """첫 줄은 `swea-fetch 0.4.0 (exe)`, 나머지는 `항목: 값` (한글 폭 때문에 열 맞춤은 하지 않는다)."""
    return "\n".join(f"{k} {v}" if k == "swea-fetch" else f"{k}: {v}" for k, v in rows)


def report(config_dir: Path | None = None, offline: bool = False) -> str:
    return format_report(collect(config_dir, offline))
