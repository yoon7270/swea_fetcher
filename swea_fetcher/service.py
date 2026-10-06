"""CLI·GUI 공용 서비스 계층. 파이프라인 로직은 여기 한 곳에만 둔다.

fetch_problem : settings → contestProbId → 세션 → 페이지 → 파싱 → (첨부) → 저장/미리보기
verify_login  : 세션 확보만 (설정 확인용)
list_topics   : root 아래 주제 폴더 (중첩 가능, `test/IM_test` 표기)
list_recent   : root 아래 {topic}/{num}/ 를 mtime 순으로 (중첩 주제 포함)
write_env     : .env 파일 쓰기 (비밀번호는 절대 쓰지 않음; SWEA_PYTHON 등 다른 키는 보존)
set_env_values: .env 의 개별 키 갱신 (M7: SWEA_COMMIT_TEMPLATE, SWEA_AUTO_PUSH)
push_problem  : 문제 폴더만 git 커밋(+푸시) (M7). 자격증명은 다루지 않는다
submit_problem: SWEA 에 제출하고 채점 결과를 받는다 (M8). Pass 면 push 까지 (submit_and_push)
ask_coach     : AI 코치 (M17) — 코드 평가·힌트·정답 풀이·연결 테스트. 호출 전 사용자 동의 필수 (GUI 전용)
check_problem : 로컬 검증 + 통과 기록 (M20 풀이 잔디). growth_solved: 잔디 데이터 조회
growth_*      : 성장 기록 (M19) — 개요·리포트 조회, 주간 AI 코멘트 생성(generate_growth), 삭제. 동의는 consent_ok 콜백 (GUI 전용)
catalog_status / refresh_catalog / refresh_passed / recommend_today / recommend_ai : 오늘의 추천 (M24) — 공개 문제 목록 카탈로그, 수준·오늘의 세트, AI 약점 선별.
              catalog_status·recommend_today 는 파일 읽기만, 나머지는 네트워크/AI 라 워커에서. 동의는 consent_ok 콜백 (GUI 전용)

네트워크·파일 I/O 가 있으므로 GUI 는 워커 스레드에서 호출한다.
"""

from __future__ import annotations

import dataclasses
import json
import difflib
import logging
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Sequence

from . import ai_engine, ai_prompts, auth, catalog, checker, client, coach, config, content_cache, gitops, growth, growth_tags, lookup, parser, problem_types, recommend, solved, solved_sync, storage, submit
from .config import Settings
from .errors import AiError, GitError, InvalidInput, SweaFetchError
from .gitops import GitResult
from .submit import SubmitResult
from .models import ImageRef, ProblemContent, ProblemInfo, SaveResult

log = logging.getLogger("swea_fetcher.service")

ProgressCb = Callable[[str], None]

PREVIEW_LINES = 3
PREVIEW_CHARS = 60
_SKELETON_HEADER_RE = re.compile(r"^#\s*(\d+)\.\s*(.*)$")


# --- 데이터 ---------------------------------------------------------------------------


@dataclass
class FetchOptions:
    force: bool = False
    skeleton_only: bool = False
    dry_run: bool = False
    refresh_index: bool = False
    num_override: int | None = None
    with_content: bool = False  # 지문 추출 (GUI 만 True, M12). False 면 지문 파싱·이미지 다운로드·캐시 쓰기 모두 없음
    cache_content: bool = False  # with_content 이고 dry-run 이 아닐 때 지문을 앱 캐시(config_dir/cache)에 기록


@dataclass
class FilePlan:
    """dry_run 미리보기의 파일 1개."""

    name: str
    action: str  # "create" | "overwrite" | "keep" | "conflict" | "create_empty"
    source: str | None = None  # 원본 첨부 파일명
    size: int | None = None
    preview: str = ""


@dataclass
class FetchOutcome:
    info: ProblemInfo
    result: SaveResult | None  # dry_run 이면 None
    preview: dict | None  # dry_run: {"problem_dir": Path, "files": [FilePlan], "needs_force": bool}
    notices: list[str] = field(default_factory=list)  # 주제 이름 안내 등
    topic: str = ""  # 실제 사용된 주제 폴더 이름
    content: ProblemContent | None = None  # 지문 (with_content 일 때만, 추출 실패면 None)


@dataclass
class RecentItem:
    num: int
    title: str | None
    topic: str
    path: Path
    saved_at: datetime


# --- 내부 ------------------------------------------------------------------------------


def _emit(progress: ProgressCb | None, msg: str) -> None:
    log.info(msg)
    if progress:
        progress(msg)


def resolve_topic(root: Path, topic: str) -> tuple[str, list[str]]:
    """주제 폴더 이름 안내. (실제 사용할 이름, 안내 메시지들).

    대소문자만 다른 기존 폴더가 있으면 그 이름을 쓰고, 비슷한 폴더는 알리기만 한다.
    """
    try:
        topic = storage.normalize_topic(topic)
    except ValueError:
        topic = topic.strip()  # 검증 실패는 저장 단계(resolve_problem_dir)에서 InvalidInput 으로 보고
    notices: list[str] = []
    dirs = list_topics(Path(root))  # 전체 상대 경로 문자열 기준으로 비교 (test/im_test vs test/IM_test)
    if not dirs:
        return topic, notices
    if topic in dirs:
        return topic, notices
    same_ci = [d for d in dirs if d.lower() == topic.lower()]
    if same_ci:
        notices.append(f"기존 폴더 '{same_ci[0]}' 를 사용합니다 (입력: '{topic}')")
        return same_ci[0], notices
    close = difflib.get_close_matches(topic, dirs, n=3, cutoff=0.6)
    if close:
        notices.append(f"비슷한 폴더가 있습니다: {', '.join(close)} — 새 폴더 '{topic}' 를 만듭니다")
    return topic, notices


def preview_text(data: bytes | None, limit_lines: int = PREVIEW_LINES, limit_chars: int = PREVIEW_CHARS) -> str:
    """앞 limit_lines 줄을 ' / ' 로 이어 붙인 미리보기."""
    if data is None:
        return ""
    lines = storage.normalize_text(data).splitlines()
    s = " / ".join(ln.strip() for ln in lines[:limit_lines])
    if len(lines) > limit_lines:
        s += " ..."
    return s if len(s) <= limit_chars else s[: limit_chars - 3] + "..."


def _build_preview(
    info: ProblemInfo, topic: str, settings: Settings, in_bytes: bytes | None, out_bytes: bytes | None, opts: FetchOptions
) -> dict:
    try:
        problem_dir = storage.resolve_problem_dir(settings.root, topic, info.num)
    except ValueError as e:
        raise InvalidInput(str(e)) from e
    input_path = problem_dir / settings.input_name
    output_path = problem_dir / settings.output_name
    py_path = problem_dir / f"{info.num}.py"
    files: list[FilePlan] = []
    if opts.skeleton_only:
        files.append(FilePlan(settings.input_name, "keep" if input_path.exists() else "create_empty"))
    else:
        for path, data, src in ((input_path, in_bytes, info.input_filename), (output_path, out_bytes, info.output_filename)):
            action = ("overwrite" if opts.force else "conflict") if path.exists() else "create"
            files.append(FilePlan(path.name, action, src, len(data or b""), preview_text(data)))
    files.append(FilePlan(py_path.name, "keep" if py_path.exists() else "create"))
    return {
        "problem_dir": problem_dir,
        "files": files,
        "needs_force": any(f.action == "conflict" for f in files),
    }


_IMG_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM")


def _looks_like_image(data: bytes) -> bool:
    return data.startswith(_IMG_MAGIC) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def _load_images(session, settings: Settings, content: ProblemContent, progress: ProgressCb | None = None) -> ProblemContent:
    """url 만 있고 data 가 없는 이미지를 순차로 내려받는다. 개별 실패는 ImageRef.error 로 남기고 계속 (fetch 실패 아님)."""
    todo = [t for t, r in content.images.items() if r.url and r.data is None and not r.error]
    if not todo:
        return content
    images = dict(content.images)
    for i, token in enumerate(todo, 1):
        ref = images[token]
        _emit(progress, f"지문 이미지 {i}/{len(todo)}")
        try:
            data = client.download(session, ref.url, settings)
            if not _looks_like_image(data):
                images[token] = ImageRef(url=ref.url, alt=ref.alt, error="이미지가 아닌 응답")
            elif len(data) > parser.IMG_MAX_BYTES:
                images[token] = ImageRef(url=ref.url, alt=ref.alt, error="이미지가 너무 큽니다 (5MB 초과)")
            else:
                images[token] = ImageRef(data=data, url=ref.url, alt=ref.alt)
        except SweaFetchError as e:
            log.debug("지문 이미지 다운로드 실패 (%s): %s", ref.url, e)
            images[token] = ImageRef(url=ref.url, alt=ref.alt, error=f"다운로드 실패: {e}")
    return dataclasses.replace(content, images=images)


def _extract_content(session, settings: Settings, html: str, progress: ProgressCb | None) -> ProblemContent | None:
    """지문 추출 + 이미지 다운로드. 어떤 실패도 fetch 를 중단시키지 않는다 (None 반환)."""
    try:
        content = parser.parse_content(html)
        if content is not None:
            content = _load_images(session, settings, content, progress)
        return content
    except Exception as e:  # noqa: BLE001 — 지문은 부가 기능
        log.warning("지문 추출 실패: %s", e)
        return None


# --- 공개 API --------------------------------------------------------------------------


def fetch_problem(
    settings: Settings,
    target: str,
    topic: str,
    opts: FetchOptions | None = None,
    progress: ProgressCb | None = None,
) -> FetchOutcome:
    """문제 1건 저장(또는 미리보기). 예외는 SweaFetchError 계열을 그대로 전파한다."""
    opts = opts or FetchOptions()
    target = (target or "").strip()
    if not target:
        raise InvalidInput("문제 번호 또는 URL 을 입력하세요")
    if not (topic or "").strip():
        raise InvalidInput("주제 폴더 이름을 입력하세요")
    try:
        topic = storage.normalize_topic(topic)
    except ValueError as e:
        raise InvalidInput(str(e)) from e

    by_number = target.isdigit()
    cid = None if by_number else parser.extract_contest_prob_id(target)

    _emit(progress, "로그인 세션 확인")
    session = auth.get_session(settings)

    if by_number:
        _emit(progress, f"문제 번호 {target} 로 찾는 중 (공개 목록 → Solving Club 상자)")
        cid = lookup.find_by_number(session, settings, int(target), refresh=opts.refresh_index)

    _emit(progress, f"문제 페이지 가져오는 중 (contestProbId={cid})")
    html, kind = client.fetch_problem_page(session, settings, cid)
    log.debug("page_kind=%s, html=%d bytes", kind, len(html))
    info = parser.parse(html, kind, cid, require_attachments=not opts.skeleton_only)

    if opts.num_override is not None:
        if info.num is not None and info.num != opts.num_override:
            log.warning("페이지의 번호 %s 대신 지정한 번호 %s 를 사용합니다", info.num, opts.num_override)
        info = dataclasses.replace(info, num=opts.num_override)
    if info.num is None:
        raise InvalidInput("문제 번호를 페이지에서 찾지 못했습니다. 번호를 직접 지정하세요 (--num)")

    topic, notices = resolve_topic(settings.root, topic)
    for n in notices:
        _emit(progress, f"[알림] {n}")

    content = None
    if opts.with_content:
        content = _extract_content(session, settings, html, progress)
        if content is None:
            notices.append("지문 영역을 찾지 못했습니다")
            _emit(progress, "[알림] 지문 영역을 찾지 못했습니다")

    in_bytes = out_bytes = None
    if not opts.skeleton_only:
        _emit(progress, "첨부 다운로드")
        in_bytes = client.download(session, info.input_url, settings)
        out_bytes = client.download(session, info.output_url, settings)

    if opts.dry_run:
        _emit(progress, "미리보기 (저장하지 않음)")
        return FetchOutcome(info, None, _build_preview(info, topic, settings, in_bytes, out_bytes, opts), notices, topic, content)

    # 지문 캐시는 저장 단계 전에 기록한다: "이미 저장된 파일" 충돌로 저장이 실패해도 지문은 다시 볼 수 있게
    if content is not None and opts.cache_content:
        content_cache.save(settings, info.num, topic, info.title, content)

    _emit(progress, "저장 중")
    try:
        if opts.skeleton_only:
            result = storage.save_skeleton(settings.root, topic, info, settings)
        else:
            result = storage.save_problem(settings.root, topic, info, in_bytes, out_bytes, settings, force=opts.force)
    except ValueError as e:
        raise InvalidInput(str(e)) from e
    _emit(progress, "저장 완료")
    # 저장 직후 자동 동기화 (M11, reason=save). skeleton-only 는 제외. 실패해도 저장 결과를 덮지 않는다
    if not opts.skeleton_only and "save" in settings.auto_push_on and settings.auto_push:
        try:
            sync_now(settings, reason="save", problem_dir=result.problem_dir, progress=progress)
        except Exception as e:  # noqa: BLE001
            log.debug("자동 동기화(save) 실패: %s", e)
    return FetchOutcome(info, result, None, notices, topic, content)


