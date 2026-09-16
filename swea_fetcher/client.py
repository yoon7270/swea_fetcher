"""SWEA HTTP 접근: 문제 페이지 GET/POST, 첨부 다운로드, 세션 만료 시 재로그인 1회.

- 모든 요청은 swexpertacademy.com 으로만 나간다 (도메인 화이트리스트)
- 응답 Content-Type 에 charset 이 없으므로 r.encoding = "utf-8" 강제
- 302 + Location 에 loginPage.do → SessionExpired → auth.login 1회 후 같은 요청 재시도
- 문제 페이지: (C) solvingProblem.do POST 우선 → (A) problemDetail.do GET 폴백
"""

from __future__ import annotations

import logging
import time
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests

from . import auth
from .config import Settings
from .errors import LoginFailed, NetworkError, ProblemNotFound, SessionExpired

log = logging.getLogger("swea_fetcher.client")

BASE = "https://swexpertacademy.com"
ALLOWED_HOSTS = {"swexpertacademy.com", "www.swexpertacademy.com"}
SOLVER_URL = f"{BASE}/main/solvingProblem/solvingProblem.do"
DETAIL_URL = f"{BASE}/main/code/problem/problemDetail.do"

TIMEOUT = 15
RETRY_DELAYS = (0.5, 1.5)  # 네트워크 예외에만 적용
ERROR_PAGE_TITLE = "::: Error :::"
SOLVER_MARKER = 'class="problem_title"'  # h3.problem_title 존재 여부의 가벼운 판별


# --- 내부 도우미 ----------------------------------------------------------------


def _check_host(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise NetworkError(f"허용되지 않은 도메인으로의 요청입니다: {url}")


def _is_login_redirect(r: requests.Response) -> bool:
    return r.status_code in (301, 302, 303, 307) and "loginPage.do" in r.headers.get("Location", "")


def _request(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    """도메인 검사 + 네트워크 예외 재시도 + utf-8 강제. 4xx/5xx 는 재시도하지 않는다."""
    _check_host(url)
    kwargs.setdefault("timeout", TIMEOUT)
    kwargs.setdefault("allow_redirects", False)
    last_exc: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            r = session.request(method, url, **kwargs)
            r.encoding = "utf-8"
            log.debug("%s %s -> %s", method, url, r.status_code)
            if _is_login_redirect(r):
                raise SessionExpired("세션이 만료되었습니다")
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            if attempt < len(RETRY_DELAYS):
                log.debug("네트워크 오류, %.1fs 후 재시도: %s", RETRY_DELAYS[attempt], e)
                time.sleep(RETRY_DELAYS[attempt])
        except requests.RequestException as e:
            raise NetworkError(f"요청 실패 ({method} {url}): {e}") from e
    raise NetworkError(f"네트워크 오류로 요청에 실패했습니다 ({method} {url}): {last_exc}")


def _with_relogin(session: requests.Session, settings: Settings, fn: Callable[[], object]):
    """fn 실행 중 SessionExpired 면 로그인 1회 후 같은 fn 을 한 번만 재시도."""
    try:
        return fn()
    except SessionExpired:
        log.info("세션 만료 감지 — 재로그인 후 재시도")
        session.cookies.clear()
        auth.login(session, settings)
        try:
            return fn()
        except SessionExpired as e:
            raise LoginFailed("재로그인 후에도 세션이 유효하지 않습니다") from e


def _is_error_page(html: str) -> bool:
    return ERROR_PAGE_TITLE in html[:4000]


# --- 공개 API -------------------------------------------------------------------


def fetch_problem_page(session: requests.Session, settings: Settings, contest_prob_id: str) -> tuple[str, str]:
    """문제 페이지 HTML 과 page_kind("solver" | "detail") 를 돌려준다.

    1. POST solvingProblem.do (categoryId 없이 시도 — M1 실측 과제)
    2. GET problemDetail.do
    둘 다 오류 페이지면 ProblemNotFound.
    """

    def _try_solver() -> str | None:
        r = _request(
            session,
            "POST",
            SOLVER_URL,
            data={"contestProbId": contest_prob_id, "categoryType": "BOX", "isPostMethod": "Y"},
            headers={"Referer": BASE + "/main/talk/solvingClub/problemView.do"},
        )
        if r.status_code == 200 and SOLVER_MARKER in r.text and not _is_error_page(r.text):
            return r.text
        log.debug("solver 페이지 사용 불가 (HTTP %s, error_page=%s)", r.status_code, _is_error_page(r.text))
        return None

    def _try_detail() -> str | None:
        r = _request(session, "GET", DETAIL_URL, params={"contestProbId": contest_prob_id})
        if r.status_code == 200 and not _is_error_page(r.text):
            return r.text
        return None

    html = _with_relogin(session, settings, _try_solver)
    if html:
        return html, "solver"
    html = _with_relogin(session, settings, _try_detail)
    if html:
        return html, "detail"
    raise ProblemNotFound(f"문제를 찾을 수 없습니다 (contestProbId={contest_prob_id}). ID 가 맞는지 확인하세요")


def download(session: requests.Session, url: str, settings: Settings | None = None) -> bytes:
    """첨부파일을 bytes 로 받는다. HTML 이 오면 로그인 페이지로 간주해 SessionExpired 처리.

    settings 가 주어지면 세션 만료 시 재로그인 1회 후 재시도한다.
    """
    abs_url = urljoin(BASE, url)

    def _get() -> bytes:
        r = _request(session, "GET", abs_url, headers={"Referer": SOLVER_URL})
        if r.status_code != 200:
            raise NetworkError(f"첨부 다운로드 실패: HTTP {r.status_code} ({abs_url})")
        ctype = r.headers.get("Content-Type", "").lower()
        if "text/html" in ctype or r.content.lstrip()[:1] == b"<":
            raise SessionExpired("첨부 대신 HTML 페이지가 왔습니다 (로그인 필요)")
        return r.content

    if settings is None:
        return _get()
    return _with_relogin(session, settings, _get)
