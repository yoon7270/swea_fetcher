"""mcp_tools: SDK 없이 도구 로직 검증. 네트워크 경계(auth/client/lookup)만 스텁하고 service/storage 는 실제로 돈다."""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from swea_fetcher import errors, mcp_tools, service
from swea_fetcher.errors import (
    AiEngineMissing,
    AiError,
    AiRunFailed,
    AiTimeout,
    AlreadyExists,
    AttachmentNotFound,
    CheckFailed,
    ConfigMissing,
    GitError,
    InvalidInput,
    LoginFailed,
    LoginLocked,
    MfaRequired,
    NetworkError,
    ParseError,
    ProblemNotFound,
    SessionExpired,
    SubmitError,
)
from swea_fetcher.mcp_tools import SweaTools
from tests.conftest import CONTEST_PROB_ID, DUMMY_ID, DUMMY_PW, FakeSession

IN = b"3\n1 2\n3 4\n5 6\n"
OUT = b"#1 3\n#2 7\n#3 11\n"
NUM = 25730


@pytest.fixture
def env(monkeypatch, root_dir, config_dir):
    """설정 파일 + 환경변수 비밀번호로 유효한 설정을 만든다 (키링 접근 없음)."""
    (config_dir / ".env").write_text(f"SWEA_ROOT={root_dir}\nSWEA_ID={DUMMY_ID}\n", encoding="utf-8")
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    return config_dir


@pytest.fixture
def tools(env) -> SweaTools:
    return SweaTools(config_dir=env)


@pytest.fixture
def stubs(monkeypatch, solver_html):
    st = {"calls": [], "explicit": None, "auth_error": None}

    def get_session(settings, explicit=False):
        st["explicit"] = explicit
        st["calls"].append("get_session")
        if st["auth_error"]:
            raise st["auth_error"]
        return FakeSession()

    monkeypatch.setattr(service.auth, "get_session", get_session)
    monkeypatch.setattr(service.client, "fetch_problem_page", lambda s, st_, cid: (solver_html, "solver"))
    monkeypatch.setattr(service.client, "download", lambda s, url, settings=None: IN if "downType=in" in url else OUT)
    monkeypatch.setattr(service.lookup, "find_by_number", lambda s, settings, num, refresh=False: CONTEST_PROB_ID)
    return st


def _dump(*results) -> str:
    return json.dumps(results, ensure_ascii=False)


# 1. 통합 경로 ------------------------------------------------------------------


def test_fetch_saves_three_files(tools, stubs, root_dir):
    r = tools.fetch(NUM, "DFS1")
    assert r["ok"] is True and r["status"] == "saved"
    assert r["num"] == NUM and r["title"] == "항아리 게임" and r["topic"] == "DFS1"
    d = root_dir / "DFS1" / str(NUM)
    assert r["problem_dir"] == str(d)
    assert {f["name"]: f["action"] for f in r["files"]} == {"input.txt": "written", "output.txt": "written", f"{NUM}.py": "written"}
    assert (d / "input.txt").is_file() and (d / "output.txt").is_file() and (d / f"{NUM}.py").is_file()
    assert r["auto_sync"] == "off"
    assert isinstance(r["notices"], list)
    json.dumps(r)  # 직렬화 가능


# 2. 이미 있음 / force ------------------------------------------------------------


def test_second_call_exists_then_force(tools, stubs, root_dir):
    tools.fetch(NUM, "DFS1")
    d = root_dir / "DFS1" / str(NUM)
    (d / "input.txt").write_text("MINE", encoding="utf-8")
    (d / f"{NUM}.py").write_text("# my code\n", encoding="utf-8")
    r = tools.fetch(NUM, "DFS1")
    assert r["ok"] is False and r["status"] == "exists" and r["code"] == "already_exists"
    assert sorted(r["existing"]) == ["input.txt", "output.txt"]
    assert "--force" not in _dump(r) and str(root_dir) not in _dump(r)
    assert (d / "input.txt").read_text(encoding="utf-8") == "MINE"
    r2 = tools.fetch(NUM, "DFS1", force=True)
    assert r2["ok"] is True
    assert (d / "input.txt").read_bytes().replace(b"\r\n", b"\n") == IN
    assert (d / f"{NUM}.py").read_text(encoding="utf-8") == "# my code\n"
    assert {f["name"]: f["action"] for f in r2["files"]}[f"{NUM}.py"] == "kept"


