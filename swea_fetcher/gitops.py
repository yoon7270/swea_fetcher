"""git 연동 (M7): 문제 폴더만 스테이징해 커밋하고, 원한다면 푸시한다.

원칙 (m7 지시서 §0):
- 도구는 git 명령을 대신 실행할 뿐 자격증명을 다루지 않는다 (인증은 Git Credential Manager 의 창이 담당)
- 문제 폴더만 `git add -- {rel}` / `git commit -- {rel}` — 루트의 다른 변경은 절대 끌고 가지 않는다
- force push 없음, pull/rebase 없음. 실패 시 "왜 + 다음 명령" 만 안내
- 루트가 저장소가 아니면 만들어 주지 않는다 (README 안내)
- 모든 호출: GIT_TERMINAL_PROMPT=0 (터미널 프롬프트로 멈추지 않게), LC_ALL=C (메시지 판별 안정화), core.quotepath=false
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_COMMIT_TEMPLATE = "solve: {num}. {title} ({topic})"
DEFAULT_TIMEOUT = 30.0
MIN_GIT_VERSION = (2, 30)

_TOKEN_URL_RE = re.compile(r"(?i)(://)([^/@\s:]+)(:[^@/\s]+)?@")  # https://user:token@host → https://***@host


@dataclass(frozen=True)
class RepoInfo:
    toplevel: Path  # git rev-parse --show-toplevel
    branch: str  # 현재 브랜치 (detached 면 "")
    remote: str | None  # origin URL (마스킹됨, 없으면 None)
    upstream: str | None  # branch 의 upstream ("origin/main" 등, 없으면 None)
    dirty_outside: bool  # 문제 폴더 밖에 변경이 있는지 (정보용, 막지 않음)
    git_dir: Path  # .git 위치 (MERGE_HEAD 등 상태 파일 확인용)


@dataclass(frozen=True)
class GitResult:
    committed: bool
    pushed: bool
    commit_hash: str | None
    message: str  # 커밋 메시지
    output: str  # git stdout/stderr 합본 (로그 표시용, 토큰 마스킹됨)
    note: str  # 사람이 읽을 결과 한 줄
    failed: bool = False  # 커밋/푸시 중 오류 (note 에 사유·다음 명령)


# --- 실행 도우미 ---------------------------------------------------------------------


def git_available() -> str | None:
    """git 실행 파일 경로. 없으면 None."""
    return shutil.which("git")


def git_version() -> tuple[int, ...] | None:
    """(2, 45, 1) 같은 튜플. git 이 없거나 파싱 실패면 None."""
    git = git_available()
    if git is None:
        return None
    try:
        out = _run(["--version"], cwd=None, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out)
    return tuple(int(g) for g in m.groups() if g is not None) if m else None


def mask_url(text: str) -> str:
    """URL 에 박힌 자격증명(https://user:token@host)을 *** 로 가린다. 로그·표시용."""
    return _TOKEN_URL_RE.sub(r"\1***@", text or "")


def _run(args: list[str], cwd: Path | None, timeout: float = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    git = git_available() or "git"
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    creation = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(
        [git, "-c", "core.quotepath=false", *args],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        creationflags=creation,
    )


def _ok(args: list[str], cwd: Path, timeout: float = DEFAULT_TIMEOUT) -> str | None:
    """성공하면 stdout.strip(), 실패(비0)면 None."""
    try:
        cp = _run(args, cwd, timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return cp.stdout.strip() if cp.returncode == 0 else None


# --- 저장소 정보 ------------------------------------------------------------------------


def find_repo(root: Path, problem_dir: Path | None = None) -> RepoInfo | None:
    """root 가 git 저장소 안이면 RepoInfo, 아니면 None.

    toplevel 은 root 와 같거나 root 의 상위여야 한다 (root 가 저장소의 하위 폴더인 경우 허용).
    dirty_outside: problem_dir 가 주어지면 그 밖의 변경, 아니면 작업 트리 전체의 변경 여부.
    """
    root = Path(root)
    if git_available() is None or not root.is_dir():
        return None
    top = _ok(["rev-parse", "--show-toplevel"], root)
    if not top:
        return None
    toplevel = Path(top).resolve()
    root_r = root.resolve()
    if toplevel != root_r and toplevel not in root_r.parents:
        return None
    git_dir_s = _ok(["rev-parse", "--absolute-git-dir"], root) or _ok(["rev-parse", "--git-dir"], root) or ".git"
    git_dir = Path(git_dir_s)
    if not git_dir.is_absolute():
        git_dir = toplevel / git_dir
    branch = _ok(["symbolic-ref", "--short", "-q", "HEAD"], root) or ""
    remote_raw = _ok(["remote", "get-url", "origin"], root)
    remote = mask_url(remote_raw) if remote_raw else None
    upstream = _ok(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root) if branch else None

    dirty_outside = False
    status = _ok(["status", "--porcelain", "--untracked-files=all"], root)
    if status:
        rel_problem = None
        if problem_dir is not None:
            try:
                rel_problem = Path(problem_dir).resolve().relative_to(toplevel).as_posix().rstrip("/") + "/"
            except ValueError:
                rel_problem = None
        for line in status.splitlines():
            path = line[3:].split(" -> ")[-1].strip().strip('"')
            if rel_problem is None or not path.startswith(rel_problem):
                dirty_outside = True
                break
    return RepoInfo(toplevel, branch, remote, upstream, dirty_outside, git_dir)


def in_progress_operation(repo: RepoInfo) -> str | None:
    """병합/리베이스/체리픽 진행 중이면 그 이름, 아니면 None."""
    g = repo.git_dir
    if (g / "MERGE_HEAD").exists():
        return "병합(merge)"
    if (g / "REBASE_HEAD").exists() or (g / "rebase-merge").exists() or (g / "rebase-apply").exists():
        return "리베이스(rebase)"
    if (g / "CHERRY_PICK_HEAD").exists():
        return "체리픽(cherry-pick)"
    return None


def preflight(repo: RepoInfo | None, problem_dir: Path, push: bool = True) -> list[str]:
    """막아야 할 사유 목록. 비어 있으면 진행 가능."""
    reasons: list[str] = []
    if git_available() is None:
        return ["git 이 설치되어 있지 않습니다"]
    if repo is None:
        return ["루트 폴더가 git 저장소가 아닙니다 — README 'GitHub 연동' 절 참고"]
    problem_dir = Path(problem_dir)
    try:
        problem_dir.resolve().relative_to(repo.toplevel)
    except ValueError:
        reasons.append(f"문제 폴더가 저장소 밖에 있습니다: {problem_dir}")
    op = in_progress_operation(repo)
    if op:
        reasons.append(f"{op} 진행 중입니다 — 먼저 끝내거나 중단(`git {op.split('(')[1].rstrip(')')} --abort`)하세요")
    if not repo.branch:
        reasons.append("브랜치가 아닌 상태(detached HEAD)입니다 — `git switch main` 등으로 브랜치로 돌아가세요")
    if push and not repo.remote:
        reasons.append("원격 저장소(origin)가 없습니다 — `git remote add origin <URL>` 후 다시 시도 (README 'GitHub 연동')")
    if not problem_dir.is_dir():
        reasons.append(f"문제 폴더가 없습니다: {problem_dir}")
    elif not (problem_dir / f"{problem_dir.name}.py").is_file():
        reasons.append(f"풀이 파일이 없습니다 ({problem_dir.name}.py)")
    return reasons


# --- 커밋 메시지 ------------------------------------------------------------------------


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_message(template: str, info, topic: str) -> str:
    """템플릿 변수 {num} {title} {topic} {date} 치환 후 공백 정리.

    info 는 .num / .title 을 가진 객체 (ProblemInfo, RecentItem). title 이 없으면 빈 문자열로 두고
    'solve: 1225.  (Queue)' 같은 이중 공백을 정리한다.
    """
    values = _SafeDict(
        num=str(getattr(info, "num", "") or ""),
        title=str(getattr(info, "title", "") or "").strip(),
        topic=str(topic or "").strip(),
        date=date.today().isoformat(),
    )
    try:
        text = (template or DEFAULT_COMMIT_TEMPLATE).format_map(values)
    except (ValueError, IndexError):  # 짝이 안 맞는 중괄호 등 → 템플릿을 그대로
        text = template or DEFAULT_COMMIT_TEMPLATE
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\(\s*\)", "", text)  # 빈 괄호 제거
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip() or f"solve: {values['num']}"


# --- 커밋 + 푸시 ------------------------------------------------------------------------


def classify_push_error(stderr: str) -> str:
    """push 의 stderr 를 사람이 읽을 사유 + 다음 명령으로 바꾼다."""
    s = stderr or ""
    low = s.lower()
    if "non-fast-forward" in low or "rejected" in low or "fetch first" in low:
        return "원격에 새 커밋이 있습니다. `git pull` 후 다시 시도하세요"
    if "authentication failed" in low or "could not read username" in low or "could not read password" in low or "terminal prompts disabled" in low:
        return "GitHub 인증 실패 — 브라우저 로그인 창이 뜨지 않았다면 Git Credential Manager 설정을 확인하세요"
    if "permission denied" in low or "403" in low:
        return "이 저장소에 푸시 권한이 없습니다 — 원격 URL 과 계정을 확인하세요"
    if "could not resolve host" in low or "unable to access" in low or "connection" in low:
        return "원격에 연결하지 못했습니다 — 네트워크를 확인한 뒤 다시 시도하세요"
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    return lines[-1] if lines else "푸시 실패 (자세한 내용은 로그 참고)"


def commit_and_push(
    repo: RepoInfo,
    problem_dir: Path,
    message: str,
    *,
    push: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> GitResult:
    """문제 폴더만 add → (변경 있으면) commit -- {rel} → push. 어떤 경우에도 예외 대신 GitResult."""
    problem_dir = Path(problem_dir)
    rel = problem_dir.resolve().relative_to(repo.toplevel).as_posix()
    return _commit_push(repo, [rel], message, push=push, timeout=timeout)


def changed_problem_dirs(repo: RepoInfo, root: Path) -> list[Path]:
    """git status 에서 변경된 파일을 {topic..}/{num}/ 문제 폴더로 묶어 (root 기준) 절대경로 목록으로.

    root 밖 변경, 그리고 숫자 폴더로 안 묶이는 변경(루트 바로 아래 파일 등)은 제외한다. 정렬·중복 제거.
    """
    root_r = Path(root).resolve()
    status = _ok(["status", "--porcelain", "--untracked-files=all"], repo.toplevel)
    if not status:
        return []
    dirs: set[Path] = set()
    for line in status.splitlines():
        raw = line[3:].split(" -> ")[-1].strip().strip('"')
        if not raw:
            continue
        abspath = (repo.toplevel / raw).resolve()
        try:
            rel_parts = abspath.relative_to(root_r).parts
        except ValueError:
            continue  # root 밖
        # rel_parts = (topic..., num, file) → num 세그먼트(숫자)를 찾아 그 상위까지가 문제 폴더
        for i, seg in enumerate(rel_parts):
            if seg.isdigit():
                dirs.add(root_r.joinpath(*rel_parts[: i + 1]))
                break
    return sorted(dirs)


def _scope_message(template: str, problem_dirs: list[Path], root: Path) -> str:
    """범위 커밋 메시지. 문제 번호가 잡히면 `solve: 1225, 1226 (Queue)` (주제 하나일 때만 괄호), 아니면 `sync: {date}`."""
    root_r = Path(root).resolve()
    nums: list[int] = []
    topics: set[str] = set()
    for d in problem_dirs:
        if d.name.isdigit():
            nums.append(int(d.name))
            try:
                rel = d.resolve().relative_to(root_r).parts
            except ValueError:
                rel = ()
            if len(rel) >= 2:
                topics.add("/".join(rel[:-1]))
    if nums:
        nums_s = ", ".join(str(n) for n in sorted(set(nums)))
        return f"solve: {nums_s}" + (f" ({next(iter(topics))})" if len(topics) == 1 else "")
    return f"sync: {date.today().isoformat()}"


def commit_and_push_scope(
    repo: RepoInfo,
    root: Path,
    scope: str,
    message_template: str = DEFAULT_COMMIT_TEMPLATE,
    *,
    push: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> GitResult:
    """범위별 커밋+푸시 (M11).

    scope="problem": 변경된 문제 폴더들만 (각 폴더 pathspec) — 루트의 다른 변경은 안 건드림.
    scope="root":    루트 서브트리 전체 (`git add -A -- {root}`), .gitignore 는 git 이 적용.
    """
    root_r = Path(root).resolve()
    try:
        root_rel = root_r.relative_to(repo.toplevel).as_posix() or "."
    except ValueError:
        root_rel = "."
    problem_dirs = changed_problem_dirs(repo, root_r)
    message = _scope_message(message_template, problem_dirs, root_r)
    if scope == "root":
        return _commit_push(repo, [root_rel], message, push=push, timeout=timeout, add_all=True)
    # scope == "problem"
    if not problem_dirs:
        # 변경된 문제 폴더가 없어도, 이전에 커밋만 하고 못 민 게 있을 수 있어 push 는 시도
        return _commit_push(repo, [], message, push=push, timeout=timeout, allow_empty_pathspec=True)
    rels = [d.resolve().relative_to(repo.toplevel).as_posix() for d in problem_dirs]
    return _commit_push(repo, rels, message, push=push, timeout=timeout)


def _commit_push(
    repo: RepoInfo,
    pathspecs: list[str],
    message: str,
    *,
    push: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
    add_all: bool = False,
    allow_empty_pathspec: bool = False,
) -> GitResult:
    """pathspecs 를 add → (변경 있으면) commit → push. 어떤 경우에도 예외 대신 GitResult.

    add_all: `git add -A` (root 범위, 삭제 포함). allow_empty_pathspec: pathspecs 가 비어도 push 만 시도.
    """
    log: list[str] = []
    cwd = repo.toplevel
    no_paths = not pathspecs and allow_empty_pathspec

    def run(args: list[str], label: str) -> subprocess.CompletedProcess | None:
        log.append(f"$ git {' '.join(args)}")
        try:
            cp = _run(args, cwd, timeout)
        except subprocess.TimeoutExpired:
            log.append(f"[시간 초과] {label} 이(가) {timeout:.0f}초를 넘었습니다")
            return None
        except OSError as e:
            log.append(f"[오류] {label}: {e}")
            return None
        for stream in (cp.stdout, cp.stderr):
            if stream and stream.strip():
                log.append(mask_url(stream.rstrip()))
        return cp

    def result(committed: bool, pushed: bool, commit_hash: str | None, note: str, failed: bool = False) -> GitResult:
        return GitResult(committed, pushed, commit_hash, message, "\n".join(log), note, failed)

    has_changes = False
    if not no_paths:
        # 1) 스테이징
        add_args = (["add", "-A", "--"] if add_all else ["add", "--"]) + pathspecs
        cp = run(add_args, "git add")
        if cp is None or cp.returncode != 0:
            return result(False, False, None, "스테이징 실패 (로그 참고)", failed=True)

        # 2) 변경 여부
        cp = run(["diff", "--cached", "--quiet", "--", *pathspecs], "git diff --cached")
        if cp is None:
            return result(False, False, None, "변경 확인 실패", failed=True)
        has_changes = cp.returncode == 1
    committed = False
    commit_hash: str | None = None
    if has_changes:
        # 3) 커밋: pathspec 을 붙여 다른 스테이징 변경이 섞이지 않게
        cp = run(["commit", "-m", message, "--", *pathspecs], "git commit")
        if cp is None or cp.returncode != 0:
            note = "커밋 실패 (로그 참고)"
            if cp is not None and "please tell me who you are" in (cp.stderr + cp.stdout).lower():
                note = "git 사용자 이름/이메일이 없습니다 — `git config --global user.name`, `user.email` 설정 후 다시 시도"
            return result(False, False, None, note, failed=True)
        committed = True
        commit_hash = _ok(["rev-parse", "--short", "HEAD"], cwd)
        log.append(f"커밋 {commit_hash}: {message}")
    else:
        log.append("커밋할 변경이 없습니다")
        commit_hash = _ok(["rev-parse", "--short", "HEAD"], cwd)

    if not push:
        return result(committed, False, commit_hash, f"커밋만 {commit_hash}" if committed else "커밋할 변경이 없습니다")

    # 4) 푸시 (변경이 없어도 시도 — 이전에 커밋만 하고 푸시 못 한 경우 대비)
    args = ["push"] if repo.upstream else ["push", "-u", "origin", repo.branch]
    cp = run(args, "git push")
    if cp is None:
        return result(committed, False, commit_hash, f"푸시 시간 초과({timeout:.0f}초) — 인증 창이 떠 있지 않은지 확인하고 다시 시도하세요", failed=True)
    if cp.returncode != 0:
        return result(committed, False, commit_hash, classify_push_error(cp.stderr + "\n" + cp.stdout), failed=True)
    stderr_low = (cp.stderr or "").lower()
    if not committed and ("everything up-to-date" in stderr_low or "up to date" in stderr_low):
        return result(False, False, commit_hash, "커밋할 변경이 없습니다 (원격도 최신)")
    return result(committed, True, commit_hash, f"푸시됨 {commit_hash}" if committed else f"이전 커밋 {commit_hash} 푸시됨")
