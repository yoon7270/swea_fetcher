"""잔디 기기 간 동기화 (M23): 임시 git 저장소(로컬 bare 원격)에서 두 "기기"(서로 다른 clone) 시나리오를 실측한다. 네트워크 없음."""

from __future__ import annotations

import dataclasses
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from swea_fetcher import gitops, growth, service, solved, solved_sync
from swea_fetcher.config import Settings, _tristate_setting

pytestmark = pytest.mark.skipif(gitops.git_available() is None, reason="git 이 설치되어 있지 않음")

NOW = datetime(2026, 10, 1, 12, 0, 0)


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cp = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and cp.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 실패: {cp.stderr}")
    return cp


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)
    monkeypatch.setattr(growth, "now", lambda: NOW)
    solved_sync.reset_caches()
    yield
    solved_sync.reset_caches()


def _identity(repo: Path) -> None:
    _git(repo, "config", "user.name", "Tester")
    _git(repo, "config", "user.email", "tester@example.invalid")


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    return bare


def _device(tmp_path: Path, origin: Path, name: str, **overrides) -> Settings:
    """clone 하나 = 기기 하나 (자기 config_dir 를 가진다)."""
    work = tmp_path / f"{name}_root"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _identity(work)
    if not (work / "README.md").exists() and _git(work, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0:
        (work / "README.md").write_text("# swea\n", encoding="utf-8")
        _git(work, "add", "README.md")
        _git(work, "commit", "-q", "-m", "init")
        _git(work, "push", "-q", "-u", "origin", "main")
    cfg = tmp_path / f"{name}_cfg"
    cfg.mkdir()
    return Settings(root=work, user_id="u", password="p", config_dir=cfg, **overrides)


def _rec(s: Settings, num: int, at: datetime = NOW, via: str = "swea", title: str = "T") -> None:
    assert solved.record(s, num, "sim", title, via, at=at)


def _nums(s: Settings) -> dict:
    return {d.isoformat(): sorted(i.num for i in v) for d, v in solved.load(s).items()}


def _sync(s: Settings, **kw):
    repo = gitops.find_repo(s.root)
    return service.sync_now(s, reason="manual", **kw), repo


# --- 설정 / 켜짐 판정 ------------------------------------------------------------------------


def test_tristate_parsing():
    assert _tristate_setting("K", "") is None and _tristate_setting("K", " 1 ") is True
    assert _tristate_setting("K", "off") is False and _tristate_setting("K", "???") is None


def test_enabled_rules(tmp_path, origin, settings):
    s = _device(tmp_path, origin, "a")
    assert solved_sync.enabled(s)  # 자동: 저장소 + 원격
    assert not solved_sync.enabled(dataclasses.replace(s, growth=False))  # 성장 기록 끔 → 동기화도 끔
    assert not solved_sync.enabled(dataclasses.replace(s, solved_sync=False))
    solved_sync.reset_caches()
    assert not solved_sync.enabled(settings)  # git 저장소가 아닌 루트: 자동은 꺼짐
    assert solved_sync.enabled(dataclasses.replace(settings, solved_sync=True))


def test_disabled_writes_no_device_file(tmp_path, origin):
    s = _device(tmp_path, origin, "a", solved_sync=False)
    _rec(s, 1)
    assert not solved_sync.sync_dir(s).exists()


# --- 기기 파일 -------------------------------------------------------------------------------


def test_record_writes_device_file_same_as_local_and_is_stable(tmp_path, origin):
    s = _device(tmp_path, origin, "a")
    _rec(s, 2, NOW + timedelta(minutes=1))
    _rec(s, 1)
    path = solved_sync.device_path(s)
    assert path.parent == s.root / ".swea-fetch" / "solved" and path.name.endswith(".json")
    assert solved_sync.device_id(s) == solved_sync.device_id(s)  # 한 번 만들고 유지
    key = lambda days: {d: sorted(v, key=lambda i: i["num"]) for d, v in days.items()}  # noqa: E731 — 기기 파일은 시각순 정렬
    assert key(solved.parse_days(path.read_text(encoding="utf-8"))) == key(solved.read_local(s))
    text = path.read_text(encoding="utf-8")
    assert [i["num"] for i in solved.parse_days(text)["2026-10-01"]] == [1, 2]  # at 순 정렬
    assert solved_sync.sync_device_file(s) is False and path.read_text(encoding="utf-8") == text  # 변경 없으면 다시 쓰지 않음
    assert "code" not in text and "input" not in text


def test_enabling_later_moves_existing_local_records(tmp_path, origin):
    s = _device(tmp_path, origin, "a", solved_sync=False)
    _rec(s, 1)
    on = dataclasses.replace(s, solved_sync=True)
    assert not solved_sync.device_path(on).exists()
    service.growth_solved(on, NOW)  # 잔디 갱신 때 기존 로컬 기록이 기기 파일로
    assert 1 in [i["num"] for v in solved.parse_days(solved_sync.device_path(on).read_text(encoding="utf-8")).values() for i in v]


def test_device_file_keeps_old_records_after_local_clear(tmp_path, origin):
    s = _device(tmp_path, origin, "a")
    _rec(s, 1)
    service.clear_growth(s.config_dir)
    _rec(s, 2, NOW + timedelta(days=1))
    days = solved.parse_days(solved_sync.device_path(s).read_text(encoding="utf-8"))
    assert sorted(i["num"] for v in days.values() for i in v) == [1, 2]


# --- 두 기기 ---------------------------------------------------------------------------------


def test_two_devices_via_fetch_only(tmp_path, origin):
    a = _device(tmp_path, origin, "a")
    b = _device(tmp_path, origin, "b")
    _git(b.root, "pull", "-q", "origin", "main", check=False)
    head_b = _git(b.root, "rev-parse", "HEAD").stdout.strip()
    status_b = _git(b.root, "status", "--porcelain", "--untracked-files=all").stdout

    _rec(a, 100)
    _rec(a, 101, NOW - timedelta(days=1))
    res, _ = _sync(a)
    assert res is not None and res.committed and res.pushed and not res.failed
    assert _git(a.root, "show", "--name-only", "--format=", "HEAD").stdout.split() == [".swea-fetch/solved/" + solved_sync.device_path(a).name]

    _rec(b, 200)  # B 의 같은 날 기록 (자기 파일만 씀)
    assert _nums(b) == {"2026-10-01": [200]}  # fetch 전엔 B 로컬만
    assert solved_sync.refresh_remote(b) is True
    assert _nums(b) == {"2026-09-30": [101], "2026-10-01": [100, 200]}  # 원격에만 있는 A 기록이 합쳐짐

    # B 작업 트리·브랜치 불변 (기기 파일 B 것만 새로 생김)
    assert _git(b.root, "rev-parse", "HEAD").stdout.strip() == head_b
    assert not (b.root / ".swea-fetch" / "solved" / solved_sync.device_path(a).name).exists()
    changed = _git(b.root, "status", "--porcelain", "--untracked-files=all").stdout
    assert changed.replace(status_b, "").split() == ["??", ".swea-fetch/solved/" + solved_sync.device_path(b).name]

    # 동시 기록 → 둘 다 커밋·푸시. 서로 다른 파일이라 충돌 없이 한 쪽이 pull 해도 깔끔
    res_b, _ = _sync(b)
    assert res_b is not None and res_b.committed
    if res_b.failed:  # A 가 먼저 푸시했으므로 non-fast-forward — 사용자가 직접 pull 한다 (도구는 pull 하지 않음)
        _git(b.root, "pull", "-q", "--no-rebase", "--no-edit", "origin", "main")
        res_b, _ = _sync(b)
    assert not res_b.failed
    assert sorted(p.name for p in (b.root / ".swea-fetch" / "solved").glob("*.json")) == sorted([solved_sync.device_path(a).name, solved_sync.device_path(b).name])
    assert _git(b.root, "status", "--porcelain").stdout.strip() == ""


def test_same_problem_same_day_merges_and_swea_wins(tmp_path, origin):
    a = _device(tmp_path, origin, "a")
    b = _device(tmp_path, origin, "b")
    _rec(a, 7, via="local", title="")
    _sync(a)
    _rec(b, 7, NOW + timedelta(hours=1), via="swea", title="Title")
    solved_sync.refresh_remote(b)
    items = solved.load(b)[NOW.date()]
    assert len(items) == 1 and items[0].via == "swea" and items[0].title == "Title"


def test_refresh_remote_throttle_and_silent_failures(tmp_path, origin, settings):
    a = _device(tmp_path, origin, "a")
    _rec(a, 1)
    _sync(a)
    b = _device(tmp_path, origin, "b")
    assert solved_sync.refresh_remote(b) is True
    assert solved_sync.refresh_remote(b) is False  # 10분 스로틀
    # 오프라인(원격 URL 깨짐): fetch 는 실패해도 이미 받은 원격 추적 브랜치로 조용히 계속
    _git(b.root, "remote", "set-url", "origin", str(tmp_path / "nope.git"))
    assert solved_sync.refresh_remote(b, force=True) is False
    assert _nums(b) == {"2026-10-01": [1]}
    # 저장소·원격 없음: 조용히 False
    assert solved_sync.refresh_remote(dataclasses.replace(settings, solved_sync=True), force=True) is False


# --- 커밋 범위 -------------------------------------------------------------------------------


def _problem(s: Settings, num: int = 1234) -> Path:
    d = s.root / "sim" / str(num)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{num}.py").write_text("print(1)\n", encoding="utf-8")
    return d


def test_problem_scope_includes_device_file_and_pass_does_not_commit_alone(tmp_path, origin):
    s = _device(tmp_path, origin, "a", auto_push=True, auto_push_scope="problem", auto_push_on=frozenset({"pass", "watch"}))
    pd = _problem(s)
    _rec(s, 1234)
    res = service.sync_now(s, reason="pass", problem_dir=pd)
    files = _git(s.root, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert res.committed and sorted(files) == sorted(["sim/1234/1234.py", ".swea-fetch/solved/" + solved_sync.device_path(s).name])
    # 문제 폴더 변경 없이 기기 파일만 바뀜: pass 시점엔 묻어가기(커밋 없음) / watch 시점엔 단독 커밋
    _rec(s, 1235)
    r1 = service.sync_now(s, reason="pass", problem_dir=None, scope="problem")  # 문제 폴더 변경 없음 → 단독 커밋 금지
    assert not r1.committed
    r2 = service.sync_now(s, reason="watch")
    assert r2.committed and r2.pushed
    assert _git(s.root, "status", "--porcelain").stdout.strip() == ""


def test_manual_push_problem_includes_device_file(tmp_path, origin):
    s = _device(tmp_path, origin, "a")
    _problem(s)
    _rec(s, 1234)
    service.push_problem(s, "sim", 1234, message="solve: 1234")
    files = _git(s.root, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert ".swea-fetch/solved/" + solved_sync.device_path(s).name in files


def test_gitignored_device_dir_is_skipped_and_noted(tmp_path, origin):
    s = _device(tmp_path, origin, "a")
    (s.root / ".gitignore").write_text(".swea-fetch/\n", encoding="utf-8")
    _problem(s)
    _rec(s, 1234)
    repo = gitops.find_repo(s.root)
    assert solved_sync.pending_commit_paths(s, repo) == []
    assert ".gitignore" in solved_sync.ignored_note(s)
    service.push_problem(s, "sim", 1234, message="solve: 1234")  # 무시돼도 커밋은 정상
    assert "sim/1234/1234.py" in _git(s.root, "show", "--name-only", "--format=", "HEAD").stdout.split()


def test_growth_off_stops_sync(tmp_path, origin):
    s = _device(tmp_path, origin, "a", growth=False)
    assert service.growth_solved(s, NOW) == {}
    assert solved_sync.refresh_remote(s, force=True) is False
    assert solved_sync.pending_commit_paths(s, gitops.find_repo(s.root)) == []
