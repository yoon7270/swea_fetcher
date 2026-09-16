"""HTML → ProblemInfo. 선택자는 상단 상수에 모아 둔다 (사이트 변경 시 여기만 수정).

페이지 종류 (docs/swea-page-notes.md):
- "solver": 문제 풀기 화면. h3.problem_title = "25730. [07] 항아리 게임"  ← 번호가 있는 유일한 페이지
- "club"  : Solving Club 상세. p.problem_title = "[07] 항아리 게임" (번호 없음)
- "detail": 일반 문제 상세 problemDetail.do. p.problem_title = "4014. [모의 SW 역량테스트] 활주로 건설" (M2 확인)
첨부: div.down_area a[href*="contestProbDown.do"], href 의 downType=in|out 으로 구분
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .errors import AttachmentNotFound, InvalidInput, ParseError
from .models import ProblemInfo

log = logging.getLogger("swea_fetcher.parser")

BASE = "https://swexpertacademy.com"

# --- 선택자 / 패턴 상수 ---------------------------------------------------------
SEL_SOLVER_TITLE = "h3.problem_title"
SEL_CLUB_TITLE = "p.problem_title"
SEL_DETAIL_NUM = "span.week_num"
SEL_DETAIL_TITLE = "span.week_text"
SEL_ATTACH = 'div.down_area a[href*="contestProbDown.do"]'

TITLE_RE = re.compile(r"^(\d+)\.\s*(?:\[\d+\]\s*)?(.+)$")  # "25730. [07] 항아리 게임"
CLUB_TITLE_RE = re.compile(r"^\[(\d+)\]\s*(.+)$")  # "[07] 항아리 게임"
CONTEST_PROB_ID_RE = re.compile(r"[A-Za-z0-9_-]{16}")

PAGE_KINDS = ("solver", "club", "detail")


# --- 입력 해석 ------------------------------------------------------------------


def extract_contest_prob_id(text: str) -> str:
    """URL 이든 ID 단독이든 contestProbId 를 뽑는다.

    ① URL 쿼리 contestProbId=  ② 전체가 16자 패턴  ③ 문자열 안의 16자 패턴 (유일할 때만)
    """
    if text is None:
        raise InvalidInput("입력이 비어 있습니다")
    s = text.strip()
    if not s:
        raise InvalidInput("입력이 비어 있습니다")

    # ① URL 쿼리 — 키가 명시돼 있으면 그 값만 인정한다 (_menuId 등 다른 16자 토큰으로 흘러가지 않도록)
    if "contestProbId" in s:
        try:
            qs = parse_qs(urlparse(s).query, keep_blank_values=True)
        except ValueError:
            qs = {}
        raw_vals = qs.get("contestProbId") or re.findall(r"contestProbId=([^&\s#]*)", s)
        vals = [v for v in raw_vals if CONTEST_PROB_ID_RE.fullmatch(v)]
        if vals:
            return vals[0]
        if raw_vals:
            raise InvalidInput(
                f"contestProbId 값이 올바르지 않습니다: {raw_vals[0]!r} (16자 영숫자여야 합니다. 링크가 잘려 복사되지 않았는지 확인하세요)"
            )

    # ② 전체가 ID
    if CONTEST_PROB_ID_RE.fullmatch(s):
        return s

    # ③ 문자열 안에 유일한 ID
    found = sorted(set(re.findall(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{16}(?![A-Za-z0-9_-])", s)))
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise InvalidInput(f"contestProbId 후보가 여러 개입니다: {', '.join(found)}")
    if re.search(r"solvingProblem\.do|problemView\.do", s):
        raise InvalidInput(
            "이 주소는 문제 화면의 주소창 값이라 문제 ID 가 들어 있지 않습니다 (POST 페이지). "
            "대신 화면 상단의 문제 번호(예: 25730)를 넣으세요"
        )
    raise InvalidInput(f"contestProbId 를 찾을 수 없습니다: {s[:80]!r}")


# --- 내부 도우미 ----------------------------------------------------------------


def _own_text(tag: Tag) -> str:
    """자식 태그(span.badge 등)를 제외한 태그 자신의 텍스트."""
    return " ".join(t.strip() for t in tag.find_all(string=True, recursive=False) if t.strip())


def _parse_solver_title(soup: BeautifulSoup) -> tuple[int, str]:
    el = soup.select_one(SEL_SOLVER_TITLE)
    if el is None:
        raise ParseError(f"제목 요소를 찾지 못했습니다 ({SEL_SOLVER_TITLE})")
    text = " ".join(el.get_text(" ", strip=True).split())
    m = TITLE_RE.match(text)
    if not m:
        raise ParseError(f"제목에서 문제 번호를 찾지 못했습니다: {text!r}")
    return int(m.group(1)), m.group(2).strip()


def _parse_club_title(soup: BeautifulSoup) -> str:
    el = soup.select_one(SEL_CLUB_TITLE)
    if el is None:
        raise ParseError(f"제목 요소를 찾지 못했습니다 ({SEL_CLUB_TITLE})")
    text = " ".join(_own_text(el).split())
    m = CLUB_TITLE_RE.match(text)
    return (m.group(2) if m else text).strip()


def _parse_detail_title(soup: BeautifulSoup) -> tuple[int | None, str]:
    """일반 문제 페이지. p.problem_title 의 "NNNN. 제목" 을 우선 쓰고, 없으면 목록형 week_num/week_text 폴백.
    실패해도 예외 대신 (None, "") — cli 가 --num 을 요구한다."""
    el = soup.select_one(SEL_CLUB_TITLE)  # detail 도 p.problem_title 을 쓴다
    if el is not None:
        text = " ".join(_own_text(el).split())
        m = TITLE_RE.match(text)
        if m:
            return int(m.group(1)), m.group(2).strip()
    num_el = soup.select_one(SEL_DETAIL_NUM)
    title_el = soup.select_one(SEL_DETAIL_TITLE)
    num: int | None = None
    if num_el is not None:
        m = re.match(r"^\s*(\d+)\.?", num_el.get_text(strip=True))
        if m:
            num = int(m.group(1))
    title = title_el.get_text(" ", strip=True) if title_el is not None else ""
    return num, title


def _attachment_filename(a: Tag) -> str:
    """<a> 안의 파일명. solver 페이지는 `<span>파일명</span><i><span class="hide">다운로드</span></i>`
    구조라 숨은 라벨을 제외하고 첫 번째 span(또는 자신의 텍스트)만 쓴다."""
    for span in a.find_all("span"):
        if "hide" in (span.get("class") or []):
            continue
        text = span.get_text(strip=True)
        if text:
            return text
    own = _own_text(a)
    if own:
        return own
    # 폴백: 숨김 라벨(.hide)을 제외한 나머지 텍스트. 없으면 빈 문자열
    visible = [t.strip() for t in a.find_all(string=True) if t.strip() and not t.find_parent(class_="hide")]
    return " ".join(visible)


def _parse_attachments(soup: BeautifulSoup) -> dict[str, tuple[str, str]]:
    """downType → (절대 URL, 파일명). 같은 타입이 여러 개면 첫 번째 + WARNING."""
    result: dict[str, tuple[str, str]] = {}
    for a in soup.select(SEL_ATTACH):
        href = a.get("href") or ""
        down_type = (parse_qs(urlparse(href).query).get("downType") or [""])[0].lower()
        if down_type not in ("in", "out"):
            continue
        filename = _attachment_filename(a)
        if down_type in result:
            log.warning("첨부 %s 가 여러 개입니다. 첫 번째(%s)만 사용", down_type, result[down_type][1])
            continue
        result[down_type] = (urljoin(BASE, href), filename)
    return result


# --- 공개 API -------------------------------------------------------------------


def parse(html: str, page_kind: str, contest_prob_id: str, require_attachments: bool = True) -> ProblemInfo:
    """페이지 HTML 을 ProblemInfo 로 바꾼다.

    require_attachments=True (기본): 첨부 in/out 중 하나라도 없으면 AttachmentNotFound.
    False: 첨부가 없어도 input_url/output_url=None 으로 돌려준다 (--skeleton-only 용).
    """
    if page_kind not in PAGE_KINDS:
        raise ParseError(f"알 수 없는 page_kind: {page_kind!r}")
    soup = BeautifulSoup(html, "lxml")

    num: int | None
    if page_kind == "solver":
        num, title = _parse_solver_title(soup)
    elif page_kind == "club":
        num, title = None, _parse_club_title(soup)
    else:
        num, title = _parse_detail_title(soup)

    attachments = _parse_attachments(soup)
    missing = [k for k in ("in", "out") if k not in attachments]
    if missing and require_attachments:
        found = [v[1] for v in attachments.values()]
        raise AttachmentNotFound(
            f"첨부 링크가 없습니다 (누락: {', '.join(missing)}; 발견: {found or '없음'})",
            found=found,
        )

    in_url, in_name = attachments.get("in", (None, None))
    out_url, out_name = attachments.get("out", (None, None))
    return ProblemInfo(
        contest_prob_id=contest_prob_id,
        num=num,
        title=title,
        input_url=in_url,
        output_url=out_url,
        input_filename=in_name,
        output_filename=out_name,
        page_kind=page_kind,
    )
