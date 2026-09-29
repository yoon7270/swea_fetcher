"""HTML → ProblemInfo. 선택자는 상단 상수에 모아 둔다 (사이트 변경 시 여기만 수정).

페이지 종류 (docs/swea-page-notes.md):
- "solver": 문제 풀기 화면. h3.problem_title = "25730. [07] 항아리 게임"  ← 번호가 있는 유일한 페이지
- "club"  : Solving Club 상세. p.problem_title = "[07] 항아리 게임" (번호 없음)
- "detail": 일반 문제 상세 problemDetail.do. p.problem_title = "4014. [모의 SW 역량테스트] 활주로 건설" (M2 확인).
            번호를 못 읽으면 (None, "") — cli/GUI 가 --num 을 안내 (목록 위젯 폴백은 M5 에서 삭제)
첨부: div.down_area a[href*="contestProbDown.do"], href 의 downType=in|out 으로 구분
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Comment, Tag

from .errors import AttachmentNotFound, InvalidInput, ParseError
from .models import ImageRef, ProblemContent, ProblemInfo

log = logging.getLogger("swea_fetcher.parser")

BASE = "https://swexpertacademy.com"

# --- 선택자 / 패턴 상수 ---------------------------------------------------------
SEL_SOLVER_TITLE = "h3.problem_title"
SEL_CLUB_TITLE = "p.problem_title"  # detail 페이지도 같은 요소
SEL_ATTACH = 'div.down_area a[href*="contestProbDown.do"]'
SEL_LIMITS = "div.box3"  # 지문: 시간/메모리 제한 (M12)
SEL_BODY = "div.box4"  # 지문: 본문

TITLE_RE = re.compile(r"^(\d+)\.\s*(?:\[\d+\]\s*)?(.+)$")  # "25730. [07] 항아리 게임"
CLUB_TITLE_RE = re.compile(r"^\[(\d+)\]\s*(.+)$")  # "[07] 항아리 게임"
CONTEST_PROB_ID_RE = re.compile(r"[A-Za-z0-9_-]{16}")

PAGE_KINDS = ("solver", "club", "detail")

# --- 지문 sanitize 상수 (M12, 허용 목록 방식) ---
IMG_TOKEN_PREFIX = "swea-img:"
_DROP_TAGS = (
    "script", "style", "iframe", "object", "embed", "form", "input", "button", "select", "textarea",
    "link", "meta", "svg", "canvas", "video", "audio", "noscript",
)  # fmt: skip
_ALLOWED_TAGS = frozenset(
    "p br div span b strong i em u s sub sup ul ol li table thead tbody tfoot tr th td caption pre code "
    "blockquote hr h1 h2 h3 h4 h5 h6 img".split()
)
_KEEP_ATTRS = {"td": ("colspan", "rowspan"), "th": ("colspan", "rowspan")}
_DATA_IMG_RE = re.compile(r"^data:image/(png|jpeg|gif|webp|bmp);base64,(.*)$", re.IGNORECASE | re.DOTALL)
IMG_MAX_BYTES = 5 * 1024 * 1024  # 개당
IMG_MAX_TOTAL = 20 * 1024 * 1024  # 지문 합계
IMG_MAX_COUNT = 30
REMOTE_IMG_MAX = 10  # 다운로드가 필요한 원격 이미지 개수 상한 (fetch 지연 방지)
_ALLOWED_IMG_HOSTS = {"swexpertacademy.com", "www.swexpertacademy.com"}  # client.ALLOWED_HOSTS 와 동일


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
    """일반 문제 페이지. p.problem_title 의 "NNNN. 제목". 실패해도 예외 대신 (None, "") — cli 가 --num 을 요구한다."""
    el = soup.select_one(SEL_CLUB_TITLE)
    if el is not None:
        text = " ".join(_own_text(el).split())
        m = TITLE_RE.match(text)
        if m:
            return int(m.group(1)), m.group(2).strip()
    return None, ""


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


# --- 지문 추출 (M12) --------------------------------------------------------------


def _classify_image(src: str, alt: str, images: dict[str, ImageRef], total: list[int]) -> ImageRef:
    """img src 하나를 ImageRef 로 (네트워크 없음). total[0] = 지금까지 디코드한 바이트 합."""
    src = (src or "").strip()
    if not src:
        return ImageRef(alt=alt, error="이미지 주소 없음")
    if len(images) >= IMG_MAX_COUNT:
        return ImageRef(alt=alt, error=f"이미지 개수 상한({IMG_MAX_COUNT}) 초과")
    if src.lower().startswith("data:"):
        m = _DATA_IMG_RE.match(src)
        if not m:
            return ImageRef(alt=alt, error="지원하지 않는 이미지 형식")
        try:
            data = base64.b64decode(re.sub(r"\s+", "", m.group(2)), validate=True)
        except (binascii.Error, ValueError):
            return ImageRef(alt=alt, error="이미지 디코드 실패")
        if len(data) > IMG_MAX_BYTES:
            return ImageRef(alt=alt, error="이미지가 너무 큽니다 (5MB 초과)")
        if total[0] + len(data) > IMG_MAX_TOTAL:
            return ImageRef(alt=alt, error="이미지 합계 용량 상한 초과")
        total[0] += len(data)
        return ImageRef(data=data, alt=alt)
    scheme = urlparse(src).scheme.lower()
    if scheme not in ("", "http", "https"):
        return ImageRef(alt=alt, error="지원하지 않는 이미지 주소")
    url = urljoin(BASE, src)
    if (urlparse(url).hostname or "").lower() not in _ALLOWED_IMG_HOSTS:
        return ImageRef(alt=alt, error="외부 이미지 생략")  # 외부 서버로는 요청하지 않는다
    if sum(1 for r in images.values() if r.url) >= REMOTE_IMG_MAX:
        return ImageRef(alt=alt, error=f"원격 이미지 개수 상한({REMOTE_IMG_MAX}) 초과")
    return ImageRef(url=url, alt=alt)


def _sanitize(root: Tag, images: dict[str, ImageRef]) -> None:
    """root 내부를 허용 목록으로 정리한다 (제자리 수정). 이미지는 swea-img:N 토큰으로 치환·등록."""
    for el in root.find_all(_DROP_TAGS):
        el.decompose()
    for c in root.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for el in root.find_all(class_="hide"):
        if not getattr(el, "decomposed", False):
            el.decompose()

    total = [0]
    for el in list(root.find_all(True)):
        if el.name not in _ALLOWED_TAGS:  # a 포함: 텍스트만 남긴다
            el.unwrap()
            continue
        if el.name == "img":
            alt = " ".join(str(el.get("alt") or "").split())[:100]
            n = len(images)
            ref = _classify_image(str(el.get("src") or ""), alt or f"이미지 {n + 1}", images, total)
            token = f"{IMG_TOKEN_PREFIX}{n}"
            images[token] = ref
            el.attrs = {"src": token, "alt": ref.alt}
            continue
        keep = _KEEP_ATTRS.get(el.name, ())
        el.attrs = {k: v for k, v in el.attrs.items() if k in keep and str(v).isdigit()}

    # 빈 <p> 제거, 연속 <br> 3개 이상 → 2개
    for p in reversed(root.find_all("p")):
        if not p.get_text(strip=True) and p.find("img") is None:
            p.decompose()
    for br in root.find_all("br"):
        prev = br.previous_sibling
        while prev is not None and isinstance(prev, str) and not prev.strip():
            prev = prev.previous_sibling
        prev2 = getattr(prev, "previous_sibling", None)
        while prev2 is not None and isinstance(prev2, str) and not prev2.strip():
            prev2 = prev2.previous_sibling
        if getattr(prev, "name", None) == "br" and getattr(prev2, "name", None) == "br":
            br.decompose()


def parse_content(html: str) -> ProblemContent | None:
    """문제 페이지에서 지문(제한사항 box3 + 본문 box4)을 sanitize 해 꺼낸다. 순수 함수 (네트워크 없음).

    본문 영역이 없거나 정리 후 비면 None (예외 아님 — 저장 파이프라인은 지문 실패로 중단하지 않는다).
    """
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(SEL_BODY)
    if body is None:
        return None
    if len(soup.select(SEL_BODY)) > 1:
        log.warning("지문 영역(%s)이 여러 개입니다. 첫 번째만 사용", SEL_BODY)
    images: dict[str, ImageRef] = {}
    _sanitize(body, images)
    body_html = body.decode_contents().strip()

    limits_html = ""
    limits = soup.select_one(SEL_LIMITS)
    if limits is not None:
        # 이미지 토큰 번호가 본문과 겹치지 않도록 같은 images 를 공유한다
        _sanitize(limits, images)
        limits_html = limits.decode_contents().strip()

    if not body.get_text(strip=True) and not _tokens_in(body_html):
        return None
    return ProblemContent(limits_html=limits_html, body_html=body_html, images=images)


def _tokens_in(html: str) -> list[str]:
    return re.findall(rf'src="({re.escape(IMG_TOKEN_PREFIX)}\d+)"', html)
