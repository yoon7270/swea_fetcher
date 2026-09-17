"""SWEA 코드 제출 (M8): 풀이 화면의 onEditSubmit() 과 같은 순서 — compile.do → submit.do. 채점 결과는 submit 응답에 바로 온다.

docs/swea-page-notes.md '제출 API' 참조. 제출은 "제출 가능 횟수 1회 감소" 라 호출 전 반드시 사용자 확인.
- 소스 변환: SWEA 는 `import sys` 를 통째로 거부(exitValue NK) → `import sys` / `sys.stdin = open(...)` 줄을 지우고 보낸다.
  다른 `sys.` 사용이 남으면 제출하지 않고 SubmitError.
- 세션 쿠키·비밀번호는 로그에 남기지 않는다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from . import client
from .config import Settings
from .errors import SubmitError

log = logging.getLogger("swea_fetcher.submit")

COMPILE_URL = f"{client.BASE}/main/commonCompileRun/compile.do"
SUBMIT_URL = f"{client.BASE}/main/commonCompileRun/submit.do"
LANG_PYTHON = "py"
MAX_SOURCE_BYTES = 100 * 1024

_STRIP_LINE_RE = re.compile(r"^[ \t]*(import[ \t]+sys[ \t]*(#.*)?|sys\.stdin[ \t]*=[ \t]*open\(.*\)[ \t]*(#.*)?)$", re.M)
_SYS_USE_RE = re.compile(r"(?<![\w.])sys\.")

COMPILE_ERRORS = {
    "H": "컴파일 오류",
    "EB": "소스코드가 100KB 를 초과했습니다",
    "NS": "허용하지 않는 라이브러리가 사용되었습니다",
    "FI": "파일 입력 메소드가 사용되었습니다 (제출 코드에는 표준 입출력만)",
    "UP": "package 선언은 사용할 수 없습니다",
    "SC": "System call 함수는 사용할 수 없습니다",
    "NK": "허용하지 않는 키워드가 사용되었습니다 (SWEA 는 `import sys` 를 거부합니다)",
}
SUBMIT_FAILED = {
    "ES": "제출 횟수를 다 채웠습니다",
    "TU": "제출 시간이 종료되었습니다",
    "AP": "제출이 불가능합니다 (AP)",
}


@dataclass(frozen=True)
class SubmitContext:
    contest_prob_id: str
    category_id: str
    category_type: str
    title: str


@dataclass
class SubmitResult:
    passed: bool
    summary: str  # "Pass" / "오답: 10개 중 7개" / "제한시간 초과" …
    score: str | None = None
    test_cases: int | None = None
    corrected: int | None = None
    timed_out: bool = False
    run_error: str = ""
    execution_time: str | None = None
    raw: dict = field(default_factory=dict, repr=False)


# --- 소스 변환 -------------------------------------------------------------------------


def prepare_source(source: str) -> tuple[str, list[str]]:
    """제출용 소스. (변환된 소스, 안내 목록). sys 사용이 남으면 SubmitError."""
    notes: list[str] = []
    stripped = _STRIP_LINE_RE.sub("", source)
    if stripped != source:
        notes.append("`import sys` / `sys.stdin = open(...)` 줄을 빼고 제출합니다 (SWEA 가 거부하는 구문)")
    if _SYS_USE_RE.search(stripped):
        raise SubmitError(
            "제출 코드에 `sys.` 사용이 남아 있습니다 — SWEA 는 sys 모듈을 허용하지 않습니다",
            hint="sys.stdin.readline → input(), sys.setrecursionlimit 는 제거하고 다시 시도하세요",
        )
    if len(stripped.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise SubmitError("소스코드가 100KB 를 초과합니다")
    if not stripped.strip():
        raise SubmitError("제출할 소스코드가 비어 있습니다")
    return stripped, notes


# --- 요청 -------------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    return {"X-Requested-With": "XMLHttpRequest", "Referer": client.SOLVER_URL}


def get_context(
    session: requests.Session, settings: Settings, contest_prob_id: str, category_type: str = "CODE", category_id: str | None = None
) -> SubmitContext:
    """풀이 화면을 실제 경로(category)로 열고 hidden 값을 읽는다.

    공개/User Problem: ("CODE", contestProbId), Solving Club 상자: ("BOX", probBoxId) — lookup.find_category.
    category 가 틀리면 채점은 되지만 제출 기록이 문제의 '제출결과' 에 남지 않는다.
    """
    category_id = category_id if category_id is not None else contest_prob_id
    r = client._request(
        session, "POST", client.SOLVER_URL,
        data={"contestProbId": contest_prob_id, "categoryId": category_id, "categoryType": category_type, "isPostMethod": "Y"},
    )
    if r.status_code != 200 or client._is_error_page(r.text):
        raise SubmitError(f"풀이 화면을 열지 못했습니다 (HTTP {r.status_code}) — contestProbId={contest_prob_id}")
    soup = BeautifulSoup(r.text, "lxml")
    cat_id = soup.select_one('input[name="categoryId"]')
    cat_type = soup.select_one('input[name="categoryType"]')
    title = soup.select_one("h3.problem_title")
    return SubmitContext(
        contest_prob_id,
        (cat_id.get("value") if cat_id else "") or category_id,
        (cat_type.get("value") if cat_type else "") or category_type,
        title.get_text(" ", strip=True) if title else "",
    )


def _params(ctx: SubmitContext, source: str, lang: str) -> dict[str, str]:
    return {
        "source": source,
        "langType": lang,
        "probId": ctx.contest_prob_id,
        "categoryId": ctx.category_id,
        "categoryType": ctx.category_type,
        "useOptimize": "",
    }


def _post_json(session: requests.Session, url: str, params: dict[str, str], what: str) -> dict:
    r = client._request(session, "POST", url, data=params, headers=_headers(), timeout=90)
    if r.status_code != 200:
        raise SubmitError(f"{what} 요청 실패 (HTTP {r.status_code})")
    try:
        data = r.json()
    except ValueError as e:
        raise SubmitError(f"{what} 응답이 JSON 이 아닙니다 (로그인이 풀렸거나 사이트 구조 변경)") from e
    if data.get("result") != "success":
        raise SubmitError(f"{what} 서버 오류: result={data.get('result')!r}")
    return data


def compile_source(session: requests.Session, ctx: SubmitContext, source: str, lang: str = LANG_PYTHON) -> dict:
    """compile.do — 부작용 없음. exitValue != "0" 이면 SubmitError (사유 매핑)."""
    data = _post_json(session, COMPILE_URL, _params(ctx, source, lang), "컴파일")
    vo = data.get("vo") or {}
    code = str(vo.get("exitValue") or "")
    if code != "0":
        reason = COMPILE_ERRORS.get(code, f"컴파일 오류 ({code})")
        detail = _clean(vo.get("cmpError"))
        raise SubmitError(f"{reason}" + (f": {detail[:300]}" if detail else ""), hint="코드를 고친 뒤 다시 제출하세요")
    return data


def submit_source(session: requests.Session, ctx: SubmitContext, source: str, lang: str = LANG_PYTHON) -> SubmitResult:
    """submit.do — 제출 횟수 1회 소모. 채점 결과를 SubmitResult 로."""
    data = _post_json(session, SUBMIT_URL, _params(ctx, source, lang), "제출")
    failed = str(data.get("submitFailed") or "")
    if failed:
        raise SubmitError(SUBMIT_FAILED.get(failed, f"제출이 불가능합니다 ({failed})"))
    return parse_result(data)


def parse_result(data: dict) -> SubmitResult:
    """processSubmit() 의 판정을 그대로 옮김."""
    vo = data.get("vo") or {}
    run_value = str(vo.get("runValue") or "")
    score = str(vo.get("usrScore")) if vo.get("usrScore") not in (None, "") else None
    timed_out = bool(str(vo.get("timeOut") or "").strip())
    run_error = _clean(vo.get("runError"))
    tc = _int(vo.get("testCaseNo"))
    ok = _int(vo.get("correctedCases"))
    exec_time = str(vo.get("executionTime")) if vo.get("executionTime") not in (None, "") else None

    passed = ("Pass" in run_value) and not timed_out and not run_error and score not in ("0", "0.0", "0.00")
    if passed:
        summary = "Pass"
    else:
        if tc:
            summary = f"오답: {tc}개 테스트케이스 중 {ok or 0}개 통과"
        else:
            summary = f"오답: {score or '0'} / 100.0"
        if timed_out:
            summary += " · 제한시간 초과"
        if run_error:
            summary += " · 런타임 에러"
        grading = _clean(vo.get("gradingResult"))
        if grading:
            summary += f" · ({grading}) 일부 Output 을 해석할 수 없음"
    return SubmitResult(passed, summary, score, tc, ok, timed_out, run_error[:255], exec_time, data)


# --- 도우미 -----------------------------------------------------------------------------


def _clean(s) -> str:
    if not s:
        return ""
    text = str(s).replace("&nbsp;", " ").replace("<br>", "\n")
    return re.sub(r"<[^>]+>", "", text).strip()


def _int(v) -> int | None:
    try:
        return int(str(v)) if v not in (None, "") else None
    except ValueError:
        return None


def read_solution(problem_dir: Path, num: int) -> str:
    path = Path(problem_dir) / f"{num}.py"
    if not path.is_file():
        raise SubmitError(f"풀이 파일이 없습니다: {path}")
    return path.read_text(encoding="utf-8", errors="replace")
