"""도메인 예외. 모든 예외는 SweaFetchError 를 상속하고 exit_code(cli) 와 hint(조치 문구) 를 가진다.

exit code 규약 (project-plan 6절):
    0 성공 / 1 로그인·설정 실패 / 2 입력·파싱 실패 / 3 저장 충돌 / 4 첨부 없음 / 5 네트워크 / 6 검증 실패 / 7 git 실패 / 8 제출 실패·오답 / 9 AI 코치 (GUI 전용, CLI 미노출)
hint: 사용자가 다음에 할 일. cli 는 `→ {hint}` 로, GUI 는 배너에 표시한다.
     클래스 기본 문구를 두고, 발생 지점에서 hint= 로 덮어쓸 수 있다.
"""

from __future__ import annotations

from pathlib import Path

from . import platform_text

INPUT_EXAMPLES = (
    "25730",
    "https://swexpertacademy.com/main/common/contestProb/contestProbDown.do?downType=in&contestProbId=AZq-gSmq_RfHBISS",
    "https://swexpertacademy.com/main/code/problem/problemDetail.do?contestProbId=AZq-gSmq_RfHBISS",
    "AZq-gSmq_RfHBISS",
)


class SweaFetchError(Exception):
    """공통 부모. 하위 클래스가 exit_code 와 default_hint 를 지정한다."""

    exit_code: int = 1
    default_hint: str = ""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self._hint = hint

    @property
    def hint(self) -> str:
        return self._hint if self._hint is not None else self.default_hint

    @hint.setter
    def hint(self, value: str) -> None:
        self._hint = value


# --- 설정 / 로그인 (exit 1) -------------------------------------------------


class ConfigMissing(SweaFetchError):
    """.env 가 없거나 필수 키가 누락됨."""

    exit_code = 1
    default_hint = "`swea-fetch init` 을 먼저 실행하세요 (GUI 에서는 설정 페이지)"


# 같은 자격증명 자동 재시도 가드 (auth.login)
GUARD_MSG = "직전 로그인이 같은 ID/비밀번호로 실패해 자동 재시도를 막았습니다 (계정 잠금 방지)"
GUARD_HINT = (
    "ID/비밀번호를 고친 뒤 다시 시도하세요 (GUI: 설정 페이지에서 저장 후 로그인 확인 / CLI: swea-fetch init). "
    "고치지 않았다면 브라우저에서 로그인이 되는지 먼저 확인하세요"
)


class LoginFailed(SweaFetchError):
    """ID/PW 오류 등 로그인 실패. code 에 서버 message 코드를 보관."""

    exit_code = 1
    default_hint = (
        "SWEA_ID / 비밀번호를 확인하세요 (GUI: 설정 페이지, CLI: swea-fetch init 으로 재작성). "
        "SWEA 는 5회 연속 실패 시 계정이 잠깁니다"
    )

    def __init__(self, message: str, code: str | None = None, *, hint: str | None = None) -> None:
        super().__init__(message, hint=hint)
        self.code = code


class MfaRequired(LoginFailed):
    """서버 응답 message == "mfa" — 자동 로그인 불가."""

    default_hint = "계정에 2단계 인증이 켜져 있어 자동 로그인이 불가합니다. SWEA 계정 설정에서 MFA 를 해제해야 합니다"


class LoginLocked(LoginFailed):
    """도구 자체의 누적 실패 카운터 초과로 로그인 시도를 차단."""

    default_hint = f"브라우저에서 직접 로그인이 되는지 확인한 뒤 {platform_text.login_state_hint()} 을 삭제하세요"


class SessionExpired(SweaFetchError):
    """내부용. client 가 잡아 재로그인 1회 후 재시도한다."""

    exit_code = 1
    default_hint = "다시 실행하면 재로그인합니다"


# --- 입력 / 파싱 (exit 2) ---------------------------------------------------


class InvalidInput(SweaFetchError):
    """입력 문자열에서 contestProbId 를 추출하지 못함, 또는 번호를 찾지 못함."""

    exit_code = 2
    default_hint = "입력 예시 (문제 번호가 가장 쉽습니다):\n" + "\n".join(f"  {ex}" for ex in INPUT_EXAMPLES)


class ProblemNotFound(SweaFetchError):
    """SWEA 오류 페이지(::: Error :::) 또는 어떤 경로로도 문제를 못 찾음."""

    exit_code = 2
    default_hint = "contestProbId 가 맞는지, 해당 문제에 접근 권한(클럽 가입 등)이 있는지 확인하세요"


class ParseError(SweaFetchError):
    """번호/제목 추출 실패."""

    exit_code = 2
    default_hint = "--num 으로 번호를 직접 지정하거나, -v 로 실행한 결과를 제보해 주세요 (사이트 구조가 바뀌었을 수 있음)"


