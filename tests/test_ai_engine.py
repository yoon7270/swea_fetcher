"""ai_engine: 엔진 감지·해석·명령 구성·실행. 실제 codex/claude 는 실행하지 않는다 (_which/_popen 대체)."""

from __future__ import annotations

import subprocess
import os
import sys
from pathlib import Path

import pytest

from swea_fetcher import ai_engine
from swea_fetcher.ai_engine import EngineInfo
from swea_fetcher.errors import AiEngineMissing, AiRunFailed, AiTimeout

CODEX_HELP = "Usage: codex exec [OPTIONS]\n  --sandbox <MODE>\n  --skip-git-repo-check\n  --cd <DIR>\n  --color <WHEN>\n  --output-last-message <FILE>\n  --ephemeral\n"
CLAUDE_HELP = "Usage: claude [options]\n  -p, --print\n  --output-format <fmt>\n  --disallowedTools <tools>\n  --no-session-persistence\n"


class FakeProc:
    def __init__(self, argv, kw, out=b"", err=b"", rc=0, timeout=False, on_communicate=None):
        self.argv, self.kw, self.pid = argv, kw, 4242
        self.returncode = None
        self._out, self._err, self._rc, self._timeout = out, err, rc, timeout
        self.stdin_data: bytes | None = None
        self.killed = False
        self._on = on_communicate

    def poll(self):
        return self.returncode

    def communicate(self, input=None, timeout=None):
        if input is not None:
            self.stdin_data = input
        if self._on:
            self._on(self)
        if self._timeout and not self.killed:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        self.returncode = self._rc
        return self._out, self._err

    def kill(self):
        self.killed = True


class FakeCLI:
    """_popen 대역. --help/--version 은 스크립트 응답, 그 외(본 실행)는 handler 로 처리하고 호출을 기록한다."""

    def __init__(self, help_text: str = "", version: str = "cli 1.2.3\n", **run_kw):
        self.help_text, self.version = help_text, version
        self.run_kw = run_kw
        self.runs: list[FakeProc] = []
        self.aux: list[list[str]] = []
        self.answer_file: bytes | None = None  # codex: --output-last-message 파일에 쓸 내용
        self.scratch_seen: Path | None = None

    def __call__(self, argv, **kw):
        if "--help" in argv:
            self.aux.append(argv)
            return FakeProc(argv, kw, out=self.help_text.encode())
        if "--version" in argv:
            self.aux.append(argv)
            return FakeProc(argv, kw, out=self.version.encode())
        proc = FakeProc(argv, kw, on_communicate=self._write_answer, **self.run_kw)
        self.runs.append(proc)
        self.scratch_seen = Path(kw["cwd"])
        return proc

    def _write_answer(self, proc: FakeProc) -> None:
        if self.answer_file is not None and "--output-last-message" in proc.argv:
            Path(proc.argv[proc.argv.index("--output-last-message") + 1]).write_bytes(self.answer_file)


@pytest.fixture
def codex(monkeypatch):
    monkeypatch.setattr(ai_engine, "_which", lambda n: "C:/bin/codex.cmd" if n == "codex" else None)
    cli = FakeCLI(CODEX_HELP, out="응답 본문".encode())
    monkeypatch.setattr(ai_engine, "_popen", cli)
    return cli


ENGINE_CODEX = EngineInfo("codex", "C:/bin/codex.cmd")
ENGINE_CLAUDE = EngineInfo("claude", "C:/bin/claude.exe")


# --- 해석 / 감지 ------------------------------------------------------------------------


def _which_map(monkeypatch, found: dict[str, str]):
    monkeypatch.setattr(ai_engine, "_which", lambda n: found.get(n))


def test_auto_prefers_codex(monkeypatch):
    _which_map(monkeypatch, {"codex": "C:/c/codex.cmd", "claude": "C:/c/claude.exe"})
    assert ai_engine.resolve("auto").name == "codex"


def test_auto_falls_back_to_claude(monkeypatch):
    _which_map(monkeypatch, {"claude": "C:/c/claude.exe"})
    e = ai_engine.resolve("auto")
    assert e.name == "claude" and e.path == "C:/c/claude.exe"


def test_none_installed_raises_with_install_hint(monkeypatch):
    with pytest.raises(AiEngineMissing) as ei:
        ai_engine.resolve("auto")
    assert "Codex" in ei.value.hint and "Claude Code" in ei.value.hint and "다시 켜" in ei.value.hint