def verify_login(settings: Settings, progress: ProgressCb | None = None) -> str:
    """세션을 확보한다. 성공 시 표시용 메시지. 예외는 그대로 전파."""
    _emit(progress, "로그인 확인 중")
    auth.get_session(settings, explicit=True)  # 사용자 명시 확인: 지문 가드 우회
    msg = f"로그인 확인 완료 ({settings.user_id}). 세션 저장됨"
    _emit(progress, msg)
    return msg


def is_session_cached(settings: Settings) -> bool:
    """네트워크 없이 session.json 존재 여부만 (상태바 표시용)."""
    return settings.session_file.is_file()


_SKIP_DIRS = {".git", ".idea", "__pycache__", ".venv", "venv", "node_modules"}


def _is_skipped_dir(d: Path) -> bool:
    return d.name.startswith(".") or d.name in _SKIP_DIRS


def _subdirs(d: Path) -> list[Path]:
    try:
        return sorted(c for c in d.iterdir() if c.is_dir() and not _is_skipped_dir(c))
    except OSError:
        return []


def list_topics(settings_or_root: Settings | Path) -> list[str]:
    """root 아래 주제 폴더를 `/` 구분 상대 경로로 (정렬).

    주제 폴더 = 숫자 이름의 자식 폴더를 하나 이상 가진 폴더, 또는 자식 폴더가 없는 비숫자 폴더.
    `test/IM_test` 처럼 중첩 가능 (깊이 storage.MAX_TOPIC_DEPTH). 숨김·.git·.idea·__pycache__ 제외.
    루트 바로 아래의 숫자 폴더는 주제가 아니므로 무시.
    """
    root = settings_or_root.root if isinstance(settings_or_root, Settings) else Path(settings_or_root)
    if not root.is_dir():
        return []
    topics: list[str] = []
    queue: list[tuple[Path, str, int]] = [(c, c.name, 1) for c in _subdirs(root) if not c.name.isdigit()]
    while queue:  # BFS
        d, rel, depth = queue.pop(0)
        children = _subdirs(d)
        has_problem = any(c.name.isdigit() for c in children)
        if has_problem or not children:
            topics.append(rel)
        if depth < storage.MAX_TOPIC_DEPTH:
            queue.extend((c, f"{rel}/{c.name}", depth + 1) for c in children if not c.name.isdigit())
    return sorted(topics)


def read_skeleton_title(py_path: Path) -> str | None:
    """{num}.py 첫 줄 `# 25730. 항아리 게임` 에서 제목을 읽는다. 없으면 None."""
    try:
        with open(py_path, encoding="utf-8", errors="replace") as f:
            first = f.readline().strip()
    except OSError:
        return None
    m = _SKELETON_HEADER_RE.match(first)
    if not m:
        return None
    return m.group(2).strip() or None


def list_recent(settings_or_root: Settings | Path, limit: int | None = 20) -> list[RecentItem]:
    """root 아래 {topic}/{num}/ 폴더를 수정 시각 내림차순으로. topic 은 `test/IM_test` 표기. limit=None 이면 전부.

    Settings 로 부르면 코드 첫 줄 주석이 없어 제목을 못 읽은 문제를 앱 기록(지문 캐시·코치·잔디·번호 색인)으로 채운다."""
    root = settings_or_root.root if isinstance(settings_or_root, Settings) else Path(settings_or_root)
    items: list[RecentItem] = []
    for topic in list_topics(root):
        tdir = root.joinpath(*topic.split("/"))
        try:
            children = list(tdir.iterdir())
        except OSError:
            continue
        for d in children:
            if not d.is_dir() or not d.name.isdigit():
                continue
            try:
                mtime = max([d.stat().st_mtime] + [p.stat().st_mtime for p in d.iterdir() if p.is_file()])
            except OSError:
                continue
            num = int(d.name)
            items.append(RecentItem(num, read_skeleton_title(d / f"{num}.py"), topic, d, datetime.fromtimestamp(mtime)))
    items.sort(key=lambda it: it.saved_at, reverse=True)
    if limit is not None:
        items = items[:limit]
    if isinstance(settings_or_root, Settings):
        _fill_missing_titles(settings_or_root, items)
    return items


_INDEX_TITLE_PREFIX_RE = re.compile(r"^\s*\[\d+\]\s*")  # 문제 상자 제목 "[07] 항아리 게임" 의 순번


def _fill_missing_titles(settings: Settings, items: list[RecentItem]) -> None:
    """제목이 없는 항목(코드 첫 줄 `# 번호. 제목` 이 지워진 경우)을 앱 기록에서 채운다. 실패해도 예외 없음 (제목은 부가 정보).

    순서: 지문 캐시(SWEA 원래 제목) → 코치 기록 → 풀이 잔디 → 문제 번호 색인(상자 제목, 앞 순번 제거)."""
    missing = [it for it in items if not it.title]
    if not missing:
        return
    known: dict[int, str] = {}
    try:
        for n, rec in coach._load_records(settings).items():
            if rec.title and str(n).isdigit():
                known.setdefault(int(n), rec.title)
        for day in solved.load(settings).values():
            for s_it in day:
                if s_it.title:
                    known.setdefault(s_it.num, s_it.title)
        for n, entry in lookup.load_index(settings).items():
            title = _INDEX_TITLE_PREFIX_RE.sub("", str((entry or {}).get("title") or "")).strip() if isinstance(entry, dict) else ""
            if title and str(n).isdigit():
                known.setdefault(int(n), title)
    except Exception:  # noqa: BLE001
        log.debug("제목 보충용 기록을 읽지 못했습니다", exc_info=True)
    for it in missing:
        try:
            cached = content_cache.load(settings, it.num)
        except Exception:  # noqa: BLE001
            cached = None
        it.title = (cached.title if cached is not None and cached.title else None) or known.get(it.num) or None


def find_problem(settings: Settings, num: int) -> RecentItem | None:
    """루트에 저장된 그 번호의 문제 폴더 (여러 주제에 있으면 가장 최근에 고친 것). 없으면 None."""
    for it in list_recent(settings.root, limit=None):
        if it.num == int(num):
            return it
    return None


def write_env(config_dir: Path, root: Path, user_id: str, input_name: str = "input.txt", output_name: str = "output.txt") -> Path:
    """.env 를 쓴다. 비밀번호는 받지도 쓰지도 않는다 (config.save_password 가 담당).

    기본 4개 키 외에 이미 있던 키(SWEA_PYTHON, SWEA_COMMIT_TEMPLATE, SWEA_AUTO_PUSH …)는 보존한다.
    남아 있던 평문 SWEA_PW 줄은 제거한다 (init 이 keyring 으로 옮긴 뒤 호출).
    """
    values = {
        "SWEA_ROOT": str(root),
        "SWEA_ID": user_id.strip(),
        "SWEA_INPUT_NAME": input_name,
        "SWEA_OUTPUT_NAME": output_name,
        config.PASSWORD_KEY: None,
    }
    return set_env_values(config_dir, **values)