# --- 첨부 (exit 4) ----------------------------------------------------------


class AttachmentNotFound(SweaFetchError):
    """입력 또는 출력 첨부 링크가 없음. found 에 페이지에서 찾은 파일명 목록."""

    exit_code = 4

    def __init__(self, message: str, found: list[str] | None = None, *, hint: str | None = None) -> None:
        super().__init__(message, hint=hint)
        self.found: list[str] = list(found or [])

    @property
    def default_hint(self) -> str:  # type: ignore[override]
        found = ", ".join(self.found) if self.found else "없음"
        return (
            f"페이지에서 찾은 첨부: {found}\n"
            "샘플 입출력 첨부가 없는 문제입니다. '뼈대만'(--skeleton-only) 으로 다시 실행하면 "
            "폴더 + {번호}.py + 빈 input.txt 만 만듭니다 (샘플은 본문에서 직접 복사)"
        )


# --- 저장 (exit 3) ----------------------------------------------------------


class AlreadyExists(SweaFetchError):
    """저장 대상 파일이 이미 있음. existing 에 충돌 경로 목록."""

    exit_code = 3

    def __init__(self, message: str, existing: list[Path] | None = None, *, hint: str | None = None) -> None:
        super().__init__(message, hint=hint)
        self.existing: list[Path] = list(existing or [])

    @property
    def default_hint(self) -> str:  # type: ignore[override]
        files = "\n".join(f"  {p}" for p in self.existing)
        return f"이미 있는 파일:\n{files}\n덮어쓰려면 '덮어쓰기'(--force) 를 켜세요 ({{번호}}.py 는 유지됩니다)"


# --- 네트워크 (exit 5) ------------------------------------------------------


class NetworkError(SweaFetchError):
    """연결 실패, 타임아웃, 예상 밖 상태 코드, 허용되지 않은 도메인."""

    exit_code = 5
    default_hint = "네트워크 연결을 확인한 뒤 다시 시도하세요"


# --- 검증 (exit 6) ----------------------------------------------------------


class CheckFailed(SweaFetchError):
    """풀이 실행 결과가 기대 출력과 다름 (cli `check` 의 종료 코드용)."""

    exit_code = 6
    default_hint = "diff 의 changed/missing/extra 행을 확인하세요"


# --- git (exit 7) -----------------------------------------------------------


class GitError(SweaFetchError):
    """커밋/푸시 전제 조건 미충족 또는 git 명령 실패 (M7). 도구는 force push·pull 을 하지 않는다."""

    exit_code = 7
    default_hint = "README 'GitHub 연동' 절과 docs/troubleshooting.md 의 'git' 항목을 확인하세요"


# --- 제출 (exit 8) ----------------------------------------------------------


class SubmitError(SweaFetchError):
    """SWEA 제출 불가(컴파일 오류·허용되지 않는 구문·횟수 소진) 또는 cli `submit` 의 오답 종료 코드 (M8)."""

    exit_code = 8
    default_hint = "코드를 고친 뒤 다시 제출하세요. 제출은 문제당 횟수 제한이 있습니다"


# --- AI 코치 (exit 9, M17) --------------------------------------------------
# GUI 전용 기능이라 CLI 는 이 종료 코드를 내지 않는다 (규약상 예약만).


class AiError(SweaFetchError):
    """AI 코치 실패의 공통 부모. code 는 GUI 가 배너 종류를 고르는 데 쓴다 (missing | failed | timeout)."""

    exit_code = 9
    code = "failed"


class AiEngineMissing(AiError):
    """Codex / Claude Code CLI 를 PATH 에서 찾지 못함 (또는 고정한 엔진이 없음)."""

    code = "missing"
    default_hint = "AI 코치 엔진(Codex CLI 또는 Claude Code CLI)을 설치·로그인한 뒤 앱을 다시 켜세요"


class AiRunFailed(AiError):
    """CLI 실행 실패 (비 0 종료, 빈 응답, 필수 옵션 미지원 등). argv(프롬프트 제외)와 stderr 끝부분을 보관."""

    code = "failed"
    default_hint = "설정 페이지의 [연결 테스트] 로 엔진 상태를 확인하세요"

    def __init__(self, message: str, *, hint: str | None = None, argv: list[str] | None = None, stderr: str = "") -> None:
        super().__init__(message, hint=hint)
        self.argv: list[str] = list(argv or [])
        self.stderr = stderr


class AiTimeout(AiRunFailed):
    """AI 응답이 제한 시간(기본 5분)을 넘김. 프로세스 트리는 종료된 상태."""

    code = "timeout"
    default_hint = "잠시 뒤 다시 시도하세요. 반복되면 터미널에서 CLI 가 직접 응답하는지 확인하세요"
