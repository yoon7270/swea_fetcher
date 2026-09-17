"""새 버전 확인 (M6 §4): GitHub Releases API 를 하루 1회만 조회하고 결과를 config_dir/update_check.json 에 캐시한다.

- 인증 없음, 타임아웃 3초, 실패는 조용히 무시 (None)
- 끄기: CLI `--no-update-check`(그 실행만), 환경변수 SWEA_NO_UPDATE_CHECK=1, 설정 페이지 체크박스(캐시 파일의 "disabled")
- 저장소가 private 이면 API 가 401/404 → 알림 없음 (public 전환 후 자연히 동작)
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import requests

from . import __version__

log = logging.getLogger("swea_fetcher.update")

REPO = "yoon7270/swea_fetcher"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
LATEST_PAGE = f"{RELEASES_URL}/latest"  # 302 → /releases/tag/vX.Y.Z (API 속도 제한 없음)
CACHE_FILE_NAME = "update_check.json"
CHECK_INTERVAL = timedelta(hours=24)
TIMEOUT = 3.0
DISABLE_ENV = "SWEA_NO_UPDATE_CHECK"
USER_AGENT = f"swea-fetch/{__version__}"


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str
    url: str

    @property
    def is_newer(self) -> bool:
        return parse_version(self.latest) > parse_version(self.current)


def parse_version(s: str | None) -> tuple[int, ...]:
    """'v0.4.1' → (0, 4, 1). 숫자가 없으면 (0,)."""
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums) or (0,)


# --- 캐시 ---------------------------------------------------------------------------


def cache_path(config_dir: Path) -> Path:
    return Path(config_dir) / CACHE_FILE_NAME


def read_cache(config_dir: Path) -> dict:
    path = cache_path(config_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def write_cache(config_dir: Path, **fields) -> None:
    """기존 내용에 fields 를 합쳐 쓴다. 쓰기 실패는 무시."""
    data = read_cache(config_dir)
    data.update(fields)
    try:
        Path(config_dir).mkdir(parents=True, exist_ok=True)
        cache_path(config_dir).write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    except OSError as e:
        log.debug("update_check.json 쓰기 실패: %s", e)


def is_disabled(config_dir: Path) -> bool:
    if os.environ.get(DISABLE_ENV, "").strip() not in ("", "0", "false", "no"):
        return True
    return bool(read_cache(config_dir).get("disabled", False))


def set_disabled(config_dir: Path, disabled: bool) -> None:
    write_cache(config_dir, disabled=bool(disabled))


# --- 조회 ---------------------------------------------------------------------------


def fetch_latest(timeout: float = TIMEOUT, session: requests.Session | None = None) -> tuple[str, str]:
    """(최신 버전 문자열, Release 페이지 URL). 실패 시 예외.

    1차: `releases/latest` 페이지의 302 Location (`…/releases/tag/vX.Y.Z`) — API 속도 제한(공용 IP 60회/시)에 걸리지 않음.
    2차: GitHub API (tag_name).
    """
    s = session or requests.Session()
    try:
        r = s.get(LATEST_PAGE, timeout=timeout, allow_redirects=False, headers={"User-Agent": USER_AGENT})
        loc = r.headers.get("Location", "")
        m = re.search(r"/releases/tag/([^/?#]+)", loc)
        if r.status_code in (301, 302, 303, 307, 308) and m:
            tag = m.group(1)
            return tag.lstrip("vV"), loc if loc.startswith("http") else f"https://github.com{loc}"
    except requests.RequestException as e:
        log.debug("releases/latest 리다이렉트 확인 실패, API 로 재시도: %s", e)
    r = s.get(LATEST_API, timeout=timeout, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    r.raise_for_status()
    data = r.json()
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("tag_name 없음")
    return tag.lstrip("vV"), str(data.get("html_url") or RELEASES_URL)


def check(
    config_dir: Path,
    *,
    force: bool = False,
    now: datetime | None = None,
    session: requests.Session | None = None,
) -> UpdateInfo | None:
    """최신 버전 정보. 캐시가 24시간 이내면 캐시를 쓰고, 아니면 조회 후 캐시한다.

    force=True 면 disabled 와 캐시를 무시하고 지금 조회 (doctor 용).
    조회 실패 → 캐시가 있으면 캐시, 없으면 None. 어떤 경우에도 예외를 내지 않는다.
    """
    try:
        if not force and is_disabled(config_dir):
            return None
        now = now or datetime.now()
        cache = read_cache(config_dir)
        latest, url = cache.get("latest"), cache.get("url")
        fresh = False
        if latest and cache.get("checked_at"):
            try:
                fresh = now - datetime.fromisoformat(str(cache["checked_at"])) < CHECK_INTERVAL
            except ValueError:
                fresh = False
        if force or not fresh:
            try:
                latest, url = fetch_latest(session=session)
                write_cache(config_dir, checked_at=now.isoformat(timespec="seconds"), latest=latest, url=url)
            except Exception as e:  # noqa: BLE001 — 네트워크/401/파싱 실패는 조용히
                log.debug("새 버전 확인 실패: %s", e)
                # 실패해도 checked_at 은 갱신해 하루 동안 재시도하지 않는다 (오프라인 환경 배려)
                write_cache(config_dir, checked_at=now.isoformat(timespec="seconds"))
                if not latest:
                    return None
        if not latest:
            return None
        return UpdateInfo(__version__, str(latest), str(url or RELEASES_URL))
    except Exception as e:  # noqa: BLE001
        log.debug("새 버전 확인 중 오류: %s", e)
        return None


def notice(config_dir: Path) -> str | None:
    """CLI 끝에 붙일 한 줄. 새 버전이 없거나 확인 불가면 None."""
    info = check(config_dir)
    if info is not None and info.is_newer:
        return f"[알림] 새 버전 {info.latest} — {info.url}"
    return None
