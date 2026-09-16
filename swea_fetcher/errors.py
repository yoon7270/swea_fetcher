"""도메인 예외. 모든 예외는 SweaFetchError 를 상속하고 cli 가 쓸 exit_code 를 가진다.

exit code 규약 (project-plan 6절):
    0 성공 / 1 로그인·설정 실패 / 2 입력·파싱 실패 / 3 저장 충돌 / 4 첨부 없음 / 5 네트워크
"""

from __future__ import annotations

from pathlib import Path


class SweaFetchError(Exception):
    """공통 부모. 하위 클래스가 exit_code 를 지정한다."""

    exit_code: int = 1


# --- 설정 / 로그인 (exit 1) -------------------------------------------------


class ConfigMissing(SweaFetchError):
    """.env 가 없거나 필수 키가 누락됨."""

    exit_code = 1


class LoginFailed(SweaFetchError):
    """ID/PW 오류 등 로그인 실패. code 에 서버 message 코드를 보관."""

    exit_code = 1

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class MfaRequired(LoginFailed):
    """서버 응답 message == "mfa" — 자동 로그인 불가."""


class LoginLocked(LoginFailed):
    """도구 자체의 누적 실패 카운터 초과로 로그인 시도를 차단."""


class SessionExpired(SweaFetchError):
    """내부용. client 가 잡아 재로그인 1회 후 재시도한다."""

    exit_code = 1


# --- 입력 / 파싱 (exit 2) ---------------------------------------------------


class InvalidInput(SweaFetchError):
    """입력 문자열에서 contestProbId 를 추출하지 못함."""

    exit_code = 2


class ProblemNotFound(SweaFetchError):
    """SWEA 오류 페이지(::: Error :::) 또는 어떤 경로로도 문제를 못 찾음."""

    exit_code = 2


class ParseError(SweaFetchError):
    """번호/제목 추출 실패."""

    exit_code = 2


# --- 첨부 (exit 4) ----------------------------------------------------------


class AttachmentNotFound(SweaFetchError):
    """입력 또는 출력 첨부 링크가 없음. found 에 페이지에서 찾은 파일명 목록."""

    exit_code = 4

    def __init__(self, message: str, found: list[str] | None = None) -> None:
        super().__init__(message)
        self.found: list[str] = list(found or [])


# --- 저장 (exit 3) ----------------------------------------------------------


class AlreadyExists(SweaFetchError):
    """저장 대상 파일이 이미 있음. existing 에 충돌 경로 목록."""

    exit_code = 3

    def __init__(self, message: str, existing: list[Path] | None = None) -> None:
        super().__init__(message)
        self.existing: list[Path] = list(existing or [])


# --- 네트워크 (exit 5) ------------------------------------------------------


class NetworkError(SweaFetchError):
    """연결 실패, 타임아웃, 예상 밖 상태 코드, 허용되지 않은 도메인."""

    exit_code = 5
