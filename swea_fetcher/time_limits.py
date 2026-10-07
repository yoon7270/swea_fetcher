"""문제별 Python 시간 제한 (M25): 지문 제한사항의 "Python의 경우 4초" 를 읽어 로컬 검증 타임아웃으로 쓴다.

- 저장할 때(dry-run 아님) 지문에서 읽은 값을 `{config_dir}/time_limits.json` 에 번호별로 남긴다 (공개 정보만).
- 찾는 순서: time_limits.json → 앱 지문 캐시(content_cache) → 없으면 None (호출자가 checker.DEFAULT_TIMEOUT 사용).
- SWEA 제한은 "N개 테스트케이스를 합쳐서" 의 총시간이라 로컬 샘플 실행에도 그대로 쓴다.
- 모든 함수는 예외를 던지지 않는다 (부가 정보 — 검증 흐름을 깨지 않는다). `logout --all` 이 지운다.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup

from . import content_cache
from .config import Settings

log = logging.getLogger("swea_fetcher.time_limits")

FILE = "time_limits.json"
MAX_SECONDS = 600.0  # 이상한 값(파싱 오류)으로 검증이 끝없이 기다리지 않게
_PY_RE = re.compile(r"python[^0-9/|\n]{0,12}?(\d+(?:\.\d+)?)\s*초", re.I)  # "Python의 경우 4초", "Python : 2초"
_SEC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*초")


def _text(limits_html: str) -> str:
    try:
        return BeautifulSoup(limits_html or "", "lxml").get_text(" ", strip=True)
    except Exception:  # noqa: BLE001
        return ""


def parse_python_limit(limits_html: str) -> float | None:
    """제한사항 HTML → Python 시간 제한(초). "Python의 경우 N초" 가 있으면 그 값, 없고 시간 줄에 초 값이 하나뿐이면 그 값, 아니면 None."""
    text = _text(limits_html)
    m = _PY_RE.search(text)
    if m:
        return _valid(float(m.group(1)))
    head = text.split("메모리")[0]  # "시간 : … 메모리 : …" 한 줄로 이어 붙은 경우 시간 부분만
    if "시간" in head:
        values = {float(v) for v in _SEC_RE.findall(head)}
        if len(values) == 1:
            return _valid(values.pop())
    return None


def _valid(v: float) -> float | None:
    return v if 0 < v <= MAX_SECONDS else None


def _path(settings: Settings) -> Path:
    return settings.config_dir / FILE  # cache/ 밖: 지문 캐시를 꺼도 남고, 캐시 끔 = cache/ 에 아무것도 안 씀 규칙을 지킨다


def _read(settings: Settings) -> dict[str, float]:
    try:
        raw = json.loads(_path(settings).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("시간 제한 기록을 읽지 못했습니다: %s", e)
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        if str(k).isdigit() and isinstance(v, (int, float)) and not isinstance(v, bool) and _valid(float(v)):
            out[str(k)] = float(v)
    return out


def remember(settings: Settings, num: int, limits_html: str) -> float | None:
    """지문 제한사항에서 읽은 값을 기록. 읽은 값(없으면 None). 루트 폴더 안이면 기록하지 않는다."""
    seconds = parse_python_limit(limits_html)
    if seconds is None:
        return None
    try:
        path = _path(settings)
        try:
            path.resolve().relative_to(Path(settings.root).resolve())
            return seconds  # 루트 안 (GitHub 로 올라갈 수 있는 곳) 에는 쓰지 않는다
        except ValueError:
            pass
        data = _read(settings)
        if data.get(str(int(num))) == seconds:
            return seconds
        data[str(int(num))] = seconds
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dict(sorted(data.items(), key=lambda kv: int(kv[0])))), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        log.warning("시간 제한 기록 실패: %s", e)
    return seconds


def lookup(settings: Settings, num: int) -> float | None:
    """그 문제의 Python 시간 제한(초). 기록 → 지문 캐시 순. 모르면 None."""
    v = _read(settings).get(str(int(num)))
    if v is not None:
        return v
    try:
        cached = content_cache.load(settings, int(num))
    except Exception:  # noqa: BLE001
        cached = None
    if cached is not None and cached.content is not None:
        return parse_python_limit(cached.content.limits_html)
    return None


def clear(config_dir: Path) -> int:
    """기록 파일 삭제 (`logout --all`)."""
    n = 0
    for name in (FILE, FILE + ".tmp"):
        try:
            (Path(config_dir) / name).unlink()
            n += 1
        except OSError:
            pass
    return n