# 3. preview -------------------------------------------------------------------


def test_preview_writes_nothing(tools, stubs, root_dir):
    r = tools.preview(NUM, "DFS1")
    assert r["ok"] is True and r["status"] == "preview" and r["needs_force"] is False
    assert not (root_dir / "DFS1").exists()
    assert all(set(f) == {"name", "action", "source", "size"} for f in r["files"])
    tools.fetch(NUM, "DFS1")
    r2 = tools.preview(NUM, "DFS1")
    assert r2["needs_force"] is True
    assert tools.preview(NUM, "DFS1", force=True)["needs_force"] is False


# 4. 오류 매핑 -----------------------------------------------------------------

ERR_CASES = [
    (ConfigMissing("no cfg"), "config_missing", False),
    (MfaRequired("mfa"), "mfa_required", False),
    (LoginLocked("locked"), "login_locked", False),
    (LoginFailed("guard", code="guard"), "login_guard", False),
    (LoginFailed("bad pw"), "login_failed", False),
    (SessionExpired("exp"), "session_expired", True),
    (InvalidInput("bad"), "invalid_input", False),
    (ProblemNotFound("nf"), "problem_not_found", False),
    (ParseError("parse"), "parse_error", False),
    (AttachmentNotFound("no att", found=["a.zip"]), "attachment_not_found", False),
    (AlreadyExists("exists", existing=[Path("C:/x/input.txt")]), "already_exists", False),
    (NetworkError("net"), "network_error", True),
    (GitError("git"), "git_error", False),
    (CheckFailed("chk"), "unsupported", False),
    (SubmitError("sub"), "unsupported", False),
    # AI 코치(M17) 는 GUI 전용 — MCP 는 일반 SweaFetchError 경로 ("error")
    (AiError("ai"), "error", False),
    (AiEngineMissing("no engine"), "error", False),
    (AiRunFailed("run"), "error", False),
    (AiTimeout("slow"), "error", False),
    (RuntimeError("boom"), "internal_error", False),
]


@pytest.mark.parametrize("exc,code,retryable", ERR_CASES, ids=[c[1] + "-" + type(c[0]).__name__ for c in ERR_CASES])
def test_error_mapping(tools, monkeypatch, exc, code, retryable):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(service, "fetch_problem", boom)
    r = tools.fetch(NUM, "DFS1")
    assert r["ok"] is False and r["code"] == code and r["retryable"] is retryable
    assert set(r) >= {"ok", "status", "code", "message", "hint", "retryable"}
    if code in ("login_failed", "login_guard", "mfa_required", "login_locked"):
        assert "재시도" in r["hint"]
    if code == "attachment_not_found":
        assert "a.zip" in r["message"] and "skeleton_only" in r["hint"]
    if code == "already_exists":
        assert r["status"] == "exists" and r["existing"] == ["input.txt"]
    json.dumps(r)


def test_error_table_covers_all_error_classes():
    """errors.py 에 새 예외가 추가되면 매핑 표(ERR_CASES)에도 추가해야 한다."""
    subs = {c for _, c in inspect.getmembers(errors, inspect.isclass) if issubclass(c, errors.SweaFetchError)}
    subs.discard(errors.SweaFetchError)
    covered = {type(c[0]) for c in ERR_CASES}
    assert subs <= covered, f"매핑 미정의 예외: {subs - covered}"


# 5. internal_error ----------------------------------------------------------------


def test_internal_error_hides_message(tools, monkeypatch, caplog):
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f"secret {DUMMY_PW} here")))
    r = tools.fetch(NUM, "DFS1")
    assert r["code"] == "internal_error" and r["message"] == "내부 오류: RuntimeError"
    assert "secret" not in _dump(r) and DUMMY_PW not in _dump(r)
    assert DUMMY_PW not in caplog.text  # 로그에도 비밀번호 없음


# 6. redact ---------------------------------------------------------------------


