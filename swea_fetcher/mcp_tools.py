"""MCP 도구 로직 (SDK 비의존). `mcp_server.py` 가 이 클래스의 메서드를 도구로 등록한다.

원칙 (docs/handoff-planner-m16-mcp.md):
- 자격증명은 인자로 받지 않는다. 설정은 호출마다 `config.load_settings()` 로 읽는다 (D2, D7).
- 저장 후 자동 push 는 MCP 경로에서 항상 끈다 (D3). 지문은 추출·반환하지 않는다 (D4).
- 모든 호출은 인스턴스 락 1개로 직렬화한다 (D5).
- 예외는 던지지 않고 `{"ok": False, "code", ...}` 구조로 돌려준다 (D6). 문자열은 redact 를 거친다.
- stdout 은 MCP 프레임 전용이므로 표준 출력에 직접 쓰지 않는다 (로그는 logging → stderr).
"""

from __future__ import annotations

import dataclasses
import logging
import re
import threading
import traceback
from pathlib import Path
from typing import Any, Callable

from . import __version__, auth, config, service
from .config import Settings
from .errors import (
    AlreadyExists,
    AttachmentNotFound,
    CheckFailed,
    ConfigMissing,
    GitError,
    InvalidInput,
    LoginFailed,
    LoginLocked,
    MfaRequired,
    NetworkError,
    ParseError,
    ProblemNotFound,
    SessionExpired,
    SubmitError,
    SweaFetchError,
)
from .errors import GUARD_MSG
from .service import FetchOptions

log = logging.getLogger("swea_fetcher.mcp")

MAX_PROBLEM_LEN = 300
MAX_TOPIC_LEN = 100
MAX_TOPICS = 200
RECENT_MIN, RECENT_MAX, RECENT_DEFAULT = 1, 50, 10
DEFAULT_LOCK_TIMEOUT = 120.0

INIT_HINT = (
    "사용자에게 터미널에서 `swea-fetch init` 을 실행하도록 안내하세요. 비밀번호를 대화에 적게 하지 마세요. "
    "init 후에는 서버 재시작 없이 다시 시도할 수 있습니다"
)
INIT_NEXT_STEP = "터미널에서 `swea-fetch init` 실행 (비밀번호는 AI 대화에 입력하지 마세요)"

# 쿠키 값 방어용 패턴 (예외 메시지에는 원래 들어가지 않는다)
_COOKIE_RES = (
    re.compile(r"(?i)\b(SESSION|JSESSIONID)=[^;\s]+"),
    re.compile(r"(?i)\bCookie:[^\r\n]*"),
)


# --- redact / 마스킹 ---------------------------------------------------------------


def mask_user_id(user_id: str) -> str:
    """앞 2글자 + *** (+ @도메인)."""
    user_id = user_id or ""
    local, at, domain = user_id.partition("@")
    return f"{local[:2]}***{at}{domain}"


def redact(text: str, settings: Settings | None) -> str:
    """비밀번호·전체 ID·쿠키 패턴을 가린다."""
    if not isinstance(text, str) or not text:
        return text
    if settings is not None:
        if settings.password:
            text = text.replace(settings.password, "***")
        if settings.user_id and len(settings.user_id) >= 3:
            text = text.replace(settings.user_id, mask_user_id(settings.user_id))
    for rx in _COOKIE_RES:
        text = rx.sub("***", text)
    return text


def _redact_obj(obj: Any, settings: Settings | None) -> Any:
    if isinstance(obj, str):
        return redact(obj, settings)
    if isinstance(obj, dict):
        return {k: _redact_obj(v, settings) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_redact_obj(v, settings) for v in obj]
    return obj


# --- 오류 매핑 ---------------------------------------------------------------------


def _err(code: str, message: str, hint: str = "", retryable: bool = False, status: str = "error", **extra: Any) -> dict:
    return {"ok": False, "status": status, "code": code, "message": message, "hint": hint, "retryable": retryable, **extra}


def map_error(exc: BaseException, settings: Settings | None = None) -> dict:
    """도메인 예외 -> 오류 봉투. 서브클래스(MfaRequired/LoginLocked)를 LoginFailed 보다 먼저 검사한다."""
    res = _map_error(exc)
    return _redact_obj(res, settings)


