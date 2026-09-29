"""지문 디스크 캐시 (M12-d). `{config_dir}/cache/statements/{num}.json`, 최근 50건 (mtime 기준).

- 지문은 삼성 저작물이므로 루트(풀이 저장소) 안에는 절대 쓰지 않는다: cache_dir 가 settings.root 안이면 쓰기를 거부한다.
- 문제 폴더·storage·gitops 와 무관. 손상된 파일은 없는 것으로 취급한다.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Settings
from .models import ImageRef, ProblemContent

log = logging.getLogger("swea_fetcher.content_cache")

STATEMENTS_DIR_NAME = "statements"
MAX_ENTRIES = 50
_VERSION = 1


@dataclass(frozen=True)
class CachedStatement:
    num: int
    topic: str
    title: str
    fetched_at: str  # ISO 8601
    content: ProblemContent


def statements_dir(cache_dir: Path) -> Path:
    return Path(cache_dir) / STATEMENTS_DIR_NAME


def _inside(path: Path, base: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except (ValueError, OSError):
        return False


def _file(settings: Settings, num: int) -> Path:
    return statements_dir(settings.cache_dir) / f"{int(num)}.json"


def _encode(num: int, topic: str, title: str, content: ProblemContent) -> dict:
    return {
        "version": _VERSION,
        "num": num,
        "topic": topic,
        "title": title,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "limits_html": content.limits_html,
        "body_html": content.body_html,
        "images": {
            token: {
                "data": base64.b64encode(ref.data).decode("ascii") if ref.data else None,
                "url": ref.url,
                "alt": ref.alt,
                "error": ref.error,
            }
            for token, ref in content.images.items()
        },
    }


def _decode(raw: dict) -> CachedStatement:
    images: dict[str, ImageRef] = {}
    for token, d in (raw.get("images") or {}).items():
        data = base64.b64decode(d["data"], validate=True) if d.get("data") else None
        images[str(token)] = ImageRef(data=data, url=d.get("url"), alt=str(d.get("alt") or ""), error=d.get("error"))
    content = ProblemContent(limits_html=str(raw.get("limits_html") or ""), body_html=str(raw["body_html"]), images=images)
    return CachedStatement(int(raw["num"]), str(raw.get("topic") or ""), str(raw.get("title") or ""), str(raw.get("fetched_at") or ""), content)


def save(settings: Settings, num: int, topic: str, title: str, content: ProblemContent) -> bool:
    """캐시에 기록. 거부(root 안)·실패면 False. 어떤 경우에도 예외를 던지지 않는다 (지문은 부가 기능)."""
    if _inside(settings.cache_dir, settings.root):
        log.warning("지문 캐시 위치가 루트 폴더 안이라 기록하지 않습니다: %s", settings.cache_dir)
        return False
    path = _file(settings, num)
    tmp = path.with_suffix(".json.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(_encode(num, topic, title, content), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        _prune(path.parent)
    except OSError as e:
        log.warning("지문 캐시 기록 실패: %s", e)
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True


def _prune(d: Path, keep: int = MAX_ENTRIES) -> None:
    """최근 keep 건만 남긴다 (mtime 내림차순)."""
    files = []
    for p in d.glob("*.json"):
        try:
            files.append((p.stat().st_mtime, p))
        except OSError:
            continue
    files.sort(key=lambda t: t[0], reverse=True)
    for _mt, p in files[keep:]:
        try:
            p.unlink()
        except OSError:
            pass


def has(settings: Settings, num: int) -> bool:
    """캐시 파일 존재 여부만 (내용 검증 없음, 최근 목록 표시용)."""
    return _file(settings, num).is_file()


def load(settings: Settings, num: int) -> CachedStatement | None:
    """캐시 읽기 (네트워크 없음). 없거나 손상되면 None. 읽으면 mtime 을 갱신해 LRU 에 반영한다."""
    path = _file(settings, num)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        cached = _decode(raw)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError, binascii.Error, AttributeError) as e:
        log.warning("지문 캐시가 손상되어 무시합니다 (%s): %s", path.name, e)
        return None
    try:
        os.utime(path)
    except OSError:
        pass
    return cached


def clear(cache_dir: Path) -> int:
    """statements 캐시 파일을 모두 지운다. 지운 개수 반환. 다른 파일은 건드리지 않는다."""
    d = statements_dir(cache_dir)
    n = 0
    if not d.is_dir():
        return 0
    for p in list(d.glob("*.json")) + list(d.glob("*.json.tmp")):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    try:
        d.rmdir()  # 비었으면 폴더도 정리 (실패해도 무시)
        Path(cache_dir).rmdir()
    except OSError:
        pass
    return n
