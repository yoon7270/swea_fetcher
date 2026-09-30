"""AI 코치 엔진 (M17): 이 PC 에 설치된 Codex CLI / Claude Code CLI 를 비대화형으로 호출한다. subprocess 전담, Qt 없음.

- 프롬프트는 항상 stdin (UTF-8 바이트). argv 에는 고정 플래그와 임시 폴더 경로만 — Windows `.cmd` shim 이 개행·따옴표를 깨뜨린다.
- 작업 폴더는 요청마다 새로 만든 빈 임시 폴더 (끝나면 삭제). 읽기 전용 샌드박스 / 도구 차단 옵션과 함께 이중 방어.
- 옵션명은 2026-09 기준 지식(미검증)이다. 실행 직전 `--help` 로 지원 여부를 확인해 선택 옵션은 빼고,
  필수 옵션이 없으면 실행하지 않고 오류로 알린다. 실측 뒤 아래 상수를 확정한다 (docs/handoff-planner-m17-ai-coach.md 6.2).
- 프롬프트·코드·응답은 로그에 남기지 않는다. 실행한 argv(프롬프트 제외)만 DEBUG 로그·오류에 남긴다.
- 호출 전 사용자 동의는 GUI 책임 — 이 모듈은 호출되면 실행한다.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .errors import AiEngineMissing, AiRunFailed, AiTimeout

log = logging.getLogger("swea_fetcher.ai_engine")

ENGINE_NAMES = ("codex", "claude")  # auto 의 우선순위 순서
ENGINE_LABELS = {"codex": "Codex", "claude": "Claude Code"}
AI_TIMEOUT = 300.0  # 응답 대기 상한 (초)
VERSION_TIMEOUT = 10.0
HELP_TIMEOUT = 15.0
MAX_RESPONSE_CHARS = 200_000
STDERR_TAIL = 600
API_KEY_ENV = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")

# --- CLI 옵션 상수 (미검증: 설치 후 --help 로 확정) ---------------------------------------
CODEX_REQUIRED = ("--sandbox",)  # help 에 없으면 실행하지 않음
CODEX_OPTIONAL = ("--skip-git-repo-check", "--cd", "--color", "--output-last-message", "--ephemeral")
CLAUDE_REQUIRED = ("--print",)
CLAUDE_OPTIONAL = ("--output-format", "--disallowedTools", "--no-session-persistence")
CLAUDE_BLOCKED_TOOLS = "Bash,Edit,MultiEdit,Write,NotebookEdit,Read,Glob,Grep,WebFetch,WebSearch,Task,Agent"  # Task 는 구버전 이름, Agent 는 신버전
ANSWER_FILE = "answer.md"

INSTALL_HINTS = {  # 설치 안내 (공식 문서에서 명령/URL 확인 후 이 한 곳만 고친다)
    "codex": "Codex CLI: `npm install -g @openai/codex` 로 설치하고 터미널에서 `codex login` 으로 로그인하세요",
    "claude": "Claude Code CLI: `npm install -g @anthropic-ai/claude-code` 로 설치하고 터미널에서 `claude` 를 한 번 실행해 로그인하세요",
}
RESTART_HINT = "설치 후에는 이 앱을 다시 켜야 PATH 가 반영됩니다"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_AUTH_RE = re.compile(r"login|log in|auth|401|not logged|unauthori[sz]ed|credential", re.I)
_LIMIT_RE = re.compile(r"rate.?limit|quota|usage limit|too many requests|429|limit reached", re.I)

# 프로세스 안 --help 캐시: (경로, 서브커맨드) → 출력
_HELP_CACHE: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class EngineInfo:
    name: str  # "codex" | "claude"
    path: str = ""  # 실행 파일 경로 (없으면 "")
    version: str = ""  # detect() 에서만 채움
    ok: bool = True  # detect(): --version 이 성공했는가
    error: str = ""  # 없음/실패 사유

    @property
    def label(self) -> str:
        return ENGINE_LABELS.get(self.name, self.name)

    @property
    def found(self) -> bool:
        return bool(self.path)


@dataclass
class AiResult:
    text: str
    argv: list[str] = field(default_factory=list)  # 프롬프트 제외
    elapsed: float = 0.0
    cancelled: bool = False
    truncated: bool = False


# --- 테스트 대체 지점 -------------------------------------------------------------------


def _which(name: str) -> str | None:
    return shutil.which(name)  # Windows 는 PATHEXT 로 .cmd/.exe 를 찾는다


def _popen(argv: list[str], **kwargs) -> subprocess.Popen:
    """이 모듈의 모든 프로세스 기동은 여기를 지난다 (테스트가 대체·차단)."""
    return subprocess.Popen(argv, **kwargs)


def _run_quiet(argv: list[str]) -> None:
    subprocess.run(argv, capture_output=True, timeout=10, creationflags=_creation_flags())


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # 콘솔 창 깜빡임 방지 (checker 와 동일)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    return env


# --- 감지 / 해석 ------------------------------------------------------------------------


def api_key_env() -> list[str]:
    """설정된 API 키 환경변수 이름. 지우지 않고 알리기만 한다 (구독 대신 API 과금이 될 수 있음)."""
    return [k for k in API_KEY_ENV if os.environ.get(k)]


def install_hint(names: tuple[str, ...] = ENGINE_NAMES) -> str:
    return "\n".join(INSTALL_HINTS[n] for n in names) + f"\n{RESTART_HINT}"


def _decode(data: bytes | None) -> str:
    return _ANSI_RE.sub("", (data or b"").decode("utf-8", errors="replace").lstrip("﻿"))


def _capture(argv: list[str], timeout: float) -> tuple[int | None, str]:
    """짧은 보조 호출(--version/--help). 실패는 (None, "") 로 — 호출자가 판단."""
    try:
        proc = _popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=_env(), creationflags=_creation_flags())
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, _decode(out)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        return None, ""
    except (OSError, ValueError) as e:
        log.debug("보조 호출 실패 %s: %s", argv[:2], e)
        return None, ""


def detect() -> list[EngineInfo]:
    """설치된 엔진과 버전 (설정 페이지·연결 테스트용). node 기동이 느려 워커에서 호출한다."""
    found: list[EngineInfo] = []
    for name in ENGINE_NAMES:
        path = _which(name)
        if not path:
            found.append(EngineInfo(name, "", "", False, "설치되어 있지 않습니다"))
            continue
        rc, out = _capture([path, "--version"], VERSION_TIMEOUT)
        if rc == 0 and out.strip():
            found.append(EngineInfo(name, path, out.strip().splitlines()[0][:60], True))
        else:
            found.append(EngineInfo(name, path, "", False, "--version 실행에 실패했습니다"))
    return found


def resolve(pref: str = "auto") -> EngineInfo:
    """요청에 쓸 엔진 (경로 존재만 확인, 프로세스 기동 없음). 고정 엔진이 없으면 다른 엔진으로 폴백하지 않는다.

    동의받은 벤더가 아닌 곳으로 조용히 보내지 않기 위함이다.
    """
    pref = (pref or "auto").strip().lower()
    if pref in ENGINE_NAMES:
        path = _which(pref)
        if path:
            return EngineInfo(pref, path)
        other = [n for n in ENGINE_NAMES if n != pref][0]
        raise AiEngineMissing(
            f"{ENGINE_LABELS[pref]} CLI 를 찾지 못했습니다",
            hint=f"{INSTALL_HINTS[pref]}\n{RESTART_HINT}\n(설정에서 '자동'으로 바꾸면 {ENGINE_LABELS[other]} 를 사용합니다)",
        )
    for name in ENGINE_NAMES:
        path = _which(name)
        if path:
            return EngineInfo(name, path)
    raise AiEngineMissing("AI 엔진(Codex / Claude Code CLI)을 찾지 못했습니다", hint=install_hint())


# --- 명령 구성 --------------------------------------------------------------------------


def _help_text(path: str, sub: str = "") -> str:
    key = (path, sub)
    if key not in _HELP_CACHE:
        argv = [path, *([sub] if sub else []), "--help"]
        _HELP_CACHE[key] = _capture(argv, HELP_TIMEOUT)[1]
    return _HELP_CACHE[key]


def _supports(help_text: str, option: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(option)}(?![\w-])", help_text) is not None


def build_command(engine: EngineInfo, scratch: str) -> tuple[list[str], Path | None]:
    """(argv, 최종 답을 담을 파일 경로 또는 None). 프롬프트는 argv 에 넣지 않는다 (stdin).

    --help 출력을 읽어 선택 옵션은 지원할 때만 붙인다. help 를 읽지 못하면(빈 출력) 필수 옵션은 그대로 두고 선택 옵션만 뺀다.
    필수 옵션이 help 에 없으면 AiRunFailed (CLI 버전이 오래됨).
    """
    if engine.name == "codex":
        helptxt = _help_text(engine.path, "exec")
        _require(engine, helptxt, CODEX_REQUIRED)
        answer = Path(scratch) / ANSWER_FILE
        argv = [engine.path, "exec", "--sandbox", "read-only"]
        for opt, val in (
            ("--skip-git-repo-check", None),
            ("--cd", scratch),
            ("--color", "never"),
            ("--output-last-message", str(answer)),
            ("--ephemeral", None),
        ):
            if _supports(helptxt, opt):
                argv += [opt] if val is None else [opt, val]
        use_answer = _supports(helptxt, "--output-last-message")
        return [*argv, "-"], (answer if use_answer else None)
    if engine.name == "claude":
        helptxt = _help_text(engine.path)
        _require(engine, helptxt, CLAUDE_REQUIRED)
        argv = [engine.path, "-p"]
        if _supports(helptxt, "--output-format"):
            argv += ["--output-format", "text"]
        if _supports(helptxt, "--disallowedTools"):
            argv += ["--disallowedTools", CLAUDE_BLOCKED_TOOLS]
        if _supports(helptxt, "--no-session-persistence"):
            argv += ["--no-session-persistence"]
        return argv, None
    raise AiRunFailed(f"알 수 없는 엔진입니다: {engine.name}")


def _require(engine: EngineInfo, helptxt: str, options: tuple[str, ...]) -> None:
    if not helptxt.strip():
        return  # help 를 읽지 못함 — 실행해 보고 오류를 그대로 보여준다
    missing = [o for o in options if not _supports(helptxt, o)]
    if missing:
        raise AiRunFailed(
            f"{engine.label} CLI 가 필요한 옵션({', '.join(missing)})을 지원하지 않습니다",
            hint=f"{engine.label} CLI 버전이 오래됐을 수 있습니다. 업데이트한 뒤 앱을 다시 켜세요 (설정의 [연결 테스트] 로 확인)",
        )


# --- 실행 -------------------------------------------------------------------------------


def kill_tree(proc) -> None:
    """프로세스 트리 종료. `.cmd` shim 은 cmd.exe → node 구조라 proc.kill() 만으로는 node 가 남는다."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            _run_quiet(["taskkill", "/PID", str(proc.pid), "/T", "/F"])
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("트리 종료 실패: %s", e)
    try:
        proc.kill()
    except OSError:
        pass