def _map_error(exc: BaseException) -> dict:
    if isinstance(exc, ConfigMissing):
        return _err("config_missing", str(exc), INIT_HINT)
    if isinstance(exc, MfaRequired):
        return _err("mfa_required", str(exc), f"{exc.hint} 재시도하지 마세요")
    if isinstance(exc, LoginLocked):
        return _err(
            "login_locked",
            str(exc),
            f"{exc.hint} 재시도하지 마세요. 사용자가 브라우저에서 로그인 확인 후 login_state.json 을 삭제해야 합니다",
        )
    if isinstance(exc, LoginFailed):
        if getattr(exc, "code", None) == "guard":
            return _err(
                "login_guard",
                GUARD_MSG,
                "같은 자격증명 재시도는 계정 잠금 위험으로 차단됨. 사용자가 `swea-fetch init` 으로 고친 뒤에만 다시 시도하세요",
            )
        return _err(
            "login_failed",
            str(exc),
            "재시도하지 말고 사용자에게 알리세요 (5회 실패 시 계정 잠금). 사용자가 `swea-fetch init` 으로 자격증명을 확인해야 합니다",
        )
    if isinstance(exc, SessionExpired):
        return _err("session_expired", str(exc), "잠시 후 한 번만 다시 시도하세요", retryable=True)
    if isinstance(exc, InvalidInput):
        return _err("invalid_input", str(exc), "문제 번호(숫자) 또는 문제 URL 과 주제 폴더 이름을 확인하세요")
    if isinstance(exc, ProblemNotFound):
        return _err("problem_not_found", str(exc), exc.hint)
    if isinstance(exc, ParseError):
        return _err(
            "parse_error",
            str(exc),
            "SWEA 페이지 구조가 바뀌었을 수 있습니다. 사용자가 저장소 이슈로 제보하도록 안내하세요",
        )
    if isinstance(exc, AttachmentNotFound):
        msg = "샘플 입출력 첨부가 없는 문제입니다"
        if exc.found:
            msg += f" (찾은 첨부: {', '.join(exc.found)})"
        return _err(
            "attachment_not_found",
            msg,
            "skeleton_only=true 로 다시 호출하면 폴더 + {번호}.py + 빈 input.txt 만 만듭니다",
        )
    if isinstance(exc, AlreadyExists):
        names = [Path(p).name for p in exc.existing]
        return _err(
            "already_exists",
            "이미 저장된 파일이 있어 덮어쓰지 않았습니다: " + (", ".join(names) if names else "(파일 없음)"),
            "사용자에게 덮어써도 되는지 확인한 뒤 force=true 로 다시 호출하세요. {번호}.py 는 유지됩니다",
            status="exists",
            existing=names,
        )
    if isinstance(exc, NetworkError):
        return _err("network_error", str(exc), exc.hint, retryable=True)
    if isinstance(exc, GitError):
        return _err("git_error", str(exc), exc.hint)
    if isinstance(exc, (CheckFailed, SubmitError)):
        return _err("unsupported", "MCP 에서 지원하지 않는 동작입니다", "")
    if isinstance(exc, SweaFetchError):
        return _err("error", str(exc), exc.hint)
    return _err("internal_error", "내부 오류: " + type(exc).__name__, "서버 로그(stderr)를 확인하세요")


# --- 입력 검증 ---------------------------------------------------------------------


def _clean_problem(problem: Any) -> str:
    if isinstance(problem, bool) or not isinstance(problem, (int, str)):
        raise InvalidInput("problem 은 문제 번호(숫자) 또는 문제 URL 문자열이어야 합니다")
    s = str(problem).strip()
    if not s:
        raise InvalidInput("문제 번호 또는 URL 을 입력하세요")
    if len(s) > MAX_PROBLEM_LEN:
        raise InvalidInput(f"problem 이 너무 깁니다 ({MAX_PROBLEM_LEN}자 이하)")
    return s


def _clean_topic(topic: Any) -> str:
    if not isinstance(topic, str):
        raise InvalidInput("topic 은 문자열이어야 합니다")
    s = topic.strip()
    if not s:
        raise InvalidInput("주제 폴더 이름을 입력하세요")
    if len(s) > MAX_TOPIC_LEN:
        raise InvalidInput(f"topic 이 너무 깁니다 ({MAX_TOPIC_LEN}자 이하)")
    return s


# --- 도구 --------------------------------------------------------------------------


