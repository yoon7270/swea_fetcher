"""SWEA 로그인과 세션 캐시.

M0 조사 결과(docs/swea-page-notes.md):
- POST /main/identity/anonymous/login.do  (form-urlencoded: id, pwd, lang, clientTimezone)
  → JSON {"success": bool, "message": str, "returnPath": str}
- 세션 쿠키 이름은 SESSION. 비로그인 시 userInformation.do 가 302 → loginPage.do
- 5회 실패 시 계정 잠금 → 도구는 프로세스당 1회 + 누적 3회에서 자동 중단
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

from .config import Settings
from .errors import LoginFailed, LoginLocked, MfaRequired, NetworkError

log = logging.getLogger("swea_fetcher.auth")

BASE = "https://swexpertacademy.com"
LOGIN_PAGE_URL = f"{BASE}/main/identity/anonymous/loginPage.do"
LOGIN_URL = f"{BASE}/main/identity/anonymous/login.do"
SESSION_CHECK_URL = f"{BASE}/main/userpage/userInformation.do"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
TIMEOUT = 15
MAX_CONSECUTIVE_FAILURES = 3  # SWEA 는 5회에서 잠금 → 여유를 두고 3회에서 중단

# 서버 message 코드 → 사용자 안내
_FAIL_MESSAGES = {
    "LoginIdFail": "존재하지 않는 ID 입니다",
    "LoginIdPwdFail": "비밀번호 오류 (SWEA 는 5회 실패 시 잠금 — 현재 도구 기록 {n}회)",
    "LoginPwdErrorCount": "계정이 잠겼습니다 — SWEA 관리자에게 문의하세요",
    "DormancyAccount": "휴면 계정입니다 — 브라우저에서 로그인해 복구한 뒤 다시 시도하세요",
}

# 프로세스당 1회 가드
_login_attempted = False


def _reset_process_guard() -> None:
    """테스트 전용. 프로세스당 1회 가드를 초기화한다."""
    global _login_attempted
    _login_attempted = False


# --- 세션 캐시 ---------------------------------------------------------------


def save_session(session: requests.Session, settings: Settings) -> None:
    """쿠키를 session.json 에 저장한다. 쿠키 값은 로그에 남기지 않는다."""
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    cookies = requests.utils.dict_from_cookiejar(session.cookies)
    settings.session_file.write_text(json.dumps(cookies), encoding="utf-8")
    log.debug("세션 저장: %s (%d cookies)", settings.session_file, len(cookies))


def load_session(session: requests.Session, settings: Settings) -> bool:
    """session.json 이 있으면 쿠키를 복원하고 True. 없거나 손상이면 False."""
    path = settings.session_file
    if not path.is_file():
        return False
    try:
        cookies = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cookies, dict):
            raise ValueError("not a dict")
    except (ValueError, OSError) as e:
        log.warning("session.json 을 읽을 수 없어 무시합니다: %s", e)
        return False
    session.cookies.update(requests.utils.cookiejar_from_dict(cookies))
    return bool(cookies)


def clear_session(settings: Settings) -> None:
    """session.json 삭제 (M3 logout 용)."""
    try:
        settings.session_file.unlink()
        log.info("저장된 세션을 삭제했습니다")
    except FileNotFoundError:
        pass


# --- 실패 카운터 -------------------------------------------------------------


def _read_failures(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("consecutive_failures", 0))
    except (ValueError, OSError, AttributeError):
        return 0


def _write_failures(path: Path, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"consecutive_failures": n}), encoding="utf-8")


# --- 로그인 -----------------------------------------------------------------


def is_logged_in(session: requests.Session) -> bool:
    """가벼운 페이지로 세션 유효성 확인. 200 → True, 302→loginPage → False."""
    try:
        r = session.get(SESSION_CHECK_URL, allow_redirects=False, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise NetworkError(f"세션 확인 요청 실패: {e}") from e
    if r.status_code == 200:
        return True
    if r.status_code in (301, 302, 303, 307) and "loginPage.do" in r.headers.get("Location", ""):
        return False
    raise NetworkError(f"세션 확인 중 예상 밖 응답: HTTP {r.status_code}")


def login(session: requests.Session, settings: Settings) -> None:
    """ID/PW 로 로그인한다. 성공 시 세션을 저장하고 실패 카운터를 리셋한다.

    LoginLocked  : 누적 실패 3회 (login_state.json)
    LoginFailed  : 이 프로세스에서 이미 시도함 / 서버가 실패 응답 / 응답 형식 이상
    MfaRequired  : 계정에 2단계 인증
    NetworkError : 연결 실패
    """
    global _login_attempted

    failures = _read_failures(settings.login_state_file)
    if failures >= MAX_CONSECUTIVE_FAILURES:
        raise LoginLocked(
            f"자동 로그인이 {failures}회 연속 실패해 중단했습니다 (SWEA 는 5회 실패 시 계정 잠금). "
            f"브라우저에서 로그인이 되는지 확인하고 .env 를 고친 뒤 "
            f"{settings.login_state_file} 을 삭제하세요"
        )
    if _login_attempted:
        raise LoginFailed("이 실행에서 이미 로그인을 시도했습니다")
    _login_attempted = True

    log.info("로그인 시도 (ID: %s)", settings.user_id)
    try:
        session.get(LOGIN_PAGE_URL, timeout=TIMEOUT)  # 초기 쿠키(SESSION 등) 발급
        r = session.post(
            LOGIN_URL,
            data={
                "id": settings.user_id,
                "pwd": settings.password,
                "lang": "ko_KR",
                "clientTimezone": "Asia/Seoul",
            },
            headers={
                "Referer": LOGIN_PAGE_URL,
                "X-Requested-With": "XMLHttpRequest",
            },
            allow_redirects=False,
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise NetworkError(f"로그인 요청 실패: {e}") from e

    if not r.text.strip():
        raise LoginFailed("로그인 응답이 비어 있습니다 — .env 의 SWEA_ID/SWEA_PW 가 비어 있는지 확인하세요")
    try:
        ret = r.json()
    except ValueError as e:
        raise LoginFailed(f"로그인 응답을 해석할 수 없습니다 (HTTP {r.status_code})") from e

    if ret.get("success") is True:
        code = str(ret.get("message", ""))
        if code == "mfa":
            raise MfaRequired(
                "계정에 2단계 인증이 걸려 있어 자동 로그인이 불가합니다. "
                "MFA 를 해제하거나 브라우저에서 로그인 후 수동 세션 주입 기능(M3)을 기다리세요",
                code=code,
            )
        _write_failures(settings.login_state_file, 0)
        save_session(session, settings)
        log.info("로그인 성공")
        return

    code = str(ret.get("message", "") or "unknown")
    failures += 1
    _write_failures(settings.login_state_file, failures)
    template = _FAIL_MESSAGES.get(code, f"로그인 실패: {code}")
    raise LoginFailed(template.format(n=failures), code=code)


def get_session(settings: Settings) -> requests.Session:
    """공통 헤더가 설정된 로그인 세션을 돌려준다. 캐시가 유효하면 재사용, 아니면 1회 로그인."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})

    if load_session(session, settings) and is_logged_in(session):
        log.info("저장된 세션 사용")
        return session

    session.cookies.clear()
    login(session, settings)
    return session
