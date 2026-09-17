"""CLI·GUI 공용 서비스 계층. 파이프라인 로직은 여기 한 곳에만 둔다.

fetch_problem : settings → contestProbId → 세션 → 페이지 → 파싱 → (첨부) → 저장/미리보기
verify_login  : 세션 확보만 (설정 확인용)
list_topics   : root 아래 주제 폴더 (중첩 가능, `test/IM_test` 표기)
list_recent   : root 아래 {topic}/{num}/ 를 mtime 순으로 (중첩 주제 포함)
write_env     : .env 파일 쓰기 (비밀번호는 절대 쓰지 않음; SWEA_PYTHON 등 다른 키는 보존)
set_env_values: .env 의 개별 키 갱신 (M7: SWEA_COMMIT_TEMPLATE, SWEA_AUTO_PUSH)
push_problem  : 문제 폴더만 git 커밋(+푸시) (M7). 자격증명은 다루지 않는다
submit_problem: SWEA 에 제출하고 채점 결과를 받는다 (M8). Pass 면 push 까지 (submit_and_push)

네트워크·파일 I/O 가 있으므로 GUI 는 워커 스레드에서 호출한다.
"""

from __future__ import annotations

import dataclasses
import json
import difflib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import auth, client, config, gitops, lookup, parser, storage, submit
from .config import Settings
from .errors import GitError, InvalidInput
from .gitops import GitResult
from .submit import SubmitResult
from .models import ProblemInfo, SaveResult

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

    in_bytes = out_bytes = None
    if not opts.skeleton_only:
        _emit(progress, "첨부 다운로드")
        in_bytes = client.download(session, info.input_url, settings)
        out_bytes = client.download(session, info.output_url, settings)

    if opts.dry_run:
        _emit(progress, "미리보기 (저장하지 않음)")
        return FetchOutcome(info, None, _build_preview(info, topic, settings, in_bytes, out_bytes, opts), notices, topic)

    _emit(progress, "저장 중")
    try:
        if opts.skeleton_only:
            result = storage.save_skeleton(settings.root, topic, info, settings)
        else:
            result = storage.save_problem(settings.root, topic, info, in_bytes, out_bytes, settings, force=opts.force)
    except ValueError as e:
        raise InvalidInput(str(e)) from e
    _emit(progress, "저장 완료")
    return FetchOutcome(info, result, None, notices, topic)


def verify_login(settings: Settings, progress: ProgressCb | None = None) -> str:
    """세션을 확보한다. 성공 시 표시용 메시지. 예외는 그대로 전파."""
    _emit(progress, "로그인 확인 중")
    auth.get_session(settings)
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


def list_recent(settings_or_root: Settings | Path, limit: int = 20) -> list[RecentItem]:
    """root 아래 {topic}/{num}/ 폴더를 수정 시각 내림차순으로. topic 은 `test/IM_test` 표기."""
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
    return items[:limit]


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
    result = gitops.commit_and_push(repo, problem_dir, message.strip(), push=push)
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
    if push and result.passed:
        outcome.git = push_problem(settings, topic, num, message=message, push=True, progress=progress)
    return outcome


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
    for path in targets:
        try:
            path.unlink()
            removed.append(path.name)
        except FileNotFoundError:
            pass
    return removed