def test_fixed_engine_missing_does_not_fall_back(monkeypatch):
    _which_map(monkeypatch, {"claude": "C:/c/claude.exe"})
    with pytest.raises(AiEngineMissing) as ei:
        ai_engine.resolve("codex")
    assert "자동" in ei.value.hint  # 설정에서 자동으로 바꾸라는 안내
    _which_map(monkeypatch, {"codex": "C:/c/codex.cmd"})
    assert ai_engine.resolve("codex").name == "codex"
    with pytest.raises(AiEngineMissing):
        ai_engine.resolve("claude")


def test_detect_reports_versions_and_missing(monkeypatch):
    _which_map(monkeypatch, {"codex": "C:/c/codex.cmd"})
    monkeypatch.setattr(ai_engine, "_popen", FakeCLI(version="codex-cli 0.9.1\n"))
    found = {e.name: e for e in ai_engine.detect()}
    assert found["codex"].ok and found["codex"].version == "codex-cli 0.9.1"
    assert not found["claude"].found and not found["claude"].ok


def test_api_key_env_only_reports(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert ai_engine.api_key_env() == ["ANTHROPIC_API_KEY"]
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "x"  # 지우지 않는다


# --- 명령 구성 --------------------------------------------------------------------------


def test_codex_command(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_engine, "_popen", FakeCLI(CODEX_HELP))
    argv, answer = ai_engine.build_command(ENGINE_CODEX, str(tmp_path))
    assert argv[:2] == ["C:/bin/codex.cmd", "exec"]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--cd") + 1] == str(tmp_path)
    assert "--skip-git-repo-check" in argv and "--ephemeral" in argv and argv[-1] == "-"
    assert answer == tmp_path / "answer.md"


def test_claude_command(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_engine, "_popen", FakeCLI(CLAUDE_HELP))
    argv, answer = ai_engine.build_command(ENGINE_CLAUDE, str(tmp_path))
    assert argv[:2] == ["C:/bin/claude.exe", "-p"] and answer is None
    assert "--disallowedTools" in argv and "Bash" in argv[argv.index("--disallowedTools") + 1]
    assert "--no-session-persistence" in argv


def test_optional_options_dropped_when_help_lacks_them(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_engine, "_popen", FakeCLI("--sandbox <MODE>\n--cd <DIR>\n"))
    argv, answer = ai_engine.build_command(ENGINE_CODEX, str(tmp_path))
    assert "--ephemeral" not in argv and "--output-last-message" not in argv and "--color" not in argv
    assert "--sandbox" in argv and answer is None


def test_required_option_missing_refuses(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_engine, "_popen", FakeCLI("--cd <DIR>\n"))
    with pytest.raises(AiRunFailed) as ei:
        ai_engine.build_command(ENGINE_CODEX, str(tmp_path))
    assert "--sandbox" in str(ei.value) and "업데이트" in ei.value.hint


def test_help_is_cached(monkeypatch, tmp_path):
    cli = FakeCLI(CODEX_HELP)
    monkeypatch.setattr(ai_engine, "_popen", cli)
    ai_engine.build_command(ENGINE_CODEX, str(tmp_path))
    ai_engine.build_command(ENGINE_CODEX, str(tmp_path))
    assert len(cli.aux) == 1


# --- 모델 선택 (M24.2: 풀이 유형 분류용 가벼운 모델) --------------------------------------------


CODEX_HELP_MODEL = CODEX_HELP + "  -m, --model <MODEL>\n  -c, --config <key=value>\n"
CLAUDE_HELP_MODEL = CLAUDE_HELP + "  --model <model>\n"


def test_codex_command_adds_model_and_low_effort_when_supported(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_engine, "_popen", FakeCLI(CODEX_HELP_MODEL))
    argv, _answer = ai_engine.build_command(ENGINE_CODEX, str(tmp_path), model="gpt-6-luna", effort="low")
    assert argv[argv.index("-m") + 1] == "gpt-6-luna"
    assert "model_reasoning_effort=low" in argv and argv[argv.index("model_reasoning_effort=low") - 1] == "--config"  # 따옴표 없는 TOML 문자열 (Windows .cmd shim 안전)
    assert argv[-1] == "-" and "mcp_servers={}" in argv  # 기존 옵션은 그대로


def test_codex_command_without_model_args_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_engine, "_popen", FakeCLI(CODEX_HELP_MODEL))
    argv, _ = ai_engine.build_command(ENGINE_CODEX, str(tmp_path))
    assert "-m" not in argv and "--model" not in argv and not any(a.startswith("model_reasoning_effort") for a in argv)
    only_model, _ = ai_engine.build_command(ENGINE_CODEX, str(tmp_path), model="gpt-6-luna")
    assert "-m" in only_model and not any(a.startswith("model_reasoning_effort") for a in only_model)