def test_redact_password_cookie_and_id(tools, monkeypatch):
    msg = f"fail {DUMMY_PW} SESSION=abcdef123 Cookie: SESSION=zzz; x=1 user {DUMMY_ID}"
    monkeypatch.setattr(service, "fetch_problem", lambda *a, **k: (_ for _ in ()).throw(NetworkError(msg)))
    r = tools.fetch(NUM, "DFS1")
    dumped = _dump(r)
    assert r["code"] == "network_error"
    for bad in (DUMMY_PW, "abcdef123", "zzz", DUMMY_ID):
        assert bad not in dumped


def test_no_secrets_in_any_result(tools, stubs):
    results = [
        tools.status(),
        tools.status(check_login=True),
        tools.fetch(NUM, "DFS1"),
        tools.fetch(NUM, "DFS1"),
        tools.preview(NUM, "DFS1"),
        tools.topics(),
        tools.recent(),
    ]
    dumped = _dump(*results)
    assert DUMMY_PW not in dumped and DUMMY_ID not in dumped
    assert "password_source" not in dumped and "cookie" not in dumped.lower()


# 7. config -----------------------------------------------------------------------


def test_config_missing_then_created_without_restart(tmp_path, monkeypatch, stubs, root_dir):
    cfg = tmp_path / "cfg2"
    cfg.mkdir()
    t = SweaTools(config_dir=cfg)
    s = t.status()
    assert s["ok"] is True and s["configured"] is False and "swea-fetch init" in s["next_step"]
    f = t.fetch(NUM, "DFS1")
    assert f["ok"] is False and f["code"] == "config_missing" and "swea-fetch init" in f["hint"]
    (cfg / ".env").write_text(f"SWEA_ROOT={root_dir}\nSWEA_ID={DUMMY_ID}\n", encoding="utf-8")
    monkeypatch.setenv("SWEA_PW", DUMMY_PW)
    assert t.fetch(NUM, "DFS1")["ok"] is True


def test_status_configured(tools, root_dir):
    r = tools.status()
    assert r["ok"] and r["configured"] is True and r["login_ok"] is None
    assert r["root"] == str(root_dir) and r["root_exists"] is True
    assert r["user_id_masked"] == "du***" and r["password_stored"] is True
    assert r["session_cached"] is False and r["auto_sync_on_save"] is False


def test_mask_user_id():
    assert mcp_tools.mask_user_id("abcdef@ssafy.com") == "ab***@ssafy.com"
    assert mcp_tools.mask_user_id("abcdef") == "ab***"


# 8. 자동 push 차단 ------------------------------------------------------------------


def test_auto_push_disabled(tools, stubs, monkeypatch):
    monkeypatch.setenv("SWEA_AUTO_PUSH", "1")
    monkeypatch.setenv("SWEA_AUTO_PUSH_ON", "save")
    synced = []
    monkeypatch.setattr(service, "sync_now", lambda *a, **k: synced.append(1))
    assert tools.status()["auto_sync_on_save"] is True
    r = tools.fetch(NUM, "DFS1")
    assert r["ok"] and r["auto_sync"] == "disabled_in_mcp" and not synced


def test_auto_sync_off_when_not_configured(tools, stubs, monkeypatch):
    synced = []
    monkeypatch.setattr(service, "sync_now", lambda *a, **k: synced.append(1))
    assert tools.fetch(NUM, "DFS1")["auto_sync"] == "off" and not synced


# 9. 지문 비추출 ---------------------------------------------------------------------


def test_no_content_extraction(tools, stubs, monkeypatch):
    seen = []
    real = service.fetch_problem

    def spy(settings, target, topic, opts=None, progress=None):
        seen.append((opts, progress))
        return real(settings, target, topic, opts, progress)

    monkeypatch.setattr(service, "fetch_problem", spy)
    tools.fetch(NUM, "DFS1")
    tools.preview(NUM, "DFS1")
    assert len(seen) == 2
    for opts, progress in seen:
        assert opts.with_content is False and opts.cache_content is False and progress is None
    assert seen[1][0].dry_run is True and seen[0][0].dry_run is False


# 10. 동시성 ----------------------------------------------------------------------