def set_env_values(config_dir: Path, **values: str | None) -> Path:
    """.env 의 키를 갱신한다 (있으면 그 줄 교체, 없으면 끝에 추가, 값이 None 이면 줄 삭제). 다른 줄은 그대로.

    SWEA_PW 는 어떤 값이 와도 쓰지 않는다 (None 으로 주면 남아 있던 줄을 지운다).
    """
    config_dir = Path(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    env_file = config_dir / config.ENV_FILE_NAME
    values = {k: (None if k == config.PASSWORD_KEY else v) for k, v in values.items()}
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.is_file() else []
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        key = m.group(1) if m else None
        if key in values:
            seen.add(key)
            if values[key] is not None:
                out.append(f"{key}={quote_env(str(values[key]))}")
            continue
        out.append(line)
    for key, val in values.items():
        if key not in seen and val is not None:
            out.append(f"{key}={quote_env(str(val))}")
    env_file.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    return env_file


def quote_env(value: str) -> str:
    """python-dotenv 규칙: #, =, 공백, 따옴표가 있으면 큰따옴표로 감싼다."""
    if any(ch in value for ch in ' #="\'') or value != value.strip():
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


# --- git (M7) --------------------------------------------------------------------------


def git_status(settings_or_root: Settings | Path) -> gitops.RepoInfo | None:
    """설정 페이지·doctor 용: 루트의 저장소 정보 (없으면 None). git 자체가 없어도 None."""
    root = settings_or_root.root if isinstance(settings_or_root, Settings) else Path(settings_or_root)
    return gitops.find_repo(root)


def commit_message_for(settings: Settings, topic: str, num: int, problem_dir: Path | None = None) -> str:
    """템플릿 + 뼈대 첫 줄의 제목으로 커밋 메시지를 만든다 (GUI 다이얼로그 기본값)."""
    if problem_dir is None:
        problem_dir = storage.resolve_problem_dir(settings.root, topic, num)
    title = read_skeleton_title(Path(problem_dir) / f"{num}.py")
    return gitops.render_message(settings.commit_template, RecentItem(num, title, topic, Path(problem_dir), datetime.now()), topic)


def sync_now(
    settings: Settings,
    *,
    reason: str = "manual",
    problem_dir: Path | None = None,
    scope: str | None = None,
    dry_run: bool = False,
    progress: ProgressCb | None = None,
) -> GitResult | None:
    """자동 동기화 1회 (M11). 예외를 던지지 않고 GitResult 로 반환 — 자동 경로 흐름을 끊지 않는다.

    reason ∈ pass|check|save|watch|manual. manual 은 항상 실행, 그 외는 설정 auto_push_on 에 있어야 실행.
    꺼짐/remote 없음/저장소 아님 → None. scope 기본은 settings.auto_push_scope.
    problem_dir 가 주어지고 scope=problem 이고 reason 이 문제발 (pass/check/save) 이면 그 폴더만 커밋.
    """
    if reason != "manual":
        if not settings.auto_push or reason not in settings.auto_push_on:
            return None
    if gitops.git_available() is None:
        return None
    repo = gitops.find_repo(settings.root)
    if repo is None or not repo.remote:
        return None
    op = gitops.in_progress_operation(repo)
    if op or not repo.branch:
        return gitops.GitResult(False, False, None, "", "", f"{op or 'detached HEAD'} 상태라 자동 동기화를 건너뜁니다", failed=True)
    scope = scope or settings.auto_push_scope
    if dry_run:
        dirs = gitops.changed_problem_dirs(repo, settings.root)
        note = f"[미리보기] scope={scope}, 변경된 문제 폴더 {len(dirs)}개"
        return gitops.GitResult(False, False, None, "", "\n".join(str(d) for d in dirs), note)
    if scope == "problem" and problem_dir is not None and reason in ("pass", "check", "save"):
        message = commit_message_for_dir(settings, problem_dir)
        _emit(progress, f"자동 동기화: {problem_dir.name}")
        return gitops.commit_and_push(repo, problem_dir, message, push=True, **_extra_kw(settings, repo))
    _emit(progress, f"자동 동기화 ({scope})")
    # 풀이 잔디 기기 파일(M23): 문제 폴더와 함께. 문제 폴더 변경이 없을 땐 watch·manual 에서만 단독 커밋 (그 외는 다음 커밋에 묻어간다)
    extra = solved_sync.pending_commit_paths(settings, repo) if scope == "problem" else []
    return gitops.commit_and_push_scope(repo, settings.root, scope, settings.commit_template, push=True, extra_paths=extra, extra_alone=reason in ("watch", "manual"))


def _extra_kw(settings: Settings, repo: gitops.RepoInfo) -> dict:
    """커밋에 함께 넣을 풀이 잔디 기기 파일 (M23). 없으면 빈 dict — 기존 호출 모양 그대로."""
    extra = solved_sync.pending_commit_paths(settings, repo)
    return {"extra_paths": extra} if extra else {}


def commit_message_for_dir(settings: Settings, problem_dir: Path) -> str:
    """problem_dir 기준 단일 문제 커밋 메시지 (템플릿 적용)."""
    problem_dir = Path(problem_dir)
    num = int(problem_dir.name) if problem_dir.name.isdigit() else 0
    try:
        topic = problem_dir.parent.resolve().relative_to(Path(settings.root).resolve()).as_posix()
    except ValueError:
        topic = problem_dir.parent.name
    title = read_skeleton_title(problem_dir / f"{num}.py")
    return gitops.render_message(settings.commit_template, RecentItem(num, title, topic, problem_dir, datetime.now()), topic)


def push_problem(
    settings: Settings,
    topic: str,
    num: int,
    *,
    message: str | None = None,
    push: bool = True,
    progress: ProgressCb | None = None,
) -> GitResult:
    """문제 폴더만 커밋(+푸시). 전제 조건 미충족·git 실패 → GitError (exit 7).

    force push·pull 은 하지 않는다. 인증은 Git Credential Manager 가 담당 (GIT_TERMINAL_PROMPT=0).
    """
    try:
        problem_dir = storage.resolve_problem_dir(settings.root, topic, num)
    except ValueError as e:
        raise InvalidInput(str(e)) from e
    if gitops.git_available() is None:
        raise GitError("git 이 설치되어 있지 않습니다", hint="https://git-scm.com 에서 Git for Windows 를 설치한 뒤 다시 시도하세요")
    _emit(progress, "저장소 확인")
    repo = gitops.find_repo(settings.root, problem_dir)
    reasons = gitops.preflight(repo, problem_dir, push=push)
    if reasons:
        raise GitError("; ".join(reasons))
    assert repo is not None
    if not (message or "").strip():
        message = commit_message_for(settings, topic, num, problem_dir)
    rel = problem_dir.resolve().relative_to(repo.toplevel).as_posix()
    _emit(progress, f"git add/commit: {rel} ({repo.branch}{' → ' + repo.upstream if repo.upstream and push else ''})")
    result = gitops.commit_and_push(repo, problem_dir, message.strip(), push=push, **_extra_kw(settings, repo))
    if result.failed:
        raise GitError(result.note, hint=result.output[-600:] if result.output else "")
    _emit(progress, result.note)
    return result


# --- 제출 (M8) -------------------------------------------------------------------------


@dataclass
class SubmitOutcome:
    submit: SubmitResult
    git: GitResult | None = None  # Pass + push 요청 시
    notes: list[str] = field(default_factory=list)  # 소스 변환 안내 등
    contest_prob_id: str = ""
    category_type: str = ""  # 제출 맥락 (CODE/BOX) — 진단 표시용 (B3)
    category_id: str = ""
    coach: coach.ProblemRecord | None = None  # AI 코치 학습 기록 스냅샷 (M17). 기록 실패면 None


def cached_submit_label(settings: Settings, num: int) -> str:
    """확인창 즉시 표시용 제출 대상 라벨 (색인만, 네트워크 없음). 미확인이면 ""."""
    return lookup.cached_category_label(settings, num)


def resolve_submit_target(settings: Settings, num: int, refresh: bool = False) -> tuple[str, str, str, str]:
    """제출 대상 (contestProbId, categoryType, categoryId, 맥락 라벨). 확인창·프롬프트에 대상을 미리 보여주기 위함 (B1).

    refresh=True 면 box_scanned 를 무시하고 클럽 상자를 다시 훑는다 ([다시 찾기] / --refresh-index).
    """
    session = auth.get_session(settings)
    return client._with_relogin(session, settings, lambda: lookup.find_category(session, settings, num, refresh=refresh))


def submit_problem(
    settings: Settings,
    topic: str,
    num: int,
    *,
    push: bool = False,
    message: str | None = None,
    target: tuple[str, str, str, str] | None = None,
    progress: ProgressCb | None = None,
) -> SubmitOutcome:
    """{topic}/{num}/{num}.py 를 SWEA 에 제출 → 채점 결과. push=True 이고 Pass 면 push_problem 까지.

    호출 전에 사용자 확인 필수 (제출 횟수 1회 소모). 제출 불가·서버 오류는 SubmitError, 오답은 예외 없이 passed=False.
    """
    try:
        problem_dir = storage.resolve_problem_dir(settings.root, topic, num)
    except ValueError as e:
        raise InvalidInput(str(e)) from e
    source = submit.read_solution(problem_dir, num)
    prepared, notes = submit.prepare_source(source)
    for n in notes:
        _emit(progress, f"[알림] {n}")

    _emit(progress, "로그인 세션 확인")
    session = auth.get_session(settings)
    _emit(progress, f"문제 번호 {num} 로 찾는 중")
    if target is None:
        cid, cat_type, cat_id, context_label = lookup.find_category(session, settings, num)
    else:
        cid, cat_type, cat_id, context_label = target
    _emit(progress, f"제출 대상: {context_label}")

    def run() -> SubmitResult:
        ctx = submit.get_context(session, settings, cid, cat_type, cat_id)
        _emit(progress, f"컴파일 확인: {ctx.title or cid}")
        submit.compile_source(session, ctx, prepared)
        _emit(progress, "제출 중 (채점 대기)")
        return submit.submit_source(session, ctx, prepared)

    result = client._with_relogin(session, settings, run)
    _emit(progress, f"채점 결과: {result.summary} ({context_label})")
    _save_last_submit(settings, num, cid, cat_type, cat_id, result)
    outcome = SubmitOutcome(result, None, notes, cid, cat_type, cat_id)
    # AI 코치 오답 횟수 기록 (M17). 채점이 끝난 제출만 센다. 실패해도 제출 결과·CLI 출력은 그대로
    prev_record = coach.get_record(settings, num) if settings.growth else None  # 성장 기록의 wb (이번 제출 직전 오답 누적)
    outcome.coach = coach.record_submit(settings, num, topic, read_skeleton_title(problem_dir / f"{num}.py") or "", result)
    _record_growth_submit(settings, num, topic, result, prev_record)
    if push and result.passed:
        if settings.auto_push_scope == "root":
            # 루트 전체 범위는 sync_now 로 (예외 없이 note 반환)
            try:
                pd = storage.resolve_problem_dir(settings.root, topic, num)
                outcome.git = sync_now(settings, reason="pass", problem_dir=pd, scope="root", progress=progress)
            except Exception as e:  # noqa: BLE001 — 자동 경로는 제출 결과를 덮지 않는다
                log.debug("자동 동기화(root) 실패: %s", e)
        else:
            outcome.git = push_problem(settings, topic, num, message=message, push=True, progress=progress)
    return outcome


def _record_growth_submit(settings: Settings, num: int, topic: str, result: SubmitResult, prev_record: coach.ProblemRecord | None) -> None:
    """성장 기록의 제출 이벤트 (M19). 실패해도 예외 없음 — 제출 결과·CLI 출력·종료 코드는 그대로."""
    if not settings.growth:
        return
    try:
        res = coach.classify(result.passed, result.summary, result.run_error, result.timed_out)
        growth.record_submit(settings, num, topic, res, prev_record.wrong_count if prev_record else 0, at=growth.now())
    except Exception as e:  # noqa: BLE001
        log.warning("성장 기록 실패: %s", e)
    if result.passed:  # 풀이 잔디 (M20): 앱으로 낸 SWEA Pass
        _record_solved(settings, topic, num, "swea")
    else:  # 샘플만 맞고 SWEA 에서 틀린 문제는 로컬 통과 기록을 걷어낸다
        solved.retract_local(settings, num)


def _record_solved(settings: Settings, topic: str, num: int, via: str) -> None:
    """풀이 잔디에 그날 Pass 1건 (M20). 성장 기록이 꺼져 있으면 기록하지 않는다. 실패해도 예외 없음."""
    if not settings.growth:
        return
    try:
        title = read_skeleton_title(settings.root / topic / str(num) / f"{num}.py") or ""
        solved.record(settings, num, topic, title, via, at=growth.now())
    except Exception as e:  # noqa: BLE001
        log.warning("풀이 잔디 기록 실패: %s", e)


def check_problem(settings: Settings, problem_dir: Path, timeout: float = checker.DEFAULT_TIMEOUT, on_start=None) -> checker.CheckResult:
    """로컬 검증 (checker.run_and_compare) + 통과하면 풀이 잔디에 기록 (M20). CLI `check` 와 GUI 검증이 공통으로 거친다."""
    res = checker.run_and_compare(problem_dir, settings, timeout, on_start=on_start) if on_start else checker.run_and_compare(problem_dir, settings, timeout)
    if res.passed and not res.cancelled:
        pd = Path(problem_dir)
        try:
            _record_solved(settings, pd.parent.relative_to(settings.root).as_posix(), int(pd.name), "local")
        except (ValueError, OSError):
            pass  # 루트 밖 폴더·숫자가 아닌 폴더명은 기록하지 않는다
    return res


LAST_SUBMIT_FILE = "last_submit.json"


def _save_last_submit(settings: Settings, num: int, cid: str, cat_type: str, cat_id: str, result: SubmitResult) -> None:
    """진단용: 마지막 제출 요청의 category 와 서버 응답(JSON) 을 config_dir 에 남긴다. 쿠키·비밀번호 없음."""
    try:
        payload = {"at": datetime.now().isoformat(timespec="seconds"), "num": num, "contestProbId": cid,
                   "categoryType": cat_type, "categoryId": cat_id, "passed": result.passed, "summary": result.summary,
                   "response": result.raw}
        (settings.config_dir / LAST_SUBMIT_FILE).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log.debug("last_submit.json 쓰기 실패: %s", e)


def logout(config_dir: Path, all_: bool = False) -> list[str]:
    """session.json, login_state.json 삭제. all_ 이면 .env 와 keyring 비밀번호도. 삭제한 항목 이름 반환."""
    config_dir = Path(config_dir)
    removed: list[str] = []
    if all_:
        user_id = (config.read_env_file(config_dir).get("SWEA_ID") or "").strip()
        if user_id and config.delete_password(user_id):
            removed.append(f"자격 증명({user_id})")
    targets = [config_dir / config.SESSION_FILE_NAME, config_dir / config.LOGIN_STATE_FILE_NAME]
    if all_:
        targets.append(config_dir / config.ENV_FILE_NAME)
        if catalog.clear(config_dir):  # content_cache.clear 가 빈 cache/ 폴더를 지우므로 먼저 (M24)
            removed.append("문제 목록 캐시")
        if problem_types.clear(config_dir):  # 풀이 유형 캐시도 같은 cache/ 아래 (M24.1)
            removed.append("풀이 유형 캐시")
        if content_cache.clear(config_dir / config.CACHE_DIR_NAME):
            removed.append("지문 캐시")
        if coach.clear(config_dir):
            removed.append("AI 코치 기록")
    for path in targets:
        try:
            path.unlink()
            removed.append(path.name)
        except FileNotFoundError:
            pass
    return removed


# --- AI 코치 (M17) ---------------------------------------------------------------------


@dataclass
class CoachAnswer:
    kind: str  # review | hint | solution | ping
    markdown: str  # hint 는 1..n 단계 합본 (누적 표시용)
    engine: str = ""  # 표시용 엔진 이름 (GPT (Codex) / Claude (Claude Code))
    engine_key: str = ""  # "codex" | "claude"
    level: int = 0  # hint 단계 (그 외 0)
    max_level: int = 0
    from_cache: bool = False
    cancelled: bool = False
    notes: list[str] = field(default_factory=list)
    review_due: date | None = None  # solution 후 복습 예정일
    elapsed: float = 0.0
    code: str = ""  # solution: 정답 코드 블록 ([복사] 용, 없으면 "")


@dataclass
class CoachFailure:
    """엔진 1개의 실패 (부분 실패를 예외 없이 결과에 담는다)."""

    code: str  # missing | failed | timeout
    title: str
    hint: str = ""
    stderr: str = ""
    argv: list[str] = field(default_factory=list)


@dataclass
class EngineOutcome:
    """엔진 1개의 결과: answer 또는 failure (또는 취소)."""

    engine: str  # 키
    label: str
    answer: CoachAnswer | None = None
    failure: CoachFailure | None = None
    cancelled: bool = False
    error: Exception | None = field(default=None, repr=False, compare=False)  # 원본 예외 (ask_coach 래퍼가 재발생)


@dataclass
class CoachResult:
    kind: str
    outcomes: list[EngineOutcome] = field(default_factory=list)  # codex, claude 순 (실행 대상 + 미설치)
    hint_done: int = 0  # 요청 후 대상 엔진들의 받은 힌트 단계 수 중 최소 (코치 바용)
    review_due: date | None = None  # solution 성공 시 복습 예정일
    growth_tip: str | None = None  # 같은 약점이 3번 연속 지적됐을 때의 고정 문구 한 줄 (M19, 없으면 None)

    @property
    def cancelled(self) -> bool:
        return any(o.cancelled for o in self.outcomes)

    @property
    def succeeded(self) -> list[EngineOutcome]:
        return [o for o in self.outcomes if o.answer is not None and not o.cancelled]

    @property
    def all_failed(self) -> bool:
        """답이 하나도 없고 취소도 아닌 경우 (전부 실패·미설치)."""
        return bool(self.outcomes) and not self.cancelled and not self.succeeded


@dataclass
class EngineStatus:
    engines: list[ai_engine.EngineInfo]
    api_keys: list[str]  # 설정된 API 키 환경변수 이름 (경고용)


def detect_engines(settings: Settings | None = None) -> EngineStatus:
    """설치된 AI 엔진과 버전 (설정 페이지·연결 테스트). --version 을 실행하므로 워커에서 호출한다."""
    return EngineStatus(ai_engine.detect(), ai_engine.api_key_env())


def resolve_engine(settings: Settings) -> ai_engine.EngineInfo:
    """단일 모드(auto/codex/claude) 전용 엔진. both 면 ValueError — GUI 는 resolve_engines 를 쓴다."""
    return ai_engine.resolve(settings.ai_engine)


def resolve_engines(settings: Settings) -> ai_engine.EngineSelection:
    """설정(auto/codex/claude/both)에 따른 실행 대상 엔진. 경로 존재만 확인 (프로세스 기동 없음). 하나도 없으면 AiEngineMissing."""
    return ai_engine.resolve_all(settings.ai_engine)


def get_coach_record(settings: Settings, num: int) -> coach.ProblemRecord | None:
    return coach.get_record(settings, num)


def hint_level(settings: Settings, topic: str, num: int) -> int:
    """현재 풀이 코드 기준 대상 엔진들이 받은 힌트 단계 수 중 최소 (0~3). 엔진이 없거나 파일을 읽지 못하면 0."""
    try:
        keys = [e.name for e in resolve_engines(settings).engines]
        code = submit.read_solution(storage.resolve_problem_dir(settings.root, topic, num), num)
        cache = coach.load_answers(settings, num, code)
        return min(len(cache.slot(k).hints) for k in keys)
    except (SweaFetchError, ValueError, OSError):
        return 0


def review_items(settings: Settings, today: date | None = None) -> list[coach.ReviewItem]:
    return coach.review_items(settings, today)


def due_count(settings: Settings, today: date | None = None) -> int:
    return coach.due_count(settings, today)


# --- 문제별 상태 (M22 최근 탭 상태 칩, 스펙 §17.12) --------------------------------------------------

STATUS_LABELS = {"pass": "Pass", "wrong": "오답", "timeout": "시간 초과", "runtime_error": "런타임 오류", "none": "미제출"}
STATUS_ORDER = ("pass", "wrong", "timeout", "runtime_error", "none")  # 요약 줄 순서


@dataclass(frozen=True)
class ProblemStatus:
    """문제 1건의 상태. key ∈ STATUS_ORDER, label = 칩 글자, detail = 툴팁용 세부("SWEA Pass"·"로컬 Pass" 등),
    review_tag = (글자, 톤) — 톤 "due"(도래·지남) | "upcoming"(예정). 복습 태그는 상태와 독립이다."""

    key: str
    label: str
    detail: str = ""
    review_tag: tuple[str, str] | None = None
    last_submit: str = ""  # "MM-DD HH:MM" (마지막 제출 — 툴팁용, 기록 없으면 "")


def _parse_iso(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _solved_not_older(solved_at: str, submit_at: str) -> bool:
    """solved 기록 시각 ≥ 마지막 제출 시각? 제출 시각이 없거나 읽을 수 없으면 solved 가 더 새롭다고 본다."""
    a, b = _parse_iso(solved_at), _parse_iso(submit_at)
    if a is None or b is None:
        return True
    try:
        return a >= b
    except TypeError:  # naive / aware 혼용
        return a.replace(tzinfo=None) >= b.replace(tzinfo=None)


def review_tag_of(review: "coach.ReviewItem | None") -> tuple[str, str] | None:
    if review is None:
        return None
    n = review.overdue_days
    if n < 0:
        return f"복습 {-n}일 뒤", "upcoming"
    return ("복습 오늘" if n == 0 else f"복습 {n}일 지남"), "due"


def problem_status(
    rec: "coach.ProblemRecord | None",
    solved_latest: "solved.SolvedItem | None",
    review: "coach.ReviewItem | None" = None,
) -> ProblemStatus:
    """문제 번호 단위 상태 판정 (순수 함수, 스펙 §17.12).

    1. solved 기록이 있고 (rec 없음 | rec 가 pass | rec 가 pass 아니지만 solved 가 마지막 제출보다 새롭거나 같음) → Pass
    2. rec.last_result 가 wrong / timeout / runtime_error → 각각
    3. rec.last_result == "pass" 인데 solved 기록이 없음(400일 경과·백필 누락) → Pass
    4. 그 외(기록 없음, 로컬 검증 실패는 기록이 남지 않음) → 미제출
    복습 태그는 별개로 붙는다.
    """
    tag = review_tag_of(review)
    last = rec.last_result if rec is not None else ""
    when = _parse_iso(rec.last_submit_at) if rec is not None else None
    sub = when.strftime("%m-%d %H:%M") if when else ""
    if solved_latest is not None and (rec is None or last == "pass" or last not in ("wrong", "timeout", "runtime_error") or _solved_not_older(solved_latest.at, rec.last_submit_at)):
        detail = {"swea": "SWEA Pass", "local": "로컬 Pass"}.get(solved_latest.via, "Pass")
        return ProblemStatus("pass", STATUS_LABELS["pass"], detail, tag, sub)
    if last in ("wrong", "timeout", "runtime_error"):
        return ProblemStatus(last, STATUS_LABELS[last], STATUS_LABELS[last], tag, sub)
    if last == "pass":
        return ProblemStatus("pass", STATUS_LABELS["pass"], "Pass", tag, sub)
    return ProblemStatus("none", STATUS_LABELS["none"], "아직 제출·검증하지 않음", tag, sub)


def problem_statuses(settings: Settings, nums: Sequence[int]) -> dict[int, ProblemStatus]:
    """번호별 상태 (최근 탭용). solved.json · coach/records.json · 복습 일정을 1회씩 읽는다 (파일 3개, UI 스레드 가능).
    어떤 파일이든 읽기에 실패하면 빈 dict — 상태는 부가 정보라 칩만 숨기고 표는 정상 표시한다."""
    try:
        days = solved.load(settings)
        records = coach._load_records(settings)
        reviews = {i.num: i for i in coach.review_items(settings)}
        latest: dict[int, solved.SolvedItem] = {}
        for d in sorted(days):
            for it in days[d]:  # 날짜 오름차순·날 안 시각순 → 마지막이 가장 늦은 항목
                latest[it.num] = it
        return {n: problem_status(records.get(str(int(n))), latest.get(int(n)), reviews.get(int(n))) for n in nums}
    except Exception:  # noqa: BLE001 — 손상·권한 등 무엇이든 상태 표시만 포기
        log.warning("문제 상태를 읽지 못했습니다", exc_info=True)
        return {}


def dismiss_offer(settings: Settings, num: int) -> None:
    coach.dismiss_offer(settings, num)


def dismiss_review(settings: Settings, num: int) -> None:
    coach.dismiss_review(settings, num)


def clear_coach(config_dir: Path) -> int:
    """AI 코치 기록(응답 캐시·오답 횟수·복습 일정) 삭제. 지운 파일 수."""
    return coach.clear(Path(config_dir))


def _read_sample(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            data = f.read(64 * 1024)
    except OSError:
        return ""
    return ai_prompts.clip_sample(storage.normalize_text(data))


def _gather_statement(settings: Settings, topic: str, num: int, progress: ProgressCb | None) -> tuple[str, str, list[str]]:
    """(지문 텍스트, 제목, notes). 앱 캐시 우선, 없으면 지문만 1회 fetch (저장·캐시 기록 없음), 실패하면 지문 없이."""
    cached = content_cache.load(settings, num)
    if cached is not None:
        return ai_prompts.statement_text(cached.content), cached.title, []
    _emit(progress, "지문 가져오는 중")
    try:
        oc = fetch_problem(settings, str(num), topic, FetchOptions(dry_run=True, skeleton_only=True, with_content=True))
        if oc.content is not None:
            return ai_prompts.statement_text(oc.content), oc.info.title, []
    except Exception as e:  # noqa: BLE001 — 지문 없이도 진행 (네트워크·로그인 문제로 코치를 막지 않는다)
        log.debug("코치용 지문 가져오기 실패: %s", e)
    return "", "", ["지문 없이 코드만으로 답했습니다"]


_HINT_TITLE_RE = re.compile(r"\A\s*#{1,6}[^\n]*힌트[^\n]*\n+")


def _merge_hints(hints: list[dict]) -> str:
    """단계별 힌트 합본. AI 가 스스로 붙인 "# 힌트 1단계…" 제목은 앱 제목과 겹치므로 뺀다."""
    return "\n\n".join(
        f"### 힌트 {h.get('level', i)}단계\n\n{_HINT_TITLE_RE.sub('', h['markdown'], count=1)}" for i, h in enumerate(hints, 1)
    )




_CACHE_LOCK = threading.Lock()  # 응답 캐시 read-modify-write 직렬화 (두 엔진 결과가 거의 동시에 저장된다)


def _failure_of(e: Exception, kind: str) -> CoachFailure:
    if isinstance(e, AiError):
        argv = list(getattr(e, "argv", None) or [])
        if kind == "ping" and argv:  # 옵션 오류를 사용자가 바로 제보할 수 있게 실행 명령줄을 함께 보여준다 (프롬프트 제외)
            e.hint = f"{e.hint}\n\n실행한 명령: {' '.join(argv)}"
        return CoachFailure(e.code, str(e), e.hint, getattr(e, "stderr", "") or "", argv)
    return CoachFailure("failed", f"내부 오류: {e}", "다시 시도하세요")


def _missing_failure(key: str) -> CoachFailure:
    return CoachFailure("missing", f"{ai_engine.CLI_NAMES[key]} 를 찾지 못했습니다", ai_engine.install_hint((key,)))


def _run_parallel(items: list[ai_engine.EngineInfo], fn: Callable[[ai_engine.EngineInfo], EngineOutcome], done: Callable[[EngineOutcome], None]) -> None:
    """엔진당 스레드 1개로 fn 을 실행하고, 끝나는 순서대로 호출 스레드에서 done(outcome) 을 부른다."""
    with ThreadPoolExecutor(max_workers=len(items), thread_name_prefix="coach") as pool:
        futures = [pool.submit(fn, e) for e in items]
        for fut in as_completed(futures):
            done(fut.result())  # fn 은 예외를 outcome 으로 바꿔 돌려준다


def ask_coach_multi(
    settings: Settings,
    kind: str,
    topic: str = "",
    num: int = 0,
    *,
    submit_summary: str = "",
    run_error: str = "",
    execution_time: str | None = None,
    progress: ProgressCb | None = None,
    on_start: Callable[[str, object], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    on_engine_done: Callable[[EngineOutcome], None] | None = None,
    force_new: bool = False,
    engines: Sequence[str] | None = None,
) -> CoachResult:
    """AI 코치 요청 1건을 대상 엔진 전부에 동시에 보낸다 (kind = review | hint | solution | ping). M18.

    호출 전 사용자 동의 필수 (프롬프트에 코드·지문이 포함되어 외부 서비스로 전송됨). 이 함수는 동의를 묻지 않는다.
    엔진이 하나도 없으면 자료 수집 전에 AiEngineMissing. engines 로 대상을 좁힐 수 있다 (개별 [다시 받기]).
    엔진별 실패(미설치·타임아웃·실행 실패)는 예외 없이 outcome.failure 로 담고 다른 엔진 결과는 유지한다.
    on_engine_done(outcome) 은 outcome 이 확정될 때마다 호출 스레드에서 호출된다. on_start(engine_key, proc) 는 프로세스가 뜬 직후.
    힌트 단계는 대상 엔진이 공통으로 진행한다 (받은 단계 최소 + 1). 앞선 엔진은 캐시에서 그 단계까지만 보여준다.
    정답 풀이는 화면 표시용으로만 돌려준다 — {num}.py 등 루트 폴더에는 절대 쓰지 않는다 (기록은 config_dir/coach/).
    """
    if kind not in ai_prompts.COACH_KINDS:
        raise ValueError(f"알 수 없는 종류: {kind}")
    sel = resolve_engines(settings)
    targets, missing = list(sel.engines), list(sel.missing)
    if engines is not None:
        want = set(engines)
        targets, missing = [e for e in targets if e.name in want], [k for k in missing if k in want]
    outcomes: dict[str, EngineOutcome] = {}

    def done(o: EngineOutcome) -> None:
        outcomes[o.engine] = o
        if on_engine_done is not None:
            on_engine_done(o)

    def finish(**extra) -> CoachResult:
        return CoachResult(kind, [outcomes[k] for k in ai_engine.ENGINE_NAMES if k in outcomes], **extra)

    def start_hook(key: str):
        return (lambda proc: on_start(key, proc)) if on_start is not None else None

    def cancelled_now() -> bool:
        return bool(is_cancelled is not None and is_cancelled())

    for key in missing:
        done(EngineOutcome(key, ai_engine.ENGINE_LABELS[key], failure=_missing_failure(key)))
    if not targets:
        return finish()

    if kind == "ping":
        _emit(progress, f"{' · '.join(e.short_label for e in targets)} 연결 테스트")

        def ping_one(engine: ai_engine.EngineInfo) -> EngineOutcome:
            try:
                res = ai_engine.run(engine, ai_prompts.build_prompt("ping"), on_start=start_hook(engine.name), is_cancelled=is_cancelled)
            except Exception as e:  # noqa: BLE001 — 한 엔진의 예외가 다른 엔진을 죽이지 않는다
                if not isinstance(e, AiError):
                    log.exception("코치 내부 오류 (%s)", engine.name)
                return EngineOutcome(engine.name, engine.label, failure=_failure_of(e, kind), error=e)
            if res.cancelled:
                return EngineOutcome(engine.name, engine.label, cancelled=True)
            return EngineOutcome(engine.name, engine.label, CoachAnswer("ping", res.text, engine.label, engine.name, elapsed=res.elapsed))

        _run_parallel(targets, ping_one, done)
        return finish()

    try:
        problem_dir = storage.resolve_problem_dir(settings.root, topic, num)
    except ValueError as e:
        raise InvalidInput(str(e)) from e
    code = submit.read_solution(problem_dir, num)
    with _CACHE_LOCK:
        cache = coach.load_answers(settings, num, code)

    # 1) 캐시 적중 판단 (엔진별 슬롯)
    level = 0
    call: list[ai_engine.EngineInfo] = []
    prev_hints: dict[str, list[str]] = {}
    if kind == "hint":
        hints = {e.name: list(cache.slot(e.name).hints) for e in targets}
        if force_new:
            for h in hints.values():
                if h:
                    h.pop()  # [다시 받기]: 마지막 단계만 다시
        level = min(min(len(h) for h in hints.values()) + 1, ai_prompts.MAX_HINT_LEVEL)
        for e in targets:
            h = hints[e.name]
            if len(h) >= level:
                answer = CoachAnswer("hint", _merge_hints(h[:level]), e.label, e.name, level, ai_prompts.MAX_HINT_LEVEL, from_cache=True)
                done(EngineOutcome(e.name, e.label, answer))
            else:
                call.append(e)
                prev_hints[e.name] = [x["markdown"] for x in h]
    else:
        for e in targets:
            entry = getattr(cache.slot(e.name), kind)
            if entry and not force_new:
                answer = CoachAnswer(kind, entry["markdown"], e.label, e.name, from_cache=True)
                if kind == "solution":
                    answer.code = ai_prompts.first_code_block(entry["markdown"]) or ""
                done(EngineOutcome(e.name, e.label, answer))
            else:
                call.append(e)

    # 2) 엔진 호출 (자료 수집은 1회, 두 엔진이 공유)
    fresh = 0
    recorded: list[str] = []  # 성장 이벤트를 남긴 엔진 (팁 판정 여부)
    if call:
        statement, title, notes = _gather_statement(settings, topic, num, progress)
        if cancelled_now():
            for e in call:
                done(EngineOutcome(e.name, e.label, cancelled=True))
            call = []
    if call:
        base = dict(
            num=num,
            title=title or read_skeleton_title(problem_dir / f"{num}.py") or "",
            statement=statement,
            sample_input=_read_sample(problem_dir / settings.input_name),
            sample_output=_read_sample(problem_dir / settings.output_name),
            code=re.sub(r"\n{3,}", "\n\n", submit.strip_io_lines(code)),  # 제출 때 빠지는 로컬 입력 줄은 AI 에게도 안 보낸다
            summary=submit_summary,
            run_error=run_error,
            execution_time=execution_time,
            level=level or 1,
            growth=settings.growth,
        )
        _emit(progress, f"{' · '.join(e.short_label for e in call)} 에게 묻는 중")

        def run_one(engine: ai_engine.EngineInfo) -> EngineOutcome:
            key, label = engine.name, engine.label
            try:
                prompt = ai_prompts.build_prompt(kind, previous_hints=prev_hints.get(key, []), **base)
                res = ai_engine.run(engine, prompt, on_start=start_hook(key), is_cancelled=is_cancelled)
                if res.cancelled or cancelled_now():
                    return EngineOutcome(key, label, cancelled=True)
                # 성장 기록용 profile 블록은 clean_titles/filter_hint/first_code_block 보다 먼저 떼어 표시·캐시·다음 힌트 어디에도 남기지 않는다.
                # SWEA_GROWTH=0 이어도 (AI 가 요청하지 않은 블록을 내는 경우 대비) 항상 제거한다
                raw_text, parsed = growth_tags.extract(res.text, kind)
                text = ai_prompts.clean_titles(raw_text)
                my_notes = list(notes)
                if res.truncated:
                    my_notes.append("응답이 너무 길어 일부만 표시합니다")
                if kind == "hint":
                    text, removed = ai_prompts.filter_hint(text)
                    if removed:
                        my_notes.append("긴 코드 블록을 제거했습니다")
                    if not text.strip():
                        raise AiError("힌트 응답이 비어 있습니다", hint="다시 시도하세요")
                elif not text.strip():
                    raise AiError("응답이 비어 있습니다", hint="다시 시도하세요")
                entry = {"markdown": text, "at": datetime.now().isoformat(timespec="seconds")}
                answer = CoachAnswer(kind, text, label, key, elapsed=res.elapsed, notes=my_notes)
                with _CACHE_LOCK:  # 재로드 -> 이 엔진 슬롯만 수정 -> 저장 (다른 엔진 결과를 덮어쓰지 않는다)
                    fresh_cache = coach.load_answers(settings, num, code)
                    slot = fresh_cache.slot(key)
                    if kind == "hint":
                        slot.hints = slot.hints[: level - 1] + [{"level": level, **entry}]
                        answer.markdown = _merge_hints(slot.hints)
                        answer.level, answer.max_level = level, ai_prompts.MAX_HINT_LEVEL
                    elif kind == "review":
                        slot.review = entry
                    else:
                        slot.solution = entry
                        answer.code = ai_prompts.first_code_block(text) or ""
                    coach.save_answers(settings, fresh_cache)
                if settings.growth:  # 새로 받은 응답만 (캐시 적중은 이벤트를 만들지 않는다). 힌트 1단계는 태그를 요청하지 않으므로 ok=false
                    try:
                        if growth.record_coach(settings, num, topic, kind, level, key, parsed if growth_tags.wants_tags(kind, level) else None, at=growth.now()):
                            recorded.append(key)
                    except Exception as e:  # noqa: BLE001
                        log.warning("성장 기록 실패: %s", e)
                return EngineOutcome(key, label, answer)
            except Exception as e:  # noqa: BLE001 — 한 엔진의 예외가 다른 엔진을 죽이지 않는다
                if cancelled_now():
                    return EngineOutcome(key, label, cancelled=True)
                if not isinstance(e, AiError):
                    log.exception("코치 내부 오류 (%s)", key)
                return EngineOutcome(key, label, failure=_failure_of(e, kind), error=e)

        _run_parallel(call, run_one, done)
        fresh = sum(1 for e in call if outcomes[e.name].answer is not None)

    # 3) 정답 풀이: 열람 처리(오답 누적 리셋 + 복습 예약)는 새로 받은 성공이 있을 때 1회만
    review_due = None
    if kind == "solution" and any(o.answer is not None for o in outcomes.values()):
        rec = coach.mark_solution_viewed(settings, num, settings.review_days) if fresh else coach.get_record(settings, num)
        if rec is not None and rec.review_due:
            review_due = date.fromisoformat(rec.review_due)
        for o in outcomes.values():
            if o.answer is not None:
                o.answer.review_due = review_due
    with _CACHE_LOCK:
        final = coach.load_answers(settings, num, code)
    hint_done = min(len(final.slot(e.name).hints) for e in targets)
    tip = None
    if recorded and not cancelled_now():
        tip = growth.pending_tip(settings, growth.now())
    return finish(hint_done=hint_done, review_due=review_due, growth_tip=tip)


def ask_coach(
    settings: Settings,
    kind: str,
    topic: str = "",
    num: int = 0,
    *,
    submit_summary: str = "",
    run_error: str = "",
    execution_time: str | None = None,
    progress: ProgressCb | None = None,
    on_start: Callable | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    force_new: bool = False,
) -> CoachAnswer:
    """단일 엔진 호환 래퍼: ask_coach_multi 를 엔진 1개로 호출하고 실패는 원래 예외로 다시 던진다 (GUI 는 ask_coach_multi 를 쓴다).

    설정이 both 면 codex 우선 첫 설치 엔진 1개만 쓴다. 호출 전 사용자 동의 필수. 취소는 예외 없이 CoachAnswer.cancelled=True.
    """
    if kind not in ai_prompts.COACH_KINDS:
        raise ValueError(f"알 수 없는 종류: {kind}")
    engine = resolve_engines(settings).engines[0]
    result = ask_coach_multi(
        settings, kind, topic, num,
        submit_summary=submit_summary, run_error=run_error, execution_time=execution_time, progress=progress,
        on_start=(lambda _key, proc: on_start(proc)) if on_start is not None else None,
        is_cancelled=is_cancelled, force_new=force_new, engines=[engine.name],
    )
    o = result.outcomes[0]
    if o.cancelled:
        return CoachAnswer(kind, "", engine.label, engine.name, cancelled=True)
    if o.answer is None:
        raise o.error if o.error is not None else AiError(o.failure.title if o.failure else "AI 코치 실패")
    return o.answer


# --- 성장 기록 (M19) -------------------------------------------------------------------
# 조회 함수는 파일 읽기 전용이라 UI 스레드에서 불러도 된다 (이벤트 파일이 커져 느려지면 워커로). 시각은 growth.now() (테스트가 대체).

GrowthOverview = growth.GrowthOverview
GrowthReport = growth.GrowthReport
ConsentCheck = Callable[[str], bool]


@dataclass
class GrowthRunResult:
    """generate_growth 결과. 예외는 던지지 않고 blocked / failure 로 담는다."""

    new_weeks: list[date] = field(default_factory=list)  # 이번 호출에서 새로 확정된 주 (월요일)
    commented_week: date | None = None  # AI 코멘트를 새로 저장한 주
    blocked: str | None = None  # off | no_engine | needs_consent | low_data (호출하지 않았고 시도 횟수도 쓰지 않음)
    failure: CoachFailure | None = None  # 코멘트 생성 실패 (리포트 통계는 이미 저장됨)
    cancelled: bool = False
    engine_key: str = ""  # blocked 가 needs_consent 일 때 동의가 필요한 엔진


def growth_overview(settings: Settings, now: datetime | None = None) -> growth.GrowthOverview:
    """이번 주 진행 중 요약 + 확정 리포트 목록(최신순) + 최근 8주 Pass 문제 수 + 미확인 수."""
    return growth.overview(settings, now)


def growth_report(settings: Settings, week_start: date, now: datetime | None = None) -> growth.GrowthReport:
    """한 주의 리포트 (확정 스냅샷 또는 이번 주 즉석 계산). 8주 시계열과 판정·코멘트 상태 포함."""
    return growth.report(settings, week_start, now)


def growth_due(settings: Settings, now: datetime | None = None) -> bool:
    """만들 스냅샷 또는 자동 코멘트 후보가 있는가 (파일 확인만 — 30분 틱용)."""
    if not settings.growth:
        return False
    return growth.is_due(settings, now, comment=settings.growth_comment)


def growth_unseen_count(settings: Settings) -> int:
    """아직 성장 탭에서 보지 않은 확정 리포트 수 (상태바 배지용)."""
    return growth.unseen_count(settings) if settings.growth else 0


def growth_mark_seen(settings: Settings, week_start: date, now: datetime | None = None) -> None:
    growth.mark_seen(settings, week_start, now)


def growth_comment_engine(settings: Settings) -> ai_engine.EngineInfo | None:
    """주간 코멘트에 쓸 엔진 (설정 auto/codex/claude 를 따르고 both 는 설치된 첫 엔진 = Codex 우선). 없으면 None (폴백 없음)."""
    try:
        return ai_engine.resolve_all(settings.ai_engine).engines[0]
    except (AiError, IndexError):
        return None


def growth_comment_blocker(settings: Settings, consent_ok: ConsentCheck, manual: bool = False) -> str | None:
    """성장 탭 안내 결정: "off" | "comment_off" | "no_engine" | "needs_consent" | None. manual 이면 자동 생성 설정은 무시한다."""
    if not settings.growth:
        return "off"
    if not manual and not settings.growth_comment:
        return "comment_off"
    engine = growth_comment_engine(settings)
    if engine is None:
        return "no_engine"
    if not consent_ok(engine.name):
        return "needs_consent"
    return None


def growth_solved(settings: Settings, now: datetime | None = None) -> dict[date, list[solved.SolvedItem]]:
    """풀이 잔디용 {날짜: [문제]} (M20). 첫 호출에서 기존 기록으로 백필한다. 성장 기록이 꺼져 있으면 빈 dict."""
    if not settings.growth:
        return {}
    solved.backfill(settings, now)
    solved_sync.sync_device_file(settings, today=now.date() if now else None)  # 동기화를 방금 켠 경우 기존 로컬 기록을 기기 파일로 옮긴다 (M23)
    return solved.load(settings)


def refresh_solved_remote(settings: Settings, *, force: bool = False) -> bool:
    """다른 기기의 잔디 기록을 원격에서 읽어 캐시에 반영 (M23, 백그라운드 워커용). 바뀌었으면 True. 예외 없음·10분 스로틀."""
    return solved_sync.refresh_remote(settings, force=force)


def clear_growth(config_dir: Path) -> int:
    """성장 기록(coach/profile: 이벤트·주간 리포트·팁 상태) 삭제. 지운 파일 수. AI 응답 캐시·복습 일정은 그대로."""
    return growth.clear(Path(config_dir))


def generate_growth(
    settings: Settings,
    *,
    now: datetime | None = None,
    consent_ok: ConsentCheck,
    on_start: Callable[[object], None] | None = None,
    on_begin: Callable[[date], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    on_stats: Callable[[list[date]], None] | None = None,
    on_comment: Callable[[date, str], None] | None = None,
    force_week: date | None = None,
) -> GrowthRunResult:
    """주간 리포트 확정(통계) + 주간 AI 코멘트 1건. 예외는 던지지 않고 결과에 담는다.

    호출 전 사용자 동의는 consent_ok(엔진 키) 콜백이 대신한다 — 이 함수(코어)는 동의를 모른다. 거짓이면 AI 를 호출하지 않는다.
    AI 로는 집계 숫자·카테고리 이름·판정 문장·기간만 보낸다 (growth.comment_payload 의 허용 키). 코드·지문·문제 번호/제목·주제명은 보내지 않는다.
    force_week: 수동 [코멘트 받기] — 자동 생성 설정·나이·시도 횟수 제한을 무시한다 (표본 조건은 유지).
    엔진은 설정(auto/codex/claude)을 따르고 both 는 설치된 첫 엔진 1개만. 고정 엔진이 없으면 폴백 없이 no_engine.
    on_stats(새 주) 는 스냅샷을 새로 만든 직후, on_begin(주) 는 엔진 호출 직전, on_start(proc) 는 프로세스가 뜬 직후, on_comment(주, 텍스트) 는 저장 직후.
    """
    result = GrowthRunResult()
    if not settings.growth:
        result.blocked = "off"
        return result
    stamp = now or growth.now()
    try:
        result.new_weeks = growth.build_missing_snapshots(settings, stamp)
        if result.new_weeks and on_stats is not None:
            on_stats(list(result.new_weeks))
        if force_week is None and not settings.growth_comment:
            return result
        snaps = growth.load_snapshots(settings)
        snap = growth.comment_candidate(snaps, stamp, force_week)
        if snap is None:
            if force_week is not None and force_week in snaps:
                result.blocked = "low_data"  # 표본이 적은 주는 수동으로도 AI 를 호출하지 않는다
            return result
        engine = growth_comment_engine(settings)
        if engine is None:
            result.blocked = "no_engine"
            return result
        if not consent_ok(engine.name):
            result.blocked, result.engine_key = "needs_consent", engine.name
            return result
        if is_cancelled is not None and is_cancelled():
            result.cancelled = True
            return result
        prev = snaps.get(snap.prev_week) if snap.prev_week else None
        prompt = ai_prompts.build_weekly_prompt(growth.comment_payload(snap, prev))
        if on_begin is not None:
            on_begin(snap.week_start)
        try:
            res = ai_engine.run(engine, prompt, on_start=on_start, is_cancelled=is_cancelled)
            if res.cancelled or (is_cancelled is not None and is_cancelled()):
                result.cancelled = True  # 취소는 상태 변경 없음
                return result
            text = growth.clean_comment(res.text)
            if not text:
                raise AiError("코멘트 응답이 비어 있습니다", hint="다시 받기를 눌러 보세요")
        except Exception as e:  # noqa: BLE001 — 통계는 이미 저장되어 있다. 코멘트만 실패로 남긴다
            if is_cancelled is not None and is_cancelled():
                result.cancelled = True
                return result
            if not isinstance(e, AiError):
                log.exception("성장 코멘트 내부 오류")
            result.failure = _failure_of(e, "weekly")
            growth.update_snapshot(settings, snap.week_start, comment_status="failed", comment_attempts=snap.comment_attempts + 1)
            return result
        comment = {"text": text, "engine": engine.label, "at": stamp.isoformat(timespec="seconds")}
        growth.update_snapshot(settings, snap.week_start, comment=comment, comment_status="ok")
        result.commented_week = snap.week_start
        if on_comment is not None:
            on_comment(snap.week_start, text)
    except Exception as e:  # noqa: BLE001
        log.exception("성장 기록 생성 내부 오류")
        result.failure = CoachFailure("failed", f"내부 오류: {e}", "다시 시도하세요")
    return result


# --- 오늘의 추천 (M24) -------------------------------------------------------------------
# catalog_status / recommend_today 는 파일 읽기 전용(네트워크·AI 없음). refresh_* / recommend_ai 는 워커에서만 부른다.
# 동의는 consent_ok 콜백이 대신한다 — 코어(recommend.py)는 동의를 모른다. 거짓이면 AI 를 호출하지 않는다.

Recommendation = recommend.Recommendation
RecommendResult = recommend.RecommendResult
CatalogStatus = catalog.CatalogStatus
CatalogError = catalog.CatalogError

AI_RECOMMEND_TIMEOUT = 120.0  # 코치(300초)보다 짧게: 선별은 짧은 JSON 하나
AI_MIN_TAGGED = 3  # 최근 28일 분류 그룹이 이보다 적으면 AI 를 부르지 않는다
AI_WINDOW_DAYS = 28
_PASSED_ATTEMPT: dict[str, datetime] = {}  # 정답 목록 시도 시각 (프로세스 안 1시간 스로틀 — 로그인 실패 재시도 루프 방지)


def recommend_enabled(settings: Settings) -> bool:
    return bool(settings.growth and settings.recommend)


def catalog_status(settings: Settings, now: datetime | None = None) -> catalog.CatalogStatus:
    """카탈로그 상태 (파일만 읽음, 네트워크 없음)."""
    return catalog.status(settings, now)


def refresh_catalog(
    settings: Settings,
    *,
    progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    force: bool = False,
    now: datetime | None = None,
    session=None,
    sleep: Callable[[float], None] = time.sleep,
) -> catalog.CatalogStatus:
    """공개 문제 목록 갱신 (네트워크 — 워커 전용). 갱신이 필요 없거나 실패 쿨다운이면 요청 없이 현재 상태를 돌려준다.

    force=True(수동 [새로 받기]/[다시 시도]) 는 TTL·실패 쿨다운을 무시하지만, 카탈로그가 이미 있으면 1시간 쿨다운은 지킨다
    (CatalogError code="cooldown"). 실패는 CatalogError 로 단일화한다 (네트워크 / 구조 변경 / 세션 / 취소).
    """
    stamp = growth._now(now)
    st = catalog.status(settings, stamp)
    if not recommend_enabled(settings):
        return st
    if force:
        if st.usable and st.manual_wait > 0:
            raise CatalogError(f"문제 목록은 {st.manual_wait // 60 + 1}분 뒤에 다시 받을 수 있습니다", code="cooldown")
    elif not st.auto_due:
        return st
    catalog.refresh(session if session is not None else catalog.anonymous_session(), settings, progress, is_cancelled, sleep, now=stamp)
    return catalog.status(settings, growth._now(now))


def refresh_passed(settings: Settings, *, is_cancelled: Callable[[], bool] | None = None, now: datetime | None = None, session=None,
                   sleep: Callable[[float], None] = time.sleep) -> int:
    """SWEA "내가 정답한 문제" 목록 갱신 (로그인 세션, 1일 TTL). 받은 개수 / 건너뜀(꺼짐·TTL·스로틀)=0 / 실패=-1 (예외 없음, 재시도 루프 없음).

    비명시 로그인(`explicit=False`)만 쓰므로 로그인 가드에 걸리면 조용히 "로그아웃" 상태(-1)로 취급한다 — 카드가 앱 기록만 썼다고 한 번 안내한다.
    """
    stamp = growth._now(now)
    if not recommend_enabled(settings) or catalog.PASSED_FILTER is None or not catalog.passed_stale(settings, stamp):
        return 0
    key = str(settings.config_dir)
    last = _PASSED_ATTEMPT.get(key)
    if last is not None and stamp - last < timedelta(hours=1):
        return 0
    _PASSED_ATTEMPT[key] = stamp
    try:
        sess = session if session is not None else auth.get_session(settings)
        nums = catalog.fetch_passed(sess, settings, catalog.load(settings), is_cancelled, sleep, now=stamp)
    except (SweaFetchError, OSError) as e:
        log.info("SWEA 정답 목록을 받지 못해 앱 기록만 사용합니다: %s", e)
        return -1
    except Exception:  # noqa: BLE001 — 부가 기능은 추천을 깨지 않는다
        log.exception("SWEA 정답 목록 내부 오류")
        return -1
    return len(nums)


@dataclass
class _RecCtx:
    """추천 계산에 쓰는 이미 읽은 이력 (파일 읽기 1회 분)."""

    cat: catalog.Catalog
    est: recommend.LevelEstimate
    facts: list[recommend.SolveFact]
    solved_nums: set[int]
    retry: list[recommend.RetryCand]
    events: list[growth.Event]
    used_swea_passed: bool = False
    first_day: dict[int, date] = field(default_factory=dict)  # 앱에 Pass 기록된 문제 {번호: 첫 Pass 날짜}
    titles: dict[int, str] = field(default_factory=dict)  # 카탈로그 + 푼 문제 제목 (유형 키워드·분류 입력용, 화면·AI 로 푼 문제 제목은 나가지 않는다)
    tcache: problem_types.TypeCache = field(default_factory=problem_types.TypeCache)
    types: dict[int, tuple[str, ...]] = field(default_factory=dict)  # {번호: 풀이 유형} AI 결과 > 제목 키워드
    counts: Counter = field(default_factory=Counter)  # {유형: 앱에 Pass 기록된 문제 수}
    known: frozenset = frozenset()  # 내가 풀어 본 유형 (폴더 이름은 증거가 아니다)


def _rec_context(settings: Settings, cat: catalog.Catalog, today: date, start_level: int | None) -> _RecCtx:
    days = solved.load(settings)
    first_day: dict[int, date] = {}
    for d in sorted(days):
        for it in days[d]:
            first_day.setdefault(it.num, d)
    events = growth.read_events(settings)
    pass_wb: dict[int, int] = {}
    for ev in events:  # 파일 순서 = 시간순: 그 문제의 첫 Pass 직전 오답
        if ev.t == "submit" and ev.res == "pass" and ev.num in first_day:
            pass_wb.setdefault(ev.num, ev.wb)
    records = coach._load_records(settings)
    unsolved: list[tuple[int, int, date | None]] = []
    for r in records.values():
        if r.last_result == "pass" or r.num in first_day or r.wrong_count < recommend.THRESH["hard_min_wb"]:
            continue
        try:
            when = datetime.fromisoformat(r.last_submit_at).date() if r.last_submit_at else None
        except ValueError:
            when = None
        unsolved.append((r.num, r.wrong_count, when))
    passed = catalog.load_passed(settings)[0] if catalog.PASSED_FILTER is not None else {}
    levels = {n: it.lv for n, it in cat.items.items() if it.lv}
    facts = recommend.facts_from_history(solved_first_day=first_day, pass_wb=pass_wb, unsolved=unsolved, swea_passed=passed, levels=levels)
    est = recommend.estimate_level(facts, today, start_level)
    solved_nums = set(first_day) | set(passed)
    retry = recommend.retry_candidates([(r.num, r.wrong_count, r.last_result) for r in records.values()], solved_nums)
    titles = {n: it.title for n, it in cat.items.items()}
    for d in days:
        for it in days[d]:
            titles.setdefault(it.num, it.title)
    tcache = problem_types.load(settings)
    types = {n: ty for n, ty in ((n, problem_types.effective_types(tcache, n, t)) for n, t in titles.items()) if ty}
    counts = problem_types.count_known(first_day, lambda n: types.get(n, ()))
    return _RecCtx(cat, est, facts, solved_nums, retry, events, bool(passed), first_day, titles, tcache, types, counts, frozenset(counts))


def _tagged_groups(events: list[growth.Event], stamp: datetime) -> int:
    cutoff = stamp - timedelta(days=AI_WINDOW_DAYS)
    return sum(1 for g in growth.group_coach([e for e in events if e.t == "coach" and e.at >= cutoff]) if g.ok)


def _ai_status_of(settings: Settings, ds: recommend.DaySet | None) -> str:
    if not settings.recommend_ai:
        return "off"
    return {"ok": "ok", "failed": "failed", "skipped": "skipped_low_data"}.get(ds.ai_status() if ds else "none", "none")


def _assemble(settings: Settings, ds: recommend.DaySet, ctx: _RecCtx, today: date, stamp: datetime, status: catalog.CatalogStatus) -> recommend.RecommendResult:
    items: list[recommend.Recommendation] = []
    for raw in ds.items:
        it = ctx.cat.items.get(raw["n"])
        if it is None:
            continue
        ty = problem_types.clean_ids(raw.get("ty")) or ctx.types.get(it.num, ())  # 세트에 저장된 유형 우선, 없으면 그 뒤에 알게 된 유형
        items.append(recommend.Recommendation(it.num, it.title, it.lv, it.pr, it.pa, raw["k"], raw["r"], raw["src"], it.num in ctx.solved_nums, ty))
    sources = {i.source for i in items}
    tagged = _tagged_groups(ctx.events, stamp)
    ai_status = _ai_status_of(settings, ds)
    if ai_status == "none" and tagged < AI_MIN_TAGGED:
        ai_status = "skipped_low_data"  # 호출 조건 미달을 카드가 바로 안내할 수 있게 (워커 없이)
    return recommend.RecommendResult(
        day=today, items=items, level=ctx.est, source=("mixed" if len(sources) > 1 else (sources.pop() if sources else "rule")),
        ai_status=ai_status, ai_engines=[str(e) for e in ds.ai.get("engines") or []], catalog=status,
        shuffle=ds.shuffle, used_swea_passed=ctx.used_swea_passed, weak_tagged=tagged, type_counts=dict(ctx.counts),
    )


def _remember(ds: recommend.DaySet, picks_nums: list[int], today: date) -> None:
    """보인 번호를 오늘/최근 노출 기록에 더한다."""
    for n in picks_nums:
        if n not in ds.day_shown:
            ds.day_shown.append(n)
        ds.recent_shown[str(n)] = today.isoformat()
    ds.recent_shown = recommend.prune_recent(ds.recent_shown, today)


def _new_set(ds: recommend.DaySet, ctx: _RecCtx, today: date, start: int, *, shuffle: int, keep_shown: bool) -> None:
    """ds 의 items 를 새로 만든다 (날짜 변경·[다른 추천]·시작 수준 변경). AI 순위가 있으면 cursor 부터 소비한다."""
    ai_ok = ds.ai_status() == "ok"
    build = recommend.build_set(
        ctx.cat.items, ctx.est, day=today, shuffle=shuffle, solved_nums=ctx.solved_nums, retry=ctx.retry,
        recent_shown=ds.recent_dates(), day_shown=list(ds.day_shown) if keep_shown else (),
        ai_picks=ds.ai_picks() if ai_ok else (), ai_cursor=int(ds.ai.get("cursor") or 0) if ai_ok else 0,
        types=ctx.types, known=ctx.known, type_counts=ctx.counts,
    )
    ds.shuffle, ds.level_c, ds.conf, ds.start = shuffle, ctx.est.level, ctx.est.confidence, start
    ds.items = recommend.items_of(build.picks)
    if ai_ok:
        ds.ai["cursor"] = int(ds.ai.get("cursor") or 0) + build.ai_used
    _remember(ds, [p.num for p in build.picks], today)


def recommend_today(
    settings: Settings,
    *,
    now: datetime | None = None,
    start_level: int | None = None,
    shuffle: bool = False,
    rebuild: bool = False,
) -> recommend.RecommendResult:
    """오늘의 추천 (규칙만, 네트워크·AI 없음). 오늘 저장된 세트가 있으면 그대로(제목·정답률은 최신값), 없으면 만들어 저장한다.

    shuffle=True 는 카운터를 올려 새 세트(이미 보인 번호 제외)를 만든다. 콜드 스타트 선택기(start_level)가 세트를 만들 때와 달라지면 다시 만든다.
    rebuild=True 는 풀이 유형 분류가 새로 끝났을 때 (M24.1): 아직 [다른 추천] 을 안 눌렀고 세트에 유형 미확인 칸이 있으면 새 유형 정보로 세트를 다시 만든다.
    카탈로그가 없으면 items=[] 와 catalog.usable=False. 설정이 꺼져 있으면 items=[] 와 ai_status="off".
    """
    stamp = growth._now(now)
    today = stamp.date()
    status = catalog.status(settings, stamp)
    cat = catalog.load(settings) if status.usable and recommend_enabled(settings) else None
    if cat is None:
        est = recommend.estimate_level([], today, start_level)
        return recommend.RecommendResult(day=today, items=[], level=est, ai_status="off" if not recommend_enabled(settings) else "none", catalog=status)
    ctx = _rec_context(settings, cat, today, start_level)
    start = recommend._clamp_level(start_level) if start_level else 0
    ds = recommend.load_day(settings)
    if ds is None or ds.date != today.isoformat():
        prev_recent = ds.recent_shown if ds is not None else {}
        ds = recommend.DaySet(today.isoformat(), recent_shown=recommend.prune_recent(prev_recent, today), ai={"status": "none"})
        _new_set(ds, ctx, today, start, shuffle=0, keep_shown=False)
        recommend.save_day(settings, ds)
    elif shuffle:
        _new_set(ds, ctx, today, start, shuffle=ds.shuffle + 1, keep_shown=True)
        recommend.save_day(settings, ds)
    elif rebuild and ds.shuffle == 0 and any(not r.get("ty") for r in ds.items if r["k"] != "retry"):
        ds.day_shown = []
        ds.recent_shown = {k: v for k, v in ds.recent_shown.items() if v != today.isoformat()}  # 오늘 처음 보인 세트는 "최근 노출" 이 아니다
        if ds.ai_status() == "ok":
            ds.ai["cursor"] = 0
        _new_set(ds, ctx, today, ds.start or start, shuffle=0, keep_shown=False)
        recommend.save_day(settings, ds)
    elif ctx.est.cold and ds.conf == "cold" and start and ds.start != start:  # 선택기를 바꿨다: 같은 셔플 번호로 다시 만든다
        ds.day_shown = []
        _new_set(ds, ctx, today, start, shuffle=ds.shuffle, keep_shown=False)
        recommend.save_day(settings, ds)
    else:
        missing = [raw for raw in ds.items if raw["n"] not in cat.items]
        if missing:  # 카탈로그에서 사라진 번호: 같은 시드로 다시 계산해 그 칸만 채운다
            fresh = recommend.build_set(
                cat.items, ctx.est, day=today, shuffle=ds.shuffle, solved_nums=ctx.solved_nums, retry=ctx.retry,
                recent_shown=ds.recent_dates(), day_shown=[n for n in ds.day_shown if n not in {r["n"] for r in ds.items}],
                types=ctx.types, known=ctx.known, type_counts=ctx.counts,
            ).picks
            have = {r["n"] for r in ds.items}
            kept = [r for r in ds.items if r["n"] in cat.items]
            for raw in missing:
                repl = next((p for p in fresh if p.num not in have and p.kind == raw["k"]), None) or next((p for p in fresh if p.num not in have), None)
                if repl is not None:
                    have.add(repl.num)
                    kept.extend(recommend.items_of([repl]))
            ds.items = kept
            _remember(ds, [r["n"] for r in kept], today)
            recommend.save_day(settings, ds)
    return _assemble(settings, ds, ctx, today, stamp, status)


def recommend_blocker(settings: Settings, consent_ok: ConsentCheck) -> str | None:
    """카드 안내 결정: "off" | "ai_off" | "no_engine" | "needs_consent" | None."""
    if not recommend_enabled(settings):
        return "off"
    if not settings.recommend_ai:
        return "ai_off"
    try:
        engines = ai_engine.resolve_all(settings.ai_engine).engines
    except AiError:
        return "no_engine"
    if not engines:
        return "no_engine"
    if not any(consent_ok(e.name) for e in engines):
        return "needs_consent"
    return None


def _ai_one(engine: ai_engine.EngineInfo, prompt: str, pool_nums: set[int], on_start, is_cancelled) -> tuple[str, list[recommend.AiPick] | None, bool]:
    """엔진 1개 호출 → (엔진 키, 검증된 순위 또는 None, 취소 여부). 예외는 실패(None)로 바꾼다. 프롬프트·응답은 로깅하지 않는다."""
    try:
        res = ai_engine.run(engine, prompt, timeout=AI_RECOMMEND_TIMEOUT, on_start=on_start, is_cancelled=is_cancelled)
    except AiError as e:
        log.info("추천 AI 실패 (%s): %s", engine.name, e)
        return engine.name, None, False
    except Exception:  # noqa: BLE001
        log.exception("추천 AI 내부 오류 (%s)", engine.name)
        return engine.name, None, False
    if res.cancelled or (is_cancelled is not None and is_cancelled()):
        return engine.name, None, True
    picks = recommend.parse_ai(res.text, pool_nums)
    if picks is None:
        log.info("추천 AI 응답을 쓸 수 없습니다 (%s): 유효한 선택 %d개 미만", engine.name, recommend.AI_PICK_MIN)
    return engine.name, picks, False


def recommend_ai(
    settings: Settings,
    base: recommend.RecommendResult,
    *,
    consent_ok: ConsentCheck,
    now: datetime | None = None,
    on_start: Callable[[object], None] | None = None,
    on_begin: Callable[[list[str]], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    is_touched: Callable[[], bool] | None = None,
    retry: bool = False,
) -> recommend.RecommendResult:
    """AI 약점 분석으로 후보 중에서 고른다 (하루 1회/엔진). 예외는 던지지 않고 base 에 ai_status 를 담아 돌려준다.

    ai_status: off | skipped_low_data | needs_consent | no_engine | ok | failed | cancelled | none(후보 부족·세트 없음).
    동의는 consent_ok(엔진 키) 콜백이 대신한다 (코어는 동의를 모른다). 동의 없는 엔진은 호출하지 않고(시도 횟수도 안 씀),
    both 는 동의된 설치 엔진을 병렬 호출해 득표로 합친다. 고정 엔진이 없으면 폴백 없이 no_engine.
    AI 로는 수준 숫자·약점/강점 카테고리 이름·집계·후보 풀(번호·제목·레벨·정답률·참여자)만 보낸다 (recommend.ai_payload).
    is_touched(): 사용자가 이미 [다른 추천]/항목 열기를 했으면 현재 화면은 바꾸지 않고 순위만 저장한다 (다음 세트용).
    """
    try:
        return _recommend_ai(settings, base, consent_ok, now, on_start, on_begin, is_cancelled, is_touched, retry)
    except Exception:  # noqa: BLE001 — 부가 기능은 앱을 깨지 않는다
        log.exception("추천 AI 내부 오류")
        base.ai_status = "failed"
        return base


def _recommend_ai(settings, base, consent_ok, now, on_start, on_begin, is_cancelled, is_touched, retry) -> recommend.RecommendResult:
    if not (recommend_enabled(settings) and settings.recommend_ai):
        base.ai_status = "off"
        return base
    stamp = growth._now(now)
    today = stamp.date()
    ds = recommend.load_day(settings)
    cat = catalog.load(settings)
    if ds is None or ds.date != today.isoformat() or cat is None:
        base.ai_status = "none"
        return base
    if not retry and ds.ai_status() in ("ok", "failed"):  # 하루 1회: 같은 날 재시작·탭 이동·[다른 추천] 에서는 호출 0
        base.ai_status = "ok" if ds.ai_status() == "ok" else "failed"
        return base
    ctx = _rec_context(settings, cat, today, ds.start or None)
    tagged = _tagged_groups(ctx.events, stamp)
    base.weak_tagged = tagged
    if tagged < AI_MIN_TAGGED:
        base.ai_status = "skipped_low_data"
        return base
    pool = recommend.ai_pool(cat.items, ctx.est, solved_nums=ctx.solved_nums, excluded={r.num for r in ctx.retry}, types=ctx.types, known=ctx.known)
    if len(pool) < recommend.AI_PICK_MAX:
        base.ai_status = "none"
        return base
    try:
        engines = ai_engine.resolve_all(settings.ai_engine).engines
    except AiError:
        base.ai_status = "no_engine"
        return base
    allowed = [e for e in engines if consent_ok(e.name)]
    if not allowed:
        base.ai_status = "needs_consent"  # 호출 0, 시도 횟수 미소모
        return base
    if is_cancelled is not None and is_cancelled():
        base.ai_status = "cancelled"
        return base

    stats = growth.compute_stats([e for e in ctx.events if e.at >= stamp - timedelta(days=AI_WINDOW_DAYS)])

    def top(d: dict[str, int]) -> list[tuple[str, int]]:
        rows = [(growth_tags.name_of(c), s) for c, s in d.items()]
        return sorted(((n, s) for n, s in rows if n), key=lambda r: (-r[1], r[0]))[:4]

    solved_by_level: Counter = Counter()
    for f in ctx.facts:
        if f.solved and f.level and f.day is not None and 0 <= (today - f.day).days <= recommend.THRESH["window_days"]:
            solved_by_level[f.level] += 1
    payload = recommend.ai_payload(
        ctx.est, recent_solved_by_level=solved_by_level, weak=top(stats.weak), strong=top(stats.strong),
        stats={"avg_wrong_before_pass": stats.avg_wrong_before_pass, "timeout_share": stats.timeout_share, "tagged": stats.tagged},
        pool=pool, clean_title=ai_prompts.neutralize, known=sorted(problem_types.allowed_for(ctx.known)), types=ctx.types,
    )
    prompt = ai_prompts.build_recommend_prompt(payload)
    pool_nums = {it.num for it in pool}
    if on_begin is not None:
        on_begin([e.name for e in allowed])
    outcomes: list[tuple[str, list[recommend.AiPick] | None, bool]] = []
    if len(allowed) == 1:
        outcomes.append(_ai_one(allowed[0], prompt, pool_nums, on_start, is_cancelled))
    else:
        with ThreadPoolExecutor(max_workers=len(allowed), thread_name_prefix="recommend") as ex:
            futures = [ex.submit(_ai_one, e, prompt, pool_nums, on_start, is_cancelled) for e in allowed]
            outcomes = [f.result() for f in futures]  # allowed 순서(Codex 우선)를 유지
    if any(o[2] for o in outcomes) or (is_cancelled is not None and is_cancelled()):
        base.ai_status = "cancelled"  # 취소는 상태를 바꾸지 않는다
        return base
    good = [(key, picks) for key, picks, _c in outcomes if picks]
    prev_fail = int(ds.ai.get("fail_count") or 0)
    if not good:
        ds.ai = {"status": "failed", "engines": [e.name for e in allowed], "at": growth._iso(stamp), "picks": [], "cursor": 0, "fail_count": prev_fail + 1}
        recommend.save_day(settings, ds)
        base.ai_status, base.ai_engines = "failed", []
        return base
    quality = {**recommend.quality_scores([it for it in pool if it.lv == ctx.est.level], recommend.WEIGHTS_FIT),
               **recommend.quality_scores([it for it in pool if it.lv != ctx.est.level], recommend.WEIGHTS_STRETCH)}
    merged = recommend.merge_ai([p for _k, p in good], quality)
    ds.ai = {"status": "ok", "engines": [k for k, _p in good], "at": growth._iso(stamp),
             "picks": [{"n": p.num, **({"r": p.reason} if p.reason else {})} for p in merged], "cursor": 0, "fail_count": prev_fail}
    touched = ds.shuffle > 0 or (is_touched is not None and is_touched())
    if not touched:  # 규칙 세트를 AI 순위로 교체 (재도전 칸은 규칙 그대로)
        ds.day_shown = []
        ds.recent_shown = {k: v for k, v in ds.recent_shown.items() if v != today.isoformat()}  # 오늘 처음 보인 규칙 세트는 "최근 노출" 이 아니다
        _new_set(ds, ctx, today, ds.start, shuffle=0, keep_shown=False)
    recommend.save_day(settings, ds)
    out = _assemble(settings, ds, ctx, today, stamp, base.catalog or catalog.status(settings, stamp))
    out.ai_status = "ok"
    out.notes = list(base.notes)
    if touched:
        out.items = base.items  # 보던 화면은 그대로 (순위는 다음 세트용으로 저장됨)
        out.source, out.shuffle = base.source, base.shuffle
    return out


# --- 풀이 유형 분류 (M24.1) -------------------------------------------------------------------
# "난이도만 같은" 추천을 막기 위해 문제마다 풀이 유형(problem_types)을 붙인다. 공개 문제의 지문 앞부분·제목만 AI 로 보내 분류하고
# 결과는 cache/problem_types.json 에 영구 저장한다 (내 코드·계정·경로는 보내지 않는다). 워커 전용 (네트워크·AI).

AI_CLASSIFY_TIMEOUT = 180.0  # 12문제 분류 JSON 한 개
CLASSIFY_FETCH_PACE = 0.3  # 지문을 새로 받을 때 요청 사이 대기(초)
ENOUGH_TYPED = 6  # 일반 칸 후보 풀(C, C+1)에 유형을 아는 문제가 이만큼 있으면 후보 분류를 더 하지 않는다


@dataclass
class ClassifyResult:
    """status: off(AI 분석 꺼짐) | nothing(할 일 없음) | needs_consent | no_engine | failed | cancelled | partial(일일 상한·중간 실패로 일부만) | ok."""

    status: str = "nothing"
    done: int = 0  # 이번에 분류를 시도한 문제 수
    changed: bool = False  # 캐시가 바뀌었다 (세트를 다시 만들 수 있다)
    engine: str = ""


def has_day_set(settings: Settings, now: datetime | None = None) -> bool:
    """오늘 이미 만들어 둔 세트가 있는가 (파일 읽기만)."""
    ds = recommend.load_day(settings)
    return ds is not None and ds.date == growth._now(now).date().isoformat() and bool(ds.items)


def classify_types(
    settings: Settings,
    *,
    consent_ok: ConsentCheck,
    now: datetime | None = None,
    start_level: int | None = None,
    on_start: Callable[[object], None] | None = None,
    on_begin: Callable[[str], None] | None = None,
    on_progress: Callable[[int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    retry: bool = False,
    session=None,
    sleep: Callable[[float], None] = time.sleep,
) -> ClassifyResult:
    """풀이 유형을 AI 로 분류해 캐시에 쌓는다 (하루 40문제 상한, 한 번에 12문제). 예외는 던지지 않고 ClassifyResult.status 로 알린다.

    대상(우선순위): ① 내가 푼 문제(앱 Pass 기록, 최근 것부터 — "내가 아는 유형"의 증거) ② 새 유형 후보(경로상 다음 유형을 찾는 난이도 C-1 의 상위 문제)
    ③ 일반 칸 후보(C, C+1 의 상위 문제). 이미 분류했거나 제목 키워드로 분명한 문제는 건너뛴다.
    입력은 공개 문제의 번호·제목·지문 앞부분뿐이다. 엔진은 동의한 엔진 중 첫 번째(Codex 우선) **하나만** 쓴다 (사용량 절약).
    지문은 (캐시에 있으면 그것을, 없으면) 카탈로그의 contestProbId 로 지문 페이지만 받아 온다 — 폴더·저장 없음, 지문 캐시도 쓰지 않는다
    (분류용으로 받은 수십 건이 사용자가 열어 본 최근 50건을 밀어내지 않게).
    """
    try:
        return _classify_types(settings, consent_ok, now, start_level, on_start, on_begin, on_progress, is_cancelled, retry, session, sleep)
    except Exception:  # noqa: BLE001 — 부가 기능은 추천을 깨지 않는다
        log.exception("풀이 유형 분류 내부 오류")
        return ClassifyResult("failed")


def _classify_types(settings, consent_ok, now, start_level, on_start, on_begin, on_progress, is_cancelled, retry, session, sleep) -> ClassifyResult:
    if not (recommend_enabled(settings) and settings.recommend_ai):
        return ClassifyResult("off")
    stamp = growth._now(now)
    today = stamp.date()
    cat = catalog.load(settings)
    if cat is None:
        return ClassifyResult("nothing")
    ctx = _rec_context(settings, cat, today, start_level)
    tc = ctx.tcache
    index = lookup.load_index(settings)
    tried: set[int] = set()  # 이번 실행에서 이미 시도(또는 지문을 못 구함)한 문제 — 같은 실행에서 다시 고르지 않는다
    used = {"solved": 0, "newtype": 0, "cand": 0}
    skip = set(ctx.solved_nums) | {r.num for r in ctx.retry}
    c = ctx.est.level

    def has_source(n: int) -> bool:
        return n in cat.items or bool((index.get(str(n)) or {}).get("id")) or content_cache.has(settings, n)

    def need(n: int) -> bool:
        return n not in tried and not tc.fresh(n, today) and not problem_types.title_types(ctx.titles.get(n, "")) and has_source(n)

    def types_now(n: int) -> tuple[str, ...]:
        return problem_types.effective_types(tc, n, ctx.titles.get(n, ""))

    def pick_batch(limit: int) -> list[int]:
        take = min(recommend.CLASSIFY_BATCH, limit)
        if take <= 0:
            return []
        if used["solved"] < recommend.CLASSIFY_SOLVED_MAX:  # ① 푼 문제 (최근 것부터)
            todo = [n for n in sorted(ctx.first_day, key=lambda n: (ctx.first_day[n], n), reverse=True) if need(n)]
            if todo:
                batch = todo[: min(take, recommend.CLASSIFY_SOLVED_MAX - used["solved"])]
                used["solved"] += len(batch)
                return batch
        known = set(problem_types.count_known(ctx.first_day, types_now))
        allowed = problem_types.allowed_for(known)
        nxt = problem_types.next_types(known)[:1]
        if nxt and used["newtype"] < recommend.CLASSIFY_NEWTYPE_MAX:  # ② 새 유형 후보: 다음 유형의 문제가 이미 있으면 더 찾지 않는다
            ranked = recommend.ranked_pool(cat.items, max(1, c - 1), recommend.WEIGHTS_STRETCH, skip)
            if not any(types_now(it.num)[:1] == (nxt[0],) for it in ranked):
                todo = [it.num for it in ranked if need(it.num)]
                if todo:
                    batch = todo[: min(take, recommend.CLASSIFY_NEWTYPE_MAX - used["newtype"])]
                    used["newtype"] += len(batch)
                    return batch
        if used["cand"] < recommend.CLASSIFY_CAND_MAX:  # ③ 일반 칸 후보 (C, C+1)
            fit = recommend.ranked_pool(cat.items, c, recommend.WEIGHTS_FIT, skip)
            stretch = recommend.ranked_pool(cat.items, c + 1, recommend.WEIGHTS_STRETCH, skip) if c < recommend.MAX_LEVEL else []
            typed = sum(1 for it in fit + stretch if problem_types.type_ok(types_now(it.num), allowed))
            if typed < ENOUGH_TYPED:
                todo = []
                for i in range(max(len(fit), len(stretch))):  # 수준 맞춤·한 단계 위를 번갈아
                    todo.extend(it.num for it in (fit[i : i + 1] + stretch[i : i + 1]) if need(it.num))
                if todo:
                    batch = todo[: min(take, recommend.CLASSIFY_CAND_MAX - used["cand"])]
                    used["cand"] += len(batch)
                    return batch
        return []

    # 할 일이 있는지부터 본다 (없으면 동의·엔진을 묻지 않는다). 미리 보기용이라 쿼터 카운터는 되돌린다
    snapshot = dict(used)
    first = pick_batch(recommend.CLASSIFY_BATCH)
    used.update(snapshot)
    if not first:
        return ClassifyResult("nothing")
    if recommend.CLASSIFY_DAILY_CAP - tc.used_on(today) <= 0:
        return ClassifyResult("partial")
    if tc.fail_day == today.isoformat() and not retry:
        return ClassifyResult("failed")  # 같은 날 자동 재시도는 하지 않는다 ([다시 시도] 만)
    try:
        engines = ai_engine.resolve_all(settings.ai_engine).engines
    except AiError:
        return ClassifyResult("no_engine")
    if not engines:
        return ClassifyResult("no_engine")
    consented = [e for e in engines if consent_ok(e.name)]
    if not consented:
        return ClassifyResult("needs_consent")  # 호출 0
    engine = consented[0]  # 분류는 한 엔진만 (사용량 절약) — 둘 다 설치돼 있으면 Codex 우선
    if is_cancelled is not None and is_cancelled():
        return ClassifyResult("cancelled")

    result = ClassifyResult("ok", engine=engine.name)
    if on_begin is not None:
        on_begin(engine.name)
    box: dict = {"session": session, "failed": False, "fetched": 0}

    def statement_of(n: int) -> tuple[str, ProblemContent | None]:
        title = ctx.titles.get(n, "")
        cached = content_cache.load(settings, n)
        if cached is not None and cached.content is not None:
            return title or cached.title, cached.content
        cid = cat.items[n].id if n in cat.items else str((index.get(str(n)) or {}).get("id") or "")
        if not cid or box["failed"]:
            return title, None
        try:
            if box["session"] is None:
                box["session"] = auth.get_session(settings)
            if box["fetched"]:
                sleep(CLASSIFY_FETCH_PACE)
            box["fetched"] += 1
            html, _kind = client.fetch_problem_page(box["session"], settings, cid)
            return title, parser.parse_content(html)
        except (SweaFetchError, OSError) as e:
            log.info("분류용 지문을 받지 못했습니다 (%s): %s", n, e)
            if box["session"] is None:
                box["failed"] = True  # 세션을 못 만들면 이번 실행에서 더 시도하지 않는다
            return title, None

    while True:
        if is_cancelled is not None and is_cancelled():
            result.status = "cancelled"
            break
        limit = recommend.CLASSIFY_DAILY_CAP - tc.used_on(today)
        if limit <= 0:
            result.status = "partial"
            break
        batch = pick_batch(limit)
        if not batch:
            break
        entries: list[dict] = []
        for n in batch:
            tried.add(n)
            title, content = statement_of(n)
            entry = ai_prompts.classify_entry(n, title, content) if content is not None else None
            if entry is not None and entry["text"].strip():
                entries.append(entry)
        if not entries:
            continue
        nums = {e["n"] for e in entries}
        cancelled = False
        parsed = None
        try:
            res = ai_engine.run(engine, ai_prompts.build_classify_prompt(entries), timeout=AI_CLASSIFY_TIMEOUT, on_start=on_start, is_cancelled=is_cancelled)
            cancelled = res.cancelled or (is_cancelled is not None and is_cancelled())
            parsed = None if cancelled else problem_types.parse_batch(res.text, nums)
        except AiError as e:
            log.info("풀이 유형 분류 AI 실패 (%s): %s", engine.name, e)
        except Exception:  # noqa: BLE001
            log.exception("풀이 유형 분류 AI 내부 오류 (%s)", engine.name)
        if cancelled:
            result.status = "cancelled"
            break
        if parsed is None:  # 엔진 실패·형식 불량: 오늘은 더 부르지 않는다
            tc.fail_day = today.isoformat()
            problem_types.save(settings, tc)
            result.status = "partial" if result.changed else "failed"
            break
        valid, _bad = parsed
        tc.entries.update(problem_types.stamp_entries(valid, nums - set(valid), engine.name, stamp))  # 응답에 없거나 쓸 수 없는 번호는 "정하지 못함" (14일 뒤 재시도)
        tc.add_used(today, len(nums))
        problem_types.save(settings, tc)
        result.done += len(nums)
        result.changed = True
        if on_progress is not None:
            on_progress(result.done)
    return result