def test_codex_model_flags_fall_back_when_help_lacks_them(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_engine, "_popen", FakeCLI(CODEX_HELP))  # --model / --config 없는 옛 버전
    argv, _ = ai_engine.build_command(ENGINE_CODEX, str(tmp_path), model="gpt-6-luna", effort="low")
    assert "-m" not in argv and "gpt-6-luna" not in argv and not any(a.startswith("model_reasoning_effort") for a in argv)  # 조용히 기본 모델로
    ai_engine._HELP_CACHE.clear()
    monkeypatch.setattr(ai_engine, "_popen", FakeCLI(""))  # help 를 못 읽은 경우도 선택 옵션만 뺀다
    argv, _ = ai_engine.build_command(ENGINE_CODEX, str(tmp_path), model="gpt-6-luna", effort="low")
    assert "-m" not in argv and argv[:2] == ["C:/bin/codex.cmd", "exec"]


def test_claude_command_uses_model_alias_only_when_supported(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_engine, "_popen", FakeCLI(CLAUDE_HELP_MODEL))
    argv, answer = ai_engine.build_command(ENGINE_CLAUDE, str(tmp_path), model="haiku", effort="low")
    assert argv[argv.index("--model") + 1] == "haiku" and answer is None and not any("effort" in a for a in argv)
    ai_engine._HELP_CACHE.clear()
    monkeypatch.setattr(ai_engine, "_popen", FakeCLI(CLAUDE_HELP))
    argv, _ = ai_engine.build_command(ENGINE_CLAUDE, str(tmp_path), model="haiku")
    assert "--model" not in argv
    plain, _ = ai_engine.build_command(ENGINE_CLAUDE, str(tmp_path))
    assert "--model" not in plain


def test_run_passes_model_flags_through_to_the_process(monkeypatch):
    monkeypatch.setattr(ai_engine, "_which", lambda n: "C:/bin/codex.cmd" if n == "codex" else None)
    cli = FakeCLI(CODEX_HELP_MODEL, out="응답".encode())
    monkeypatch.setattr(ai_engine, "_popen", cli)
    res = ai_engine.run(ENGINE_CODEX, "p", model="gpt-6-luna", effort="low")
    assert "gpt-6-luna" in cli.runs[0].argv and res.argv == cli.runs[0].argv and cli.runs[0].stdin_data == b"p"


@pytest.mark.parametrize("text,expected", [
    ("exit 1: Rate limit exceeded, retry later", True),
    ("You've hit your usage limit", True),
    ("HTTP 429 Too Many Requests", True),
    ("quota exceeded", True),
    ("Error 4290 something else", False),
    ("not logged in", False),
    ("실행 실패 (코드 1)", False),
])
def test_is_limit_error_heuristic(text, expected):
    assert ai_engine.is_limit_error(AiRunFailed("GPT 실행 실패", stderr=text)) is expected
    assert ai_engine.is_limit_error(AiRunFailed(text)) is expected


# --- 실행 -------------------------------------------------------------------------------


def test_run_prompt_via_stdin_not_argv(codex):
    prompt = "한글 프롬프트\n`code` & % \"quote\"\n" + "x" * 5000
    res = ai_engine.run(ENGINE_CODEX, prompt)
    proc = codex.runs[0]
    assert proc.stdin_data == prompt.encode("utf-8")  # 한글 UTF-8 왕복
    assert all("한글" not in a and "quote" not in a for a in proc.argv)
    assert res.text == "응답 본문" and res.argv == proc.argv


def test_run_cwd_is_empty_temp_dir_removed_after(codex, tmp_path):
    ai_engine.run(ENGINE_CODEX, "p")
    scratch = codex.scratch_seen
    assert scratch.name.startswith("swea-coach-") and not scratch.exists()
    assert codex.runs[0].kw["cwd"] == str(scratch)
    assert codex.runs[0].argv[codex.runs[0].argv.index("--cd") + 1] == str(scratch)


