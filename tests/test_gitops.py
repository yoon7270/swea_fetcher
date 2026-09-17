"""gitops: 실제 git 으로 tmp_path 에 bare origin + clone 을 만들어 commit/push 를 실측한다 (M10 §2).

네트워크 없음 (origin 은 로컬 bare 저장소). git 이 없으면 전체 skip.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

from swea_fetcher import gitops
from swea_fetcher.gitops import RepoInfo, classify_push_error, commit_and_push, find_repo, mask_url, preflight, render_message

pytestmark = pytest.mark.skipif(gitops.git_available() is None, reason="git 이 설치되어 있지 않음")


# --- 저장소 픽스처 -----------------------------------------------------------------------


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cp = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and cp.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 실패: {cp.stderr}")
    return cp


def _identity(repo: Path) -> None:
    _git(repo, "config", "user.name", "Tester")
    _git(repo, "config", "user.email", "tester@example.invalid")


@pytest.fixture(autouse=True)
def _git_env(monkeypatch):
    """전역/시스템 git 설정과 자격증명 헬퍼가 끼어들지 않게 한다."""
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    return bare


@pytest.fixture
def repo(tmp_path: Path, origin: Path) -> Path:
    """origin 을 clone 한 작업 저장소 (main, 첫 커밋 + upstream 설정됨). 루트 = 저장소 최상위."""
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _identity(work)
    (work / "README.md").write_text("# swea\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "push", "-q", "-u", "origin", "main")
    return work


def _problem(root: Path, topic: str = "sim", num: int = 1234, body: str = "print(1)\n") -> Path:
    d = root / topic / str(num)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{num}.py").write_text(body, encoding="utf-8")
    (d / "input.txt").write_text("1\n", encoding="utf-8")
    return d


def _log(repo: Path) -> list[str]:
    return _git(repo, "log", "--format=%s", "main").stdout.split()


def _origin_log(origin: Path) -> list[str]:
    return _git(origin, "log", "--format=%s", "main", check=False).stdout.split()


def _commit_files(repo: Path, ref: str = "HEAD") -> list[str]:
    return sorted(_git(repo, "show", "--name-only", "--format=", ref).stdout.split())


# =============================================================================
# 순수 함수
# =============================================================================


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://user:ghp_secret@github.com/u/r.git", "https://***@github.com/u/r.git"),
        ("https://ghp_secret@github.com/u/r.git", "https://***@github.com/u/r.git"),
        ("https://github.com/u/r.git", "https://github.com/u/r.git"),
        ("git@github.com:u/r.git", "git@github.com:u/r.git"),
        ("fatal: unable to access 'https://x:y@github.com/u/r.git/'", "fatal: unable to access 'https://***@github.com/u/r.git/'"),
        ("", ""),
        (None, ""),
    ],
)
def test_mask_url(raw, expected):
    assert mask_url(raw) == expected


def test_git_version_tuple():
    v = gitops.git_version()
    assert v is not None and len(v) >= 2 and all(isinstance(x, int) for x in v)


class _Info:
    def __init__(self, num, title):
        self.num, self.title = num, title


@pytest.mark.parametrize(
    "template, info, topic, expected",
    [
        (gitops.DEFAULT_COMMIT_TEMPLATE, _Info(1225, "Queue"), "test/IM_test", "solve: 1225. Queue (test/IM_test)"),
        (gitops.DEFAULT_COMMIT_TEMPLATE, _Info(1225, None), "Queue", "solve: 1225. (Queue)"),  # 제목 없음 → 이중 공백 정리
        (gitops.DEFAULT_COMMIT_TEMPLATE, _Info(1225, "  T  "), "", "solve: 1225. T"),  # 빈 괄호 제거
        ("{num}", _Info(7, "x"), "t", "7"),
        ("{num} {unknown}", _Info(7, "x"), "t", "7 {unknown}"),  # 모르는 키는 그대로
        ("{date} {num}", _Info(7, "x"), "t", f"{date.today().isoformat()} 7"),
        ("", _Info(7, "x"), "t", "solve: 7. x (t)"),  # 빈 템플릿 → 기본
        ("bad {", _Info(7, "x"), "t", "bad {"),  # 깨진 템플릿 → 그대로
        ("   ", _Info(7, None), "", "solve: 7"),
    ],
)
def test_render_message(template, info, topic, expected):
    assert render_message(template, info, topic) == expected


@pytest.mark.parametrize(
    "stderr, expect",
    [
        ("! [rejected] main -> main (non-fast-forward)", "git pull"),
        ("! [rejected] main -> main (fetch first)", "git pull"),
        ("fatal: Authentication failed for 'https://github.com/u/r.git/'", "인증 실패"),
        ("fatal: could not read Username for 'https://github.com': terminal prompts disabled", "인증 실패"),
        ("remote: Permission to u/r.git denied to x.\nfatal: unable to access ...: The requested URL returned error: 403", "권한"),
        ("fatal: unable to access 'https://github.com/u/r.git/': Could not resolve host: github.com", "연결"),
        ("something odd\nlast line here", "last line here"),
        ("", "푸시 실패"),
    ],
)
def test_classify_push_error(stderr, expect):
    assert expect in classify_push_error(stderr)


# =============================================================================
# find_repo / in_progress_operation / preflight
# =============================================================================


def test_find_repo_none_outside_git(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert find_repo(plain) is None
    assert find_repo(tmp_path / "missing") is None


def test_find_repo_fields(repo, origin):
    info = find_repo(repo)
    assert info is not None
    assert info.toplevel == repo.resolve()
    assert info.branch == "main"
    assert info.upstream == "origin/main"
    assert info.remote is not None and str(origin.name) in info.remote
    assert info.git_dir.is_dir() and info.git_dir.name == ".git"
    assert info.dirty_outside is False


def test_find_repo_masks_remote_token(repo):
    _git(repo, "remote", "set-url", "origin", "https://user:ghp_secret@github.com/u/r.git")
    info = find_repo(repo)
    assert info.remote == "https://***@github.com/u/r.git"
    assert "ghp_secret" not in info.remote


def test_find_repo_root_below_toplevel(repo):
    root = repo / "swea"
    root.mkdir()
    info = find_repo(root)
    assert info is not None and info.toplevel == repo.resolve()


def test_find_repo_dirty_outside(repo):
    d = _problem(repo)
    assert find_repo(repo, d).dirty_outside is False  # 문제 폴더 안의 변경만
    (repo / "notes.md").write_text("x")
    assert find_repo(repo, d).dirty_outside is True
    assert find_repo(repo).dirty_outside is True


def test_find_repo_no_remote_no_upstream(tmp_path):
    r = tmp_path / "solo"
    _git(tmp_path, "init", "-q", "-b", "main", str(r))
    _identity(r)
    (r / "a").write_text("a")
    _git(r, "add", "a")
    _git(r, "commit", "-q", "-m", "a")
    info = find_repo(r)
    assert info.remote is None and info.upstream is None and info.branch == "main"


def test_find_repo_detached(repo):
    _git(repo, "checkout", "-q", "--detach")
    assert find_repo(repo).branch == ""


def test_in_progress_operation(repo):
    info = find_repo(repo)
    assert gitops.in_progress_operation(info) is None
    (info.git_dir / "MERGE_HEAD").write_text("x")
    assert "merge" in gitops.in_progress_operation(info)
    (info.git_dir / "MERGE_HEAD").unlink()
    (info.git_dir / "rebase-merge").mkdir()
    assert "rebase" in gitops.in_progress_operation(info)
    (info.git_dir / "rebase-merge").rmdir()
    (info.git_dir / "CHERRY_PICK_HEAD").write_text("x")
    assert "cherry-pick" in gitops.in_progress_operation(info)


def test_preflight_ok(repo):
    d = _problem(repo)
    assert preflight(find_repo(repo, d), d) == []


def test_preflight_no_repo(tmp_path):
    reasons = preflight(None, tmp_path / "x")
    assert len(reasons) == 1 and "git 저장소가 아닙니다" in reasons[0]


def test_preflight_no_git(tmp_path, monkeypatch):
    monkeypatch.setattr(gitops, "git_available", lambda: None)
    assert preflight(None, tmp_path)[0].startswith("git 이 설치")


def test_preflight_no_remote_only_blocks_push(tmp_path):
    r = tmp_path / "solo"
    _git(tmp_path, "init", "-q", "-b", "main", str(r))
    _identity(r)
    d = _problem(r)
    info = find_repo(r, d)
    assert any("origin" in x for x in preflight(info, d, push=True))
    assert preflight(info, d, push=False) == []


def test_preflight_detached_and_in_progress(repo):
    d = _problem(repo)
    _git(repo, "checkout", "-q", "--detach")
    info = find_repo(repo, d)
    (info.git_dir / "rebase-merge").mkdir()
    reasons = preflight(info, d)
    assert any("detached" in x for x in reasons)
    assert any("rebase --abort" in x for x in reasons)


def test_preflight_missing_dir_or_solution(repo):
    info = find_repo(repo)
    assert any("문제 폴더가 없습니다" in x for x in preflight(info, repo / "sim" / "9"))
    d = repo / "sim" / "9"
    d.mkdir(parents=True)
    assert any("풀이 파일이 없습니다" in x for x in preflight(info, d))


def test_preflight_outside_repo(repo, tmp_path):
    outside = tmp_path / "elsewhere" / "1"
    outside.mkdir(parents=True)
    (outside / "1.py").write_text("")
    assert any("저장소 밖" in x for x in preflight(find_repo(repo), outside))


# =============================================================================
# commit_and_push — 실측
# =============================================================================


def test_commit_and_push_success(repo, origin):
    d = _problem(repo)
    info = find_repo(repo, d)
    res = commit_and_push(info, d, "solve: 1234. A+B (sim)")
    assert res.failed is False and res.committed and res.pushed
    assert res.commit_hash and len(res.commit_hash) >= 7
    assert res.note == f"푸시됨 {res.commit_hash}"
    assert res.message == "solve: 1234. A+B (sim)"
    assert "$ git add -- sim/1234" in res.output and "$ git push" in res.output
    assert _log(repo)[0] == "solve:" and _origin_log(origin) == _log(repo)  # 원격도 같은 커밋
    assert _commit_files(repo) == ["sim/1234/1234.py", "sim/1234/input.txt"]


def test_commit_only_when_push_false(repo, origin):
    d = _problem(repo)
    res = commit_and_push(find_repo(repo, d), d, "m", push=False)
    assert res.committed and not res.pushed and res.note == f"커밋만 {res.commit_hash}"
    assert "push" not in res.output
    assert len(_log(repo)) == 2 and len(_origin_log(origin)) == 1


def test_no_changes(repo):
    d = _problem(repo)
    commit_and_push(find_repo(repo, d), d, "first")
    res = commit_and_push(find_repo(repo, d), d, "again")
    assert not res.committed and not res.pushed and not res.failed
    assert "커밋할 변경이 없습니다" in res.note and "원격도 최신" in res.note
    assert len(_log(repo)) == 2


def test_no_changes_push_false(repo):
    d = _problem(repo)
    commit_and_push(find_repo(repo, d), d, "first", push=False)
    res = commit_and_push(find_repo(repo, d), d, "again", push=False)
    assert not res.committed and res.note == "커밋할 변경이 없습니다"


def test_only_problem_folder_is_committed(repo):
    """루트의 다른 변경(미추적·스테이징됨 모두)은 커밋에 섞이지 않는다."""
    d = _problem(repo)
    _problem(repo, "sim", 5555)  # 다른 문제 폴더 (미추적)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    _git(repo, "add", "README.md")  # 스테이징된 다른 변경
    res = commit_and_push(find_repo(repo, d), d, "only 1234")
    assert res.committed
    assert _commit_files(repo) == ["sim/1234/1234.py", "sim/1234/input.txt"]
    status = _git(repo, "status", "--porcelain").stdout
    assert "README.md" in status and "sim/5555/" in status  # 그대로 남아 있음


def test_previously_committed_but_unpushed_is_pushed(repo, origin):
    d = _problem(repo)
    first = commit_and_push(find_repo(repo, d), d, "m", push=False)
    assert len(_origin_log(origin)) == 1
    res = commit_and_push(find_repo(repo, d), d, "m2")
    assert not res.committed and res.pushed and res.note == f"이전 커밋 {first.commit_hash} 푸시됨"
    assert len(_origin_log(origin)) == 2


def test_first_push_sets_upstream(tmp_path, origin):
    work = tmp_path / "w2"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _identity(work)
    _git(work, "checkout", "-q", "-b", "feature")
    d = _problem(work)
    info = find_repo(work, d)
    assert info.upstream is None
    res = commit_and_push(info, d, "m")
    assert res.pushed and "push -u origin feature" in res.output
    assert find_repo(work).upstream == "origin/feature"


def test_non_fast_forward_reports_pull(repo, origin, tmp_path):
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(origin), str(other))
    _identity(other)
    (other / "x.txt").write_text("x")
    _git(other, "add", "x.txt")
    _git(other, "commit", "-q", "-m", "elsewhere")
    _git(other, "push", "-q")

    d = _problem(repo)
    res = commit_and_push(find_repo(repo, d), d, "mine")
    assert res.committed and not res.pushed and res.failed
    assert "git pull" in res.note
    assert len(_log(repo)) == 2  # 커밋은 로컬에 남음 (force push 없음)
    assert _origin_log(origin)[0] == "elsewhere"


def test_missing_identity_gives_config_hint(tmp_path, origin):
    work = tmp_path / "noid"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
        os.environ.pop(k, None)
    d = _problem(work)
    res = commit_and_push(find_repo(work, d), d, "m", push=False)
    assert res.failed and not res.committed
    assert "user.name" in res.note


def test_toplevel_above_root_uses_full_pathspec(repo, origin):
    root = repo / "swea"
    d = _problem(root, "Queue", 1225)
    info = find_repo(root, d)
    res = commit_and_push(info, d, "nested")
    assert res.pushed and "$ git add -- swea/Queue/1225" in res.output
    assert _commit_files(repo) == ["swea/Queue/1225/1225.py", "swea/Queue/1225/input.txt"]


def test_push_timeout(repo, monkeypatch):
    d = _problem(repo)
    real_run = gitops._run

    def flaky(args, cwd, timeout=gitops.DEFAULT_TIMEOUT):
        if args and args[0] == "push":
            raise subprocess.TimeoutExpired("git push", timeout)
        return real_run(args, cwd, timeout)

    monkeypatch.setattr(gitops, "_run", flaky)
    res = commit_and_push(find_repo(repo, d), d, "m", timeout=7)
    assert res.committed and not res.pushed and res.failed
    assert "시간 초과" in res.note and "7초" in res.note
    assert "[시간 초과]" in res.output


def test_output_masks_tokens(repo, monkeypatch):
    d = _problem(repo)
    real_run = gitops._run

    class CP:
        returncode = 1
        stdout = ""
        stderr = "fatal: unable to access 'https://u:ghp_tok@github.com/u/r.git/': Could not resolve host"

    def fake(args, cwd, timeout=gitops.DEFAULT_TIMEOUT):
        return CP() if args and args[0] == "push" else real_run(args, cwd, timeout)

    monkeypatch.setattr(gitops, "_run", fake)
    res = commit_and_push(find_repo(repo, d), d, "m")
    assert res.failed and "연결" in res.note
    assert "ghp_tok" not in res.output and "***@github.com" in res.output


def test_commit_message_with_korean_and_quotes(repo):
    d = _problem(repo)
    msg = 'solve: 1234. 항아리 "게임" (sim)'
    res = commit_and_push(find_repo(repo, d), d, msg, push=False)
    assert res.committed
    assert _git(repo, "log", "-1", "--format=%s").stdout.strip() == msg


def test_run_env_disables_terminal_prompt(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)

        class CP:
            returncode, stdout, stderr = 0, "", ""

        return CP()

    monkeypatch.setattr(gitops.subprocess, "run", fake_run)
    gitops._run(["status"], None)
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0" and seen["env"]["LC_ALL"] == "C"
