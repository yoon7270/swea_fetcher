"""풀이 잔디 기기 간 동기화 (M23): 풀이 저장소(git)를 통해 여러 PC 의 잔디를 합친다.

- 기기별 파일: `{root}/.swea-fetch/solved/{device_id}.json` — 각 PC 는 자기 파일만 쓴다 (같은 파일 동시 수정 없음 → git 충돌 없음).
  내용은 로컬 solved.json 과 같은 스키마 (날짜 → [{num, topic, title, via, at}]). 코드·지문 없음. 정렬·고정 들여쓰기로 diff 최소화.
  [성장 기록 지우기] 뒤에도 기기 파일의 옛 기록은 보존한다 (기기 파일 = 기존 파일 ∪ 로컬).
- 합치기(표시): 로컬 ∪ 작업 트리의 `.swea-fetch/solved/*.json` ∪ 원격 캐시. 원격은 백그라운드에서 `git fetch <remote> <branch>` 후
  `git ls-tree` / `git show` 로 읽기만 한다 (pull·merge·rebase 없음, 작업 트리·브랜치 불변) — 결과는 `coach/profile/solved_remote.json` 캐시.
  fetch 는 최소 간격(REMOTE_MIN_INTERVAL)으로 스로틀하고, 실패(오프라인·원격 없음·인증)는 조용히 넘어간다.
- 켜짐 조건 (enabled): 성장 기록 켜짐 + SWEA_SOLVED_SYNC (1/0, 비어 있으면 루트가 git 저장소이고 원격(origin)이 있을 때만 켜짐).
- 모든 공개 함수는 예외를 던지지 않는다 (부가 기능). solved 를 import 하고, solved 가 늦은 import 로 이 모듈을 부른다 (순환 회피).
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import socket
import threading
import time
from datetime import date, timedelta
from pathlib import Path

from . import coach, gitops, growth, solved
from .config import Settings

log = logging.getLogger("swea_fetcher.solved_sync")

DEVICE_ID_FILE = "device_id"
REMOTE_CACHE_FILE = "solved_remote.json"
SYNC_DIR_PARTS = (".swea-fetch", "solved")
REMOTE_MIN_INTERVAL = 600.0  # 원격 fetch 최소 간격 (초)
FETCH_TIMEOUT = 45.0
_AUTO_TTL = 60.0  # 자동(기본값) 판정의 git 조회 캐시 (초)

_lock = threading.Lock()
_last_fetch: dict[str, float] = {}  # root → monotonic 시각 (시도 기준)
_auto_cache: dict[str, tuple[float, bool]] = {}


# --- 켜짐 판정 -------------------------------------------------------------------------------


def enabled(settings: Settings) -> bool:
    """동기화가 동작해야 하는가. 성장 기록이 꺼져 있으면 항상 False."""
    if not settings.growth:
        return False
    if settings.solved_sync is not None:
        return settings.solved_sync
    return auto_default(settings)


def auto_default(settings: Settings) -> bool:
    """SWEA_SOLVED_SYNC 가 비어 있을 때의 기본값: 루트가 git 저장소이고 원격(origin)이 있으면 True. 60초 캐시."""
    key = str(settings.root)
    now = time.monotonic()
    hit = _auto_cache.get(key)
    if hit and now - hit[0] < _AUTO_TTL:
        return hit[1]
    try:
        repo = gitops.find_repo(settings.root)
        value = bool(repo and repo.remote)
    except Exception:  # noqa: BLE001
        value = False
    _auto_cache[key] = (now, value)
    return value


def reset_caches() -> None:
    """테스트·설정 변경용: 자동 판정 캐시와 fetch 스로틀을 비운다."""
    _auto_cache.clear()
    _last_fetch.clear()


# --- 기기 파일 -------------------------------------------------------------------------------


def device_id(settings: Settings) -> str:
    """이 PC 의 식별자 (처음 한 번 만들어 config_dir/device_id 에 저장). 호스트명 슬러그 + 랜덤 4자리."""
    path = Path(settings.config_dir) / DEVICE_ID_FILE
    try:
        text = path.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", text):
            return text
    except OSError:
        pass
    host = re.sub(r"[^a-z0-9]+", "-", socket.gethostname().lower()).strip("-")[:20] or "pc"
    new = f"{host}-{secrets.token_hex(2)}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
    except OSError as e:
        log.warning("기기 식별자를 저장하지 못했습니다: %s", e)
    return new


def sync_dir(settings: Settings) -> Path:
    return Path(settings.root).joinpath(*SYNC_DIR_PARTS)


def device_path(settings: Settings) -> Path:
    return sync_dir(settings) / f"{device_id(settings)}.json"


def _remote_cache_path(settings: Settings) -> Path:
    return growth.profile_dir(settings) / REMOTE_CACHE_FILE


# --- 병합 ------------------------------------------------------------------------------------


def merge_into(dst: dict[str, list[dict]], src: dict[str, list[dict]]) -> None:
    """src 를 dst 에 합친다. 같은 날 같은 문제는 1건 — via 는 swea 우선, 빈 제목·주제는 채우고, 기록 시각은 이른 쪽."""
    for day, items in src.items():
        bucket = dst.setdefault(day, [])
        for it in items:
            for cur in bucket:
                if cur["num"] == it["num"]:
                    if it["via"] == "swea":
                        cur["via"] = "swea"
                    for field in ("topic", "title"):
                        if it.get(field) and not cur.get(field):
                            cur[field] = it[field]
                    at = str(it.get("at") or "")
                    if at and (not cur.get("at") or at < cur["at"]):
                        cur["at"] = at
                    break
            else:
                bucket.append({"num": int(it["num"]), "topic": str(it.get("topic") or ""), "title": str(it.get("title") or ""),
                               "via": it["via"], "at": str(it.get("at") or "")})


def _normalize(days: dict[str, list[dict]], today: date) -> dict[str, list[dict]]:
    """400일 보관 + 날짜·항목 정렬 (diff 최소화)."""
    cutoff = (today - timedelta(days=solved.KEEP_DAYS)).isoformat()
    return {k: sorted(v, key=lambda i: (i.get("at") or "", i["num"])) for k, v in sorted(days.items()) if k >= cutoff and v}


def _read_file(path: Path) -> dict[str, list[dict]]:
    try:
        return solved.parse_days(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sync_device_file(settings: Settings, local: dict[str, list[dict]] | None = None, today: date | None = None) -> bool:
    """기기 파일 = 기존 기기 파일 ∪ 로컬 기록. 내용이 바뀐 때만 쓴다. 쓰면 True. 꺼져 있거나 실패해도 예외 없음."""
    try:
        if not enabled(settings):
            return False
        day = today or growth.now().date()
        with growth._LOCK:
            if local is None:
                local = solved.read_local(settings)
            path = device_path(settings)
            merged: dict[str, list[dict]] = {}
            merge_into(merged, _read_file(path))
            merge_into(merged, local)
            data = {"v": solved.SOLVED_VERSION, "days": _normalize(merged, day)}
            text = json.dumps(data, ensure_ascii=False, indent=1)
            try:
                if path.read_text(encoding="utf-8") == text:
                    return False
            except OSError:
                pass
            if not data["days"] and not path.exists():
                return False  # 올릴 기록이 없으면 빈 파일을 만들지 않는다
            coach._atomic_write(path, data)
            return True
    except Exception as e:  # noqa: BLE001
        log.warning("잔디 기기 파일 저장 실패: %s", e)
        return False


def merged_days(settings: Settings, local: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """표시용: 로컬 ∪ 작업 트리 기기 파일들 ∪ 원격 캐시. 꺼져 있으면 로컬 그대로. 읽기 전용 (git 호출 없음)."""
    try:
        if not enabled(settings):
            return local
        out: dict[str, list[dict]] = {}
        merge_into(out, local)
        d = sync_dir(settings)
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                merge_into(out, _read_file(f))
        merge_into(out, _read_file(_remote_cache_path(settings)))
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("잔디 기록 합치기 실패: %s", e)
        return local


# --- 원격 읽기 -------------------------------------------------------------------------------


def _remote_ref(repo: gitops.RepoInfo) -> tuple[str, str, str] | None:
    """(remote, branch, ref) — upstream 이 있으면 그것, 없으면 origin/{현재 브랜치}. detached·원격 없음이면 None."""
    if not repo.branch or not repo.remote:
        return None
    if repo.upstream and "/" in repo.upstream:
        remote, _, br = repo.upstream.partition("/")
        return remote, br, repo.upstream
    return "origin", repo.branch, f"origin/{repo.branch}"


def refresh_remote(settings: Settings, *, force: bool = False) -> bool:
    """원격 브랜치의 기기 파일들을 읽어 캐시에 반영한다 (fetch + ls-tree/show, 작업 트리·브랜치 불변). 캐시가 바뀌면 True.

    최소 간격(REMOTE_MIN_INTERVAL) 안의 재호출은 아무것도 안 한다 (force 제외). 실패는 조용히 False.
    """
    try:
        if not enabled(settings) or gitops.git_available() is None:
            return False
        key = str(settings.root)
        now = time.monotonic()
        with _lock:
            last = _last_fetch.get(key)
            if not force and last is not None and now - last < REMOTE_MIN_INTERVAL:
                return False
            _last_fetch[key] = now
        repo = gitops.find_repo(settings.root)
        target = _remote_ref(repo) if repo else None
        if repo is None or target is None:
            return False
        remote, branch, ref = target
        try:
            # GCM 로그인 창이 백그라운드에서 뜨지 않게 (인증이 필요하면 조용히 실패)
            cp = gitops._run(["fetch", "--quiet", "--no-tags", "--no-auto-gc", "--no-recurse-submodules", remote, branch], repo.toplevel,
                             FETCH_TIMEOUT, extra_env={"GCM_INTERACTIVE": "never"})
            if cp.returncode != 0:
                log.info("잔디 동기화 fetch 실패(무시): %s", gitops.mask_url((cp.stderr or "").strip()[-200:]))
        except Exception as e:  # noqa: BLE001 — 오프라인이어도 이미 받아 둔 원격 추적 브랜치는 읽는다
            log.info("잔디 동기화 fetch 실패(무시): %s", e)
        if gitops._ok(["rev-parse", "--verify", "-q", ref + "^{commit}"], repo.toplevel) is None:
            return False
        rel_dir = sync_dir(settings).resolve().relative_to(repo.toplevel).as_posix()
        listing = gitops._ok(["ls-tree", "-r", "--name-only", ref, "--", rel_dir + "/"], repo.toplevel)
        remote_days: dict[str, list[dict]] = {}
        for name in (listing or "").splitlines():
            name = name.strip().strip('"')
            if not name.endswith(".json") or "/" in name[len(rel_dir) + 1:]:
                continue
            text = gitops._ok(["show", f"{ref}:{name}"], repo.toplevel)
            if text:
                merge_into(remote_days, solved.parse_days(text))
        data = {"v": solved.SOLVED_VERSION, "days": _normalize(remote_days, growth.now().date())}
        path = _remote_cache_path(settings)
        with growth._LOCK:
            if not growth._writable(settings):
                return False
            if not data["days"] and not path.exists():
                return False
            try:
                if json.loads(path.read_text(encoding="utf-8")) == data:
                    return False
            except (OSError, ValueError):
                pass
            coach._atomic_write(path, data)
        return True
    except Exception as e:  # noqa: BLE001
        log.info("잔디 원격 읽기 실패(무시): %s", e)
        return False


# --- 커밋 대상 -------------------------------------------------------------------------------


def pending_commit_paths(settings: Settings, repo: gitops.RepoInfo) -> list[str]:
    """이번 커밋에 함께 넣을 기기 파일 (저장소 기준 상대 경로). 꺼짐·파일 없음·변경 없음·.gitignore 무시면 빈 목록."""
    try:
        if not enabled(settings):
            return []
        path = device_path(settings)
        if not path.is_file():
            return []
        rel = path.resolve().relative_to(repo.toplevel).as_posix()
        if gitops.path_ignored(repo, rel) or not gitops.path_changed(repo, rel):
            return []
        return [rel]
    except Exception as e:  # noqa: BLE001
        log.warning("잔디 기기 파일 커밋 대상 확인 실패: %s", e)
        return []


def ignored_note(settings: Settings) -> str:
    """기기 폴더가 .gitignore 로 무시되고 있으면 안내 문구, 아니면 빈 문자열 (설정 화면용)."""
    try:
        repo = gitops.find_repo(settings.root)
        if repo is None:
            return ""
        rel = (sync_dir(settings).resolve() / "x.json").relative_to(repo.toplevel).as_posix()
        if gitops.path_ignored(repo, rel):
            return "풀이 저장소의 .gitignore 가 .swea-fetch/ 를 무시하고 있어 잔디 기록이 올라가지 않습니다. 해당 줄을 빼 주세요."
    except Exception:  # noqa: BLE001
        pass
    return ""