def test_run_prefers_answer_file_over_stdout(codex):
    codex.answer_file = "파일 답변".encode()
    assert ai_engine.run(ENGINE_CODEX, "p").text == "파일 답변"


def test_run_falls_back_to_stdout_when_no_answer_file(codex):
    assert ai_engine.run(ENGINE_CODEX, "p").text == "응답 본문"


def test_run_strips_ansi_and_bom(codex):
    codex.run_kw["out"] = "\ufeff\x1b[32m초록\x1b[0m 텍스트\n".encode()
    assert ai_engine.run(ENGINE_CODEX, "p").text == "초록 텍스트"


def test_run_truncates_huge_response(codex):
    codex.run_kw["out"] = ("a" * (ai_engine.MAX_RESPONSE_CHARS + 500)).encode()
    res = ai_engine.run(ENGINE_CODEX, "p")
    assert res.truncated and len(res.text) < ai_engine.MAX_RESPONSE_CHARS + 200 and "너무 길어" in res.text


def test_run_empty_response_is_error(codex):
    codex.run_kw["out"] = b"  \n"
    with pytest.raises(AiRunFailed) as ei:
        ai_engine.run(ENGINE_CODEX, "p")
    assert "빈 응답" in str(ei.value)


def test_run_nonzero_exit_keeps_stderr_tail(codex):
    codex.run_kw.update(out=b"", err=("x" * 900 + "END").encode(), rc=2)
    with pytest.raises(AiRunFailed) as ei:
        ai_engine.run(ENGINE_CODEX, "p")
    e = ei.value
    assert "코드 2" in str(e) and e.stderr.endswith("END") and len(e.stderr) == ai_engine.STDERR_TAIL
    assert e.argv[0] == "C:/bin/codex.cmd" and "END" in e.hint


@pytest.mark.parametrize(
    "stderr, expect",
    [("Error: not logged in, please login", "로그인"), ("429 Too Many Requests: rate limit", "한도"), ("segfault", "연결 테스트")],
)
def test_run_failure_hint_heuristics(codex, stderr, expect):
    codex.run_kw.update(out=b"", err=stderr.encode(), rc=1)
    with pytest.raises(AiRunFailed) as ei:
        ai_engine.run(ENGINE_CODEX, "p")
    assert expect in ei.value.hint and stderr in ei.value.hint  # 원문 stderr 도 함께


def test_run_timeout_kills_tree(codex, monkeypatch):
    killed = []
    monkeypatch.setattr(ai_engine, "kill_tree", lambda proc: (killed.append(proc), setattr(proc, "killed", True)))
    codex.run_kw["timeout"] = True
    with pytest.raises(AiTimeout) as ei:
        ai_engine.run(ENGINE_CODEX, "p", timeout=0.01)
    assert len(killed) == 1 and ei.value.code == "timeout"
    assert not codex.scratch_seen.exists()


def test_run_cancel_before_start_spawns_nothing(codex):
    res = ai_engine.run(ENGINE_CODEX, "p", is_cancelled=lambda: True)
    assert res.cancelled and codex.runs == []


def test_run_cancel_during_run(codex):
    flag = {"c": False}
    started = []

    def on_start(proc):
        started.append(proc)
        flag["c"] = True  # 취소 요청이 프로세스 기동 직후 들어온 경우

    res = ai_engine.run(ENGINE_CODEX, "p", on_start=on_start, is_cancelled=lambda: flag["c"])
    assert res.cancelled and started and started[0] is codex.runs[0]


def test_popen_failure_is_clear_error(monkeypatch):
    monkeypatch.setattr(ai_engine, "_popen", lambda argv, **kw: (_ for _ in ()).throw(FileNotFoundError("nope")) if "exec" in argv or "-p" in argv else FakeProc(argv, kw, out=CODEX_HELP.encode()))
    with pytest.raises(AiRunFailed) as ei:
        ai_engine.run(ENGINE_CODEX, "p")
    assert "실행하지 못했습니다" in str(ei.value)