def test_calls_are_serialized(tools, monkeypatch):
    state = {"cur": 0, "max": 0}
    guard = threading.Lock()

    def slow(*a, **k):
        with guard:
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
        time.sleep(0.05)
        with guard:
            state["cur"] -= 1
        raise InvalidInput("stop")

    monkeypatch.setattr(service, "fetch_problem", slow)
    ths = [threading.Thread(target=tools.fetch, args=(NUM, "DFS1")) for _ in range(4)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert state["max"] == 1


def test_busy_when_lock_held(env, monkeypatch):
    t = SweaTools(config_dir=env, lock_timeout=0.05)
    started, release = threading.Event(), threading.Event()

    def hold(*a, **k):
        started.set()
        release.wait(5)
        raise InvalidInput("done")

    monkeypatch.setattr(service, "fetch_problem", hold)
    th = threading.Thread(target=t.fetch, args=(NUM, "DFS1"))
    th.start()
    assert started.wait(5)
    r = t.topics()
    release.set()
    th.join()
    assert r["ok"] is False and r["code"] == "busy" and r["retryable"] is True


# 11. 입력 검증 --------------------------------------------------------------------


@pytest.mark.parametrize("problem", ["", "   ", True, "9" * 301, None, 1.5])
def test_invalid_problem(tools, stubs, problem):
    r = tools.fetch(problem, "DFS1")
    assert r["ok"] is False and r["code"] == "invalid_input"


@pytest.mark.parametrize("topic", ["", "x" * 101, "..", "../evil", "123", "a/b/c/d/e", None])
def test_invalid_topic_no_files(tools, stubs, root_dir, tmp_path, topic):
    r = tools.fetch(NUM, topic)
    assert r["ok"] is False and r["code"] == "invalid_input"
    assert list(root_dir.iterdir()) == []
    assert not (tmp_path / "evil").exists()


def test_int_problem_is_stringified(tools, stubs, monkeypatch):
    seen = []
    real = service.fetch_problem
    monkeypatch.setattr(service, "fetch_problem", lambda s, target, *a, **k: (seen.append(target), real(s, target, *a, **k))[1])
    assert tools.fetch(NUM, "DFS1")["ok"]
    assert seen == [str(NUM)]


# 12. 목록 -------------------------------------------------------------------------


def test_recent_clamp_and_shape(tools, stubs):
    tools.fetch(NUM, "DFS1")
    r = tools.recent(0)
    assert r["ok"] and len(r["items"]) == 1
    it = r["items"][0]
    assert it["num"] == NUM and it["topic"] == "DFS1" and it["title"] == "항아리 게임" and "T" in it["saved_at"]
    seen = []
    orig = service.list_recent
    tools_mod = mcp_tools.service
    tools_mod.list_recent = lambda s, n: (seen.append(n), orig(s, n))[1]
    try:
        tools.recent(0)
        tools.recent(999)
        tools.recent("x")
    finally:
        tools_mod.list_recent = orig
    assert seen == [1, 50, 10]


def test_topics_truncated(tools, root_dir):
    for i in range(205):
        (root_dir / f"T{i:03}").mkdir()
    r = tools.topics()
    assert r["ok"] and r["count"] == 205 and len(r["topics"]) == 200 and r["truncated"] is True
    small = SweaTools(config_dir=tools._config_dir)
    for d in list(root_dir.iterdir())[5:]:
        d.rmdir()
    r2 = small.topics()
    assert "truncated" not in r2 and r2["count"] == 5


# 13. status(check_login) 가드 유지 -----------------------------------------------------


def test_status_check_login_not_explicit(tools, stubs):
    r = tools.status(check_login=True)
    assert r["login_ok"] is True and stubs["explicit"] is False


def test_status_check_login_guard(tools, stubs):
    stubs["auth_error"] = LoginFailed(errors.GUARD_MSG, code="guard")
    r = tools.status(check_login=True)
    assert r["ok"] is False and r["code"] == "login_guard"


# 14. 정적 검사 ---------------------------------------------------------------------


@pytest.mark.parametrize("name", ["mcp_tools.py", "mcp_server.py"])
def test_no_stdout_usage(name):
    src = (Path(mcp_tools.__file__).parent / name).read_text(encoding="utf-8")
    assert "print(" not in src and "sys.stdout" not in src


def test_mcp_tools_does_not_import_sdk():
    code = "import sys, swea_fetcher.mcp_tools; assert not [m for m in sys.modules if m == 'mcp' or m.startswith('mcp.')]"
    subprocess.run([sys.executable, "-c", code], check=True, cwd=Path(mcp_tools.__file__).parents[1])