class SweaTools:
    """도구 5개. 각 메서드는 항상 dict 를 반환한다 (예외 없음)."""

    def __init__(self, config_dir: Path | None = None, lock_timeout: float = DEFAULT_LOCK_TIMEOUT) -> None:
        self._config_dir = Path(config_dir) if config_dir is not None else None
        self._lock_timeout = lock_timeout
        self._lock = threading.Lock()

    # -- 공통 실행기: 락 + 설정 로드 + 오류 매핑 + redact --

    def _run(self, fn: Callable[[Settings], dict], *, allow_missing: bool = False) -> dict:
        if not self._lock.acquire(timeout=self._lock_timeout):
            return _err("busy", "다른 요청 처리 중입니다", "잠시 후 다시 시도하세요", retryable=True)
        settings: Settings | None = None
        try:
            try:
                settings = config.load_settings(self._config_dir)
            except ConfigMissing as e:
                if allow_missing:
                    return {"ok": True, "configured": False, "message": str(e), "next_step": INIT_NEXT_STEP}
                return map_error(e, None)
            return _redact_obj(fn(settings), settings)
        except Exception as e:  # noqa: BLE001 — 서버는 어떤 경우에도 예외 대신 결과를 돌려준다
            if not isinstance(e, SweaFetchError):
                # 트레이스백은 stderr 로그에만 (redact 적용)
                log.error("도구 실행 중 내부 오류: %s", redact(traceback.format_exc(), settings))
            return map_error(e, settings)
        finally:
            self._lock.release()

    # -- 4.1 status --

    def status(self, check_login: bool = False) -> dict:
        def body(s: Settings) -> dict:
            login_ok = None
            if check_login:
                auth.get_session(s)  # explicit 미사용: 실패 지문 가드 유지
                login_ok = True
            auto_on = bool(s.auto_push and "save" in s.auto_push_on)
            return {
                "ok": True,
                "configured": True,
                "version": __version__,
                "root": str(s.root),
                "root_exists": s.root.is_dir(),
                "user_id_masked": mask_user_id(s.user_id),
                "password_stored": True,
                "session_cached": service.is_session_cached(s),
                "login_ok": login_ok,
                "auto_sync_on_save": auto_on,
                "auto_sync_note": "MCP 로 저장할 때는 자동 동기화(push)가 항상 꺼집니다. GUI/CLI 로 동기화하세요",
            }

        return self._run(body, allow_missing=True)

    # -- 4.2 / 4.3 fetch, preview --

    def fetch(
        self,
        problem: int | str,
        topic: str,
        force: bool = False,
        skeleton_only: bool = False,
        refresh_index: bool = False,
    ) -> dict:
        return self._fetch(problem, topic, force, skeleton_only, refresh_index, dry_run=False)

    def preview(
        self,
        problem: int | str,
        topic: str,
        force: bool = False,
        skeleton_only: bool = False,
        refresh_index: bool = False,
    ) -> dict:
        return self._fetch(problem, topic, force, skeleton_only, refresh_index, dry_run=True)

    def _fetch(self, problem: Any, topic: Any, force: Any, skeleton_only: Any, refresh_index: Any, *, dry_run: bool) -> dict:
        try:
            target = _clean_problem(problem)
            topic_s = _clean_topic(topic)
        except InvalidInput as e:
            return map_error(e, None)
        opts = FetchOptions(
            force=bool(force),
            skeleton_only=bool(skeleton_only),
            dry_run=dry_run,
            refresh_index=bool(refresh_index),
            with_content=False,
            cache_content=False,
        )

        def body(s: Settings) -> dict:
            auto_was_on = bool(s.auto_push and "save" in s.auto_push_on)
            safe = dataclasses.replace(s, auto_push_on=frozenset(s.auto_push_on) - {"save"})  # D3
            oc = service.fetch_problem(safe, target, topic_s, opts, progress=None)
            if dry_run:
                pv = oc.preview or {}
                return {
                    "ok": True,
                    "status": "preview",
                    "num": oc.info.num,
                    "title": oc.info.title,
                    "topic": oc.topic,
                    "problem_dir": str(pv.get("problem_dir", "")),
                    "files": [{"name": f.name, "action": f.action, "source": f.source, "size": f.size} for f in pv.get("files", [])],
                    "needs_force": bool(pv.get("needs_force")),
                    "notices": list(oc.notices),
                }
            res = oc.result
            files = [{"name": Path(p).name, "action": "written"} for p in res.written]
            files += [{"name": Path(p).name, "action": "kept"} for p in res.skipped]
            out = {
                "ok": True,
                "status": "saved",
                "num": oc.info.num,
                "title": oc.info.title,
                "topic": oc.topic,
                "problem_dir": str(res.problem_dir),
                "files": files,
                "notices": list(oc.notices),
                "auto_sync": "disabled_in_mcp" if auto_was_on else "off",
            }
            if auto_was_on:
                out["auto_sync_message"] = "자동 동기화가 설정돼 있지만 MCP 저장에서는 push 하지 않았습니다. GUI/CLI 로 동기화하세요"
            return out

        return self._run(body)

    # -- 4.4 / 4.5 목록 --

    def topics(self) -> dict:
        def body(s: Settings) -> dict:
            items = service.list_topics(s)
            return {
                "ok": True,
                "root": str(s.root),
                "topics": items[:MAX_TOPICS],
                "count": len(items),
                **({"truncated": True} if len(items) > MAX_TOPICS else {}),
            }

        return self._run(body)

    def recent(self, limit: int = RECENT_DEFAULT) -> dict:
        try:
            n = int(limit)
        except (TypeError, ValueError):
            n = RECENT_DEFAULT
        n = max(RECENT_MIN, min(RECENT_MAX, n))

        def body(s: Settings) -> dict:
            items = service.list_recent(s, n)
            return {
                "ok": True,
                "items": [
                    {
                        "num": it.num,
                        "title": it.title,
                        "topic": it.topic,
                        "path": str(it.path),
                        "saved_at": it.saved_at.isoformat(),
                    }
                    for it in items
                ],
            }

        return self._run(body)