def test_kill_tree_windows_uses_taskkill(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_engine, "_run_quiet", lambda argv: calls.append(argv))
    monkeypatch.setattr(ai_engine.sys, "platform", "win32")
    proc = FakeProc(["x"], {})
    ai_engine.kill_tree(proc)
    assert calls == [["taskkill", "/PID", "4242", "/T", "/F"]] and proc.killed


def test_kill_tree_skips_finished_process(monkeypatch):
    monkeypatch.setattr(ai_engine, "_run_quiet", lambda argv: pytest.fail("이미 끝난 프로세스"))
    proc = FakeProc(["x"], {})
    proc.returncode = 0
    ai_engine.kill_tree(proc)


# --- Windows .cmd shim 왕복 (실제 프로세스 — 가짜 CLI 스크립트, 실제 AI 아님) ----------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows .cmd shim 전용")
def test_cmd_shim_roundtrip(monkeypatch, tmp_path):
    """npm 전역 설치처럼 .cmd shim 을 거쳐도 stdin(한글 포함)·종료 코드가 유지된다."""
    script = tmp_path / "fake_cli.py"
    script.write_text(
        "import sys\n"
        "a = sys.argv[1:]\n"
        "if '--help' in a:\n"
        "    print('--sandbox --skip-git-repo-check --cd --color --output-last-message --ephemeral'); sys.exit(0)\n"
        "data = sys.stdin.buffer.read().decode('utf-8')\n"
        "if 'FAIL' in data:\n"
        "    sys.stderr.write('boom'); sys.exit(3)\n"
        "out = a[a.index('--output-last-message') + 1]\n"
        "open(out, 'wb').write(('echo:' + data).encode('utf-8'))\n",
        encoding="utf-8",
    )
    shim = tmp_path / "codex.cmd"
    shim.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    monkeypatch.setattr(ai_engine, "_which", lambda n: str(shim) if n == "codex" else None)
    monkeypatch.setattr(ai_engine, "_popen", subprocess.Popen)  # 이 테스트만 실제 Popen (가짜 CLI 대상)
    monkeypatch.setattr(ai_engine, "_run_quiet", lambda argv: subprocess.run(argv, capture_output=True))
    engine = ai_engine.resolve("codex")
    res = ai_engine.run(engine, "안녕하세요 & 100% \"따옴표\"\n둘째 줄")
    assert res.text == "echo:안녕하세요 & 100% \"따옴표\"\n둘째 줄"
    with pytest.raises(AiRunFailed) as ei:
        ai_engine.run(engine, "FAIL please")
    assert "코드 3" in str(ei.value) and "boom" in ei.value.stderr


# --- Codex 번들 탐색 (PATH 밖의 앱·확장 codex.exe) ---------------------------------------------


def _touch(p, mtime):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    os.utime(p, (mtime, mtime))
    return p


def test_bundled_codex_prefers_app_then_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_engine.sys, "platform", "win32")
    local, home = tmp_path / "local", tmp_path / "home"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert ai_engine.bundled_codex() is None
    ext = _touch(home / ".vscode/extensions/openai.chatgpt-1.0-win32-x64/bin/windows-x86_64/codex.exe", 3000)
    assert ai_engine.bundled_codex() == str(ext)
    _touch(local / "OpenAI/Codex/bin/aaa/codex.exe", 1000)
    new_app = _touch(local / "OpenAI/Codex/bin/bbb/codex.exe", 2000)
    assert ai_engine.bundled_codex() == str(new_app)  # 앱이 확장보다 먼저, 앱끼리는 최신


REAL_WHICH = ai_engine._which  # conftest 가 테스트마다 _which 를 막기 전에 원본을 잡아 둔다


def test_which_falls_back_to_bundle_only_for_codex_on_windows(monkeypatch):
    monkeypatch.setattr(ai_engine.shutil, "which", lambda n: None)
    monkeypatch.setattr(ai_engine, "bundled_codex", lambda: "C:/app/codex.exe")
    monkeypatch.setattr(ai_engine.sys, "platform", "win32")
    assert REAL_WHICH("codex") == "C:/app/codex.exe"
    assert REAL_WHICH("claude") is None  # 번들 탐색은 codex 만
    monkeypatch.setattr(ai_engine.shutil, "which", lambda n: "C:/path/codex.cmd")
    assert REAL_WHICH("codex") == "C:/path/codex.cmd"  # PATH 가 우선
    monkeypatch.setattr(ai_engine.shutil, "which", lambda n: None)
    monkeypatch.setattr(ai_engine.sys, "platform", "linux")
    assert REAL_WHICH("codex") is None


