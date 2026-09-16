"""문제 번호 → contestProbId 조회 (Solving Club 문제 상자 색인).

SWEA 문제 화면의 주소창 URL 에는 문제 ID 가 없다(POST 페이지). 대신 화면 상단에 늘 보이는
문제 번호(예: 25730)로 찾을 수 있도록, 사용자가 가입한 Solving Club 의 문제 상자를 훑어
번호 → ID 색인을 만든다. 한 번 본 상자는 ~/.swea-fetch/problem_index.json 에 캐시한다.

M2 실측(docs/swea-page-notes.md):
- POST /main/talk/solvingClub/myClubList.do      (JSON 본문 {})            → data.myClubList[].solveclubId, title
- POST /main/talk/solvingClub/problemBoxList.do  (JSON {solveclubId, pageIndex}) → data.problemBoxList[].probBoxId, title / endPage (최신순)
- GET  /main/talk/solvingClub/problemBoxDetail.do?solveclubId=&probBoxId=      → div.header-caption 마다
      input[name=checkContestProbId] (ID), span.week_num ("25730 ."), span.week_text a (제목)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .client import BASE, _request, _with_relogin
from .config import Settings
from .errors import InvalidInput, NetworkError

log = logging.getLogger("swea_fetcher.lookup")

MY_CLUB_LIST_URL = f"{BASE}/main/talk/solvingClub/myClubList.do"
BOX_LIST_URL = f"{BASE}/main/talk/solvingClub/problemBoxList.do"
BOX_DETAIL_URL = f"{BASE}/main/talk/solvingClub/problemBoxDetail.do"
INDEX_FILE_NAME = "problem_index.json"

# --- 선택자 상수 -------------------------------------------------------------
SEL_CAPTION = "div.header-caption"
SEL_CAPTION_ID = "input[name=checkContestProbId]"
SEL_CAPTION_NUM = "span.week_num"
SEL_CAPTION_TITLE = "span.week_text a"
NUM_RE = re.compile(r"^\s*(\d+)")

JSON_HEADERS = {"Content-Type": "application/json;charset=UTF-8", "X-Requested-With": "XMLHttpRequest"}
MAX_BOX_PAGES = 20  # 상자 목록 페이지 상한 (무한 루프 방지)


# --- 캐시 ----------------------------------------------------------------------


def _index_path(settings: Settings) -> Path:
    return settings.config_dir / INDEX_FILE_NAME


def load_index(settings: Settings) -> dict[str, dict]:
    """{"25730": {"id": ..., "title": ..., "club": ..., "box": ...}, ...}"""
    path = _index_path(settings)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError) as e:
        log.warning("problem_index.json 을 읽을 수 없어 무시합니다: %s", e)
        return {}


def save_index(settings: Settings, index: dict[str, dict]) -> None:
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    _index_path(settings).write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")


# --- SWEA 호출 -------------------------------------------------------------------


def _post_json(session: requests.Session, url: str, payload: dict) -> dict:
    r = _request(session, "POST", url, data=json.dumps(payload), headers=JSON_HEADERS)
    if r.status_code != 200:
        raise NetworkError(f"Solving Club API 오류: HTTP {r.status_code} ({url})")
    try:
        body = r.json()
    except ValueError as e:
        raise NetworkError(f"Solving Club API 응답이 JSON 이 아닙니다 ({url})") from e
    if not body.get("success"):
        raise NetworkError(f"Solving Club API 실패: {body.get('message')} ({url})")
    return body.get("data") or {}


def list_my_clubs(session: requests.Session) -> list[tuple[str, str]]:
    """[(solveclubId, title), ...]"""
    data = _post_json(session, MY_CLUB_LIST_URL, {})
    return [(c["solveclubId"], c.get("title") or "") for c in data.get("myClubList", []) if c.get("solveclubId")]


def list_boxes(session: requests.Session, club_id: str) -> list[tuple[str, str]]:
    """[(probBoxId, title), ...] 최신순. 페이지를 모두 합친다."""
    boxes: list[tuple[str, str]] = []
    page = 1
    while page <= MAX_BOX_PAGES:
        data = _post_json(session, BOX_LIST_URL, {"solveclubId": club_id, "pageIndex": page})
        boxes += [(b["probBoxId"], b.get("title") or "") for b in data.get("problemBoxList", []) if b.get("probBoxId")]
        if page >= int(data.get("endPage") or 1):
            break
        page += 1
    return boxes


def list_box_problems(session: requests.Session, club_id: str, box_id: str) -> list[tuple[int, str, str]]:
    """[(번호, contestProbId, 제목), ...]"""
    r = _request(session, "GET", BOX_DETAIL_URL, params={"solveclubId": club_id, "probBoxId": box_id})
    if r.status_code != 200:
        raise NetworkError(f"문제 상자 페이지 오류: HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "lxml")
    out: list[tuple[int, str, str]] = []
    for cap in soup.select(SEL_CAPTION):
        id_el = cap.select_one(SEL_CAPTION_ID)
        num_el = cap.select_one(SEL_CAPTION_NUM)
        if id_el is None or num_el is None:
            continue
        m = NUM_RE.match(num_el.get_text(strip=True))
        if not m:
            continue
        title_el = cap.select_one(SEL_CAPTION_TITLE)
        title = title_el.get_text(" ", strip=True) if title_el is not None else ""
        out.append((int(m.group(1)), id_el.get("value", ""), title))
    return out


# --- 공개 API -----------------------------------------------------------------------


def find_by_number(session: requests.Session, settings: Settings, num: int, refresh: bool = False) -> str:
    """문제 번호로 contestProbId 를 찾는다. 캐시 → 가입 클럽의 문제 상자(최신순) 순서로 탐색.

    찾으면 ID 를 돌려주고, 훑는 동안 본 문제는 모두 캐시에 넣는다. 못 찾으면 InvalidInput.
    """
    key = str(num)
    index = {} if refresh else load_index(settings)
    if key in index and index[key].get("id"):
        log.debug("색인 캐시에서 %s → %s", key, index[key]["id"])
        return index[key]["id"]

    def _scan() -> str | None:
        clubs = list_my_clubs(session)
        if not clubs:
            raise InvalidInput("가입한 Solving Club 이 없어 문제 번호로 찾을 수 없습니다. 첨부 링크 URL 로 지정하세요")
        for club_id, club_title in clubs:
            log.info("클럽 '%s' 의 문제 상자를 훑는 중", club_title)
            for box_id, box_title in list_boxes(session, club_id):
                problems = list_box_problems(session, club_id, box_id)
                for p_num, p_id, p_title in problems:
                    index[str(p_num)] = {"id": p_id, "title": p_title, "club": club_title, "box": box_title}
                save_index(settings, index)
                if key in index:
                    log.info("찾음: %s (%s / %s)", index[key]["title"], club_title, box_title)
                    return index[key]["id"]
        return None

    found = _with_relogin(session, settings, _scan)
    if found:
        return found
    raise InvalidInput(
        f"문제 번호 {num} 을(를) 가입한 Solving Club 의 문제 상자에서 찾지 못했습니다. "
        "번호를 확인하거나 첨부 링크 URL 로 지정하세요"
    )