def _failure_hint(engine: EngineInfo, text: str) -> str:
    login_cmd = "codex login" if engine.name == "codex" else "claude"
    if _AUTH_RE.search(text):
        return f"터미널에서 `{login_cmd}` 로 먼저 로그인하세요"
    if _LIMIT_RE.search(text):
        return "구독 사용량 한도일 수 있습니다. 잠시 뒤 다시 시도하세요"
    return "설정 페이지의 [연결 테스트] 로 엔진 상태를 확인하세요"


def _clean(text: str) -> tuple[str, bool]:
    text = _ANSI_RE.sub("", text.lstrip("﻿")).strip()
    if len(text) > MAX_RESPONSE_CHARS:
        return text[:MAX_RESPONSE_CHARS] + "\n\n(응답이 너무 길어 여기까지만 표시합니다)", True
    return text, False


def run(
    engine: EngineInfo,
    prompt: str,
    *,
    timeout: float = AI_TIMEOUT,
    on_start: Callable[[subprocess.Popen], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> AiResult:
    """프롬프트를 stdin 으로 넘겨 엔진을 1회 실행하고 응답 텍스트를 돌려준다.

    호출 전 사용자 동의 필수 (프롬프트에 코드·지문이 포함되어 외부 서비스로 전송됨).
    on_start(proc): 프로세스가 뜬 직후 호출 (GUI 가 취소 핸들로 쓴다). 취소는 예외 없이 cancelled=True.
    실패는 AiRunFailed / 타임아웃은 AiTimeout (프로세스 트리 종료 후).
    """
    scratch = tempfile.mkdtemp(prefix="swea-coach-")
    started = time.perf_counter()
    try:
        if is_cancelled is not None and is_cancelled():
            return AiResult("", [], 0.0, cancelled=True)
        argv, answer = build_command(engine, scratch)
        log.debug("AI 실행: %s", argv)
        kwargs: dict = dict(cwd=scratch, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env(), creationflags=_creation_flags())
        if sys.platform != "win32":
            kwargs["start_new_session"] = True  # 취소 시 killpg 로 자식까지
        try:
            proc = _popen(argv, **kwargs)
        except OSError as e:
            raise AiRunFailed(f"{engine.label} 를 실행하지 못했습니다: {e}", hint=INSTALL_HINTS[engine.name], argv=argv) from e
        if on_start is not None:
            on_start(proc)
        try:
            out_b, err_b = proc.communicate(prompt.encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            try:
                proc.communicate(timeout=5)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                pass
            raise AiTimeout(f"{engine.label} 응답이 {timeout:.0f}초를 넘어 중단했습니다", argv=argv) from None
        elapsed = time.perf_counter() - started
        if is_cancelled is not None and is_cancelled():
            return AiResult("", argv, elapsed, cancelled=True)
        out, err = _decode(out_b), _decode(err_b)
        if proc.returncode != 0:
            tail = (err.strip() or out.strip())[-STDERR_TAIL:]
            hint = _failure_hint(engine, f"{err}\n{out}")
            if tail:
                hint += f"\n\n{tail}"
            raise AiRunFailed(f"{engine.label} 실행 실패 (코드 {proc.returncode})", hint=hint, argv=argv, stderr=tail)
        raw = ""
        if answer is not None and answer.is_file():
            raw = _decode(answer.read_bytes())
        if not raw.strip():
            raw = out
        text, truncated = _clean(raw)
        if not text:
            tail = err.strip()[-STDERR_TAIL:]
            raise AiRunFailed(
                f"{engine.label} 가 빈 응답을 돌려줬습니다",
                hint="다시 시도하거나 설정의 [연결 테스트] 로 확인하세요" + (f"\n\n{tail}" if tail else ""),
                argv=argv,
                stderr=tail,
            )
        return AiResult(text, argv, elapsed, truncated=truncated)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