# --- M18: 둘 다 모드 ---------------------------------------------------------------------


def test_labels_and_short_labels():
    assert ai_engine.ENGINE_LABELS == {"codex": "GPT (Codex)", "claude": "Claude (Claude Code)"}
    assert (ENGINE_CODEX.label, ENGINE_CODEX.short_label) == ("GPT (Codex)", "GPT")
    assert (ENGINE_CLAUDE.label, ENGINE_CLAUDE.short_label) == ("Claude (Claude Code)", "Claude")


def test_install_hint_uses_cli_names(monkeypatch):
    _which_map(monkeypatch, {"claude": "C:/c/claude.exe"})
    with pytest.raises(AiEngineMissing) as ei:
        ai_engine.resolve("codex")
    assert "Codex CLI" in str(ei.value) and "Claude Code CLI" in ei.value.hint


def test_resolve_rejects_both():
    with pytest.raises(ValueError):
        ai_engine.resolve("both")


def test_resolve_all_single_delegates(monkeypatch):
    _which_map(monkeypatch, {"claude": "C:/c/claude.exe"})
    sel = ai_engine.resolve_all("auto")
    assert [e.name for e in sel.engines] == ["claude"] and sel.missing == []
    with pytest.raises(AiEngineMissing):  # 고정 엔진 미설치는 폴백 없음
        ai_engine.resolve_all("codex")


def test_resolve_all_both(monkeypatch):
    _which_map(monkeypatch, {"codex": "C:/c/codex.cmd", "claude": "C:/c/claude.exe"})
    sel = ai_engine.resolve_all("both")
    assert [e.name for e in sel.engines] == ["codex", "claude"] and sel.missing == []
    _which_map(monkeypatch, {"claude": "C:/c/claude.exe"})
    sel = ai_engine.resolve_all("both")
    assert [e.name for e in sel.engines] == ["claude"] and sel.missing == ["codex"]
    _which_map(monkeypatch, {})
    with pytest.raises(AiEngineMissing):
        ai_engine.resolve_all("both")


# --- macOS: Finder 로 연 앱은 PATH 가 비어 있어도 CLI 를 찾는다 ----------------------------------


_REAL_WHICH = ai_engine._which  # conftest 의 autouse 픽스처가 대체하기 전의 진짜 함수


def _fake_exe(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)
    return p


def test_mac_finds_claude_outside_path(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_engine, "_which", _REAL_WHICH)
    monkeypatch.setattr(ai_engine.sys, "platform", "darwin")
    monkeypatch.setattr(ai_engine.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert ai_engine._which("claude") is None
    exe = _fake_exe(tmp_path / ".local/bin/claude")
    assert ai_engine._which("claude") == str(exe)


def test_mac_finds_claude_desktop_bundle_and_prefers_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_engine, "_which", _REAL_WHICH)
    monkeypatch.setattr(ai_engine.sys, "platform", "darwin")
    monkeypatch.setattr(ai_engine.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    base = tmp_path / "Library/Application Support/Claude/claude-code"
    old = _fake_exe(base / "2.1.260/claude.app/Contents/MacOS/claude")
    new = _fake_exe(base / "2.1.286/claude.app/Contents/MacOS/claude")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    assert ai_engine._which("claude") == str(new)


def test_mac_path_wins_over_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_engine, "_which", _REAL_WHICH)
    monkeypatch.setattr(ai_engine.sys, "platform", "darwin")
    monkeypatch.setattr(ai_engine.Path, "home", classmethod(lambda cls: tmp_path))
    _fake_exe(tmp_path / ".local/bin/claude")
    on_path = _fake_exe(tmp_path / "bin/claude")
    monkeypatch.setenv("PATH", str(on_path.parent))
    assert ai_engine._which("claude") == str(on_path)


def test_mac_env_adds_user_bin_dirs_for_node_shims(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_engine.sys, "platform", "darwin")
    monkeypatch.setattr(ai_engine.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".nvm/versions/node/v22.1.0/bin").mkdir(parents=True)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    path = ai_engine._env()["PATH"].split(os.pathsep)
    assert path[:2] == ["/usr/bin", "/bin"] and str(tmp_path / ".nvm/versions/node/v22.1.0/bin") in path
