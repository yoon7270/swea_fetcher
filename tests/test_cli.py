"""cli: 인자 정규화, 종료 코드/힌트 출력, init/migrate/logout/check, fetch 출력. service 는 스텁."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from swea_fetcher import auth, checker, cli, config, service
from swea_fetcher.errors import (
    AlreadyExists,
    AttachmentNotFound,
    CheckFailed,
    ConfigMissing,
    InvalidInput,
    LoginFailed,
    NetworkError,
    ProblemNotFound,
    SweaFetchError,
)
from swea_fetcher.models import SaveResult
from swea_fetcher.service import FetchOutcome, FilePlan
from tests.conftest import CONTEST_PROB_ID, DUMMY_ID, DUMMY_PW

ID = CONTEST_PROB_ID


@pytest.fixture
def cfg(root_dir, fake_keyring):
    """config.CONFIG_DIR(tmp) 에 유효한 .env + keyring 비밀번호."""
    (config.CONFIG_DIR / ".env").write_text(f"SWEA_ROOT={service.quote_env(str(root_dir))}\nSWEA_ID={DUMMY_ID}\n", encoding="utf-8")
    fake_keyring.store[(config.KEYRING_SERVICE, DUMMY_ID)] = DUMMY_PW
    return config.CONFIG_DIR


# =============================================================================
# normalize_argv / parser
# =============================================================================


@pytest.mark.parametrize(
    "argv, expected",
    [
        ([], []),
        (["25730", "sim"], ["fetch", "25730", "sim"]),
        (["fetch", "25730", "sim"], ["fetch", "25730", "sim"]),
        (["init"], ["init"]),
        (["logout", "--all"], ["logout", "--all"]),
        (["check", "sim", "1"], ["check", "sim", "1"]),
        (["-h"], ["-h"]),
        (["--help"], ["--help"]),
        (["--force", "1", "t"], ["fetch", "--force", "1", "t"]),
    ],
)
def test_normalize_argv(argv, expected):
    assert cli.normalize_argv(argv) == expected


def test_fetch_args_parse_all_flags():
    args = cli.build_parser().parse_args(["fetch", "25730", "sim", "--num", "7", "--force", "--skeleton-only", "--dry-run", "--refresh-index", "-v"])
    assert (args.target, args.topic, args.num) == ("25730", "sim", 7)
    assert args.force and args.skeleton_only and args.dry_run and args.refresh_index and args.verbose


def test_no_args_prints_help_and_exits_2(capsys):
    assert cli.main([]) == 2
    assert "swea-fetch" in capsys.readouterr().out


def test_missing_topic_is_argparse_error():
    with pytest.raises(SystemExit) as ei:
        cli.main(["25730"])
    assert ei.value.code == 2


# =============================================================================
# main — 종료 코드 / 힌트
# =============================================================================


@pytest.mark.parametrize(
    "exc, code",
    [
        (ConfigMissing("c"), 1),
        (LoginFailed("l"), 1),
        (InvalidInput("i"), 2),
        (ProblemNotFound("p"), 2),
        (AlreadyExists("a", existing=[Path("x")]), 3),
        (AttachmentNotFound("n"), 4),
        (NetworkError("n"), 5),
        (CheckFailed("k"), 6),
    ],
)
def test_main_maps_domain_errors_to_exit_codes(cfg, monkeypatch, capsys, exc, code):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(cli.service, "fetch_problem", boom)
    assert cli.main([ID, "sim"]) == code
    err = capsys.readouterr().err
    assert f"[오류] {exc}" in err
    if exc.hint:
        assert "→" in err


def test_main_unexpected_error_exit_10(cfg, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli.service, "fetch_problem", boom)
    assert cli.main([ID, "sim"]) == cli.EXIT_UNEXPECTED
    err = capsys.readouterr().err
    assert "RuntimeError: kaboom" in err and "-v" in err
    assert "Traceback" not in err


def test_main_unexpected_error_verbose_prints_traceback(cfg, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli.service, "fetch_problem", boom)
    assert cli.main([ID, "sim", "-v"]) == cli.EXIT_UNEXPECTED
    assert "Traceback" in capsys.readouterr().err


def test_main_keyboard_interrupt_130(cfg, monkeypatch):
    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.service, "fetch_problem", boom)
    assert cli.main([ID, "sim"]) == 130


def test_main_config_missing_without_settings(capsys):
    assert cli.main([ID, "sim"]) == 1
    err = capsys.readouterr().err
    assert "설정이 없습니다" in err and "swea-fetch init" in err


def test_hint_for_login_failed_adds_failure_count(cfg):
    auth._write_failures(config.CONFIG_DIR / config.LOGIN_STATE_FILE_NAME, 2)
    assert "2회" in cli._hint_for(LoginFailed("x"))
    assert "회" not in cli._hint_for(NetworkError("x"))


def test_hint_for_number_not_found_suggests_refresh():
    h = cli._hint_for(InvalidInput("문제 번호 5 을(를) 찾지 못했습니다"))
    assert h.startswith("클럽에 새 문제 상자") and "--refresh-index" in h


def test_hint_for_indents_multiline():
    assert "\n    " in cli._hint_for(InvalidInput("x"))


def test_hint_for_empty_hint_prints_nothing(cfg, monkeypatch, capsys):
    def boom(*a, **k):
        raise CheckFailed("k", hint="")

    monkeypatch.setattr(cli.service, "fetch_problem", boom)
    cli.main([ID, "sim"])
    assert "→" not in capsys.readouterr().err


# =============================================================================
# fetch 출력
# =============================================================================


def _outcome(problem_dir: Path, problem_info, skeleton=False, skipped_py=False, preview=None) -> FetchOutcome:
    problem_dir.mkdir(parents=True, exist_ok=True)
    written, skipped = [], []
    if skeleton:
        (problem_dir / "input.txt").write_text("")
        written.append(problem_dir / "input.txt")
    else:
        (problem_dir / "input.txt").write_text("3\n1 2\n")
        (problem_dir / "output.txt").write_text("#1 3\n")
        written += [problem_dir / "input.txt", problem_dir / "output.txt"]
    py = problem_dir / "25730.py"
    py.write_text("# 25730. 항아리 게임\n")
    (skipped if skipped_py else written).append(py)
    return FetchOutcome(problem_info, None if preview else SaveResult(problem_dir, written, skipped), preview, [], "sim")


def test_fetch_prints_result_and_passes_options(cfg, root_dir, problem_info, monkeypatch, capsys):
    seen = {}

    def fake(settings, target, topic, opts, progress):
        seen.update(target=target, topic=topic, opts=opts, settings=settings)
        progress("[알림] 안내 메시지")
        progress("저장 중")
        return _outcome(root_dir / "sim" / "25730", problem_info)

    monkeypatch.setattr(cli.service, "fetch_problem", fake)
    assert cli.main(["25730", "sim", "--force", "--num", "25730", "--refresh-index"]) == 0
    assert seen["target"] == "25730" and seen["topic"] == "sim"
    assert seen["opts"].force and seen["opts"].refresh_index and seen["opts"].num_override == 25730
    assert not seen["opts"].dry_run and not seen["opts"].skeleton_only
    assert seen["settings"].user_id == DUMMY_ID
    out = capsys.readouterr().out
    assert "[알림] 안내 메시지" in out and "저장 중" not in out
    assert "[OK] 25730. 항아리 게임" in out
    assert "input.txt" in out and "input7_sample.txt" in out and "output.txt" in out
    assert "25730.py" in out and "뼈대 생성" in out


def test_fetch_prints_kept_py(cfg, root_dir, problem_info, monkeypatch, capsys):
    monkeypatch.setattr(cli.service, "fetch_problem", lambda *a: _outcome(root_dir / "sim" / "25730", problem_info, skipped_py=True))
    cli.main([ID, "sim"])
    assert "기존 파일 유지" in capsys.readouterr().out


def test_fetch_skeleton_only_output(cfg, root_dir, problem_info, monkeypatch, capsys):
    monkeypatch.setattr(cli.service, "fetch_problem", lambda *a: _outcome(root_dir / "sim" / "25730", problem_info, skeleton=True))
    assert cli.main([ID, "sim", "--skeleton-only"]) == 0
    out = capsys.readouterr().out
    assert "뼈대만" in out and "빈 파일 생성" in out and "output.txt" not in out


def test_fetch_dry_run_output(cfg, root_dir, problem_info, monkeypatch, capsys):
    preview = {
        "problem_dir": root_dir / "sim" / "25730",
        "files": [
            FilePlan("input.txt", "conflict", "input7_sample.txt", 12, "3 / 1 2"),
            FilePlan("output.txt", "create", "output7_sample.txt", 5, "#1 3"),
            FilePlan("25730.py", "keep"),
        ],
        "needs_force": True,
    }
    monkeypatch.setattr(cli.service, "fetch_problem", lambda *a: FetchOutcome(problem_info, None, preview, [], "sim"))
    assert cli.main([ID, "sim", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "[DRY-RUN] 25730. 항아리 게임" in out and "page_kind=solver" in out
    assert "input7_sample.txt (12 B)" in out and "3 / 1 2" in out
    assert "기존 파일 유지" in out
    assert "[주의] 이미 있음: input.txt" in out and "--force 필요" in out
    assert not (root_dir / "sim").exists()


def test_fetch_dry_run_with_force_says_overwrite(cfg, root_dir, problem_info, monkeypatch, capsys):
    preview = {"problem_dir": root_dir / "sim" / "25730", "files": [FilePlan("input.txt", "overwrite", "i", 1, ""), FilePlan("25730.py", "create")], "needs_force": False}
    monkeypatch.setattr(cli.service, "fetch_problem", lambda *a: FetchOutcome(problem_info, None, preview, [], "sim"))
    cli.main([ID, "sim", "--dry-run", "--force"])
    assert "--force 로 덮어쓰게 됩니다" in capsys.readouterr().out


# =============================================================================
# init / migrate
# =============================================================================


def _feed(monkeypatch, answers: list[str], secrets: list[str]):
    ans, sec = iter(answers), iter(secrets)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(ans))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(sec))


def test_init_writes_env_and_keyring_then_verifies(root_dir, config_dir, fake_keyring, monkeypatch, capsys):
    _feed(monkeypatch, [str(root_dir), DUMMY_ID], [DUMMY_PW, DUMMY_PW])
    verified = {}
    monkeypatch.setattr(cli.service, "verify_login", lambda s: verified.update(user=s.user_id, pw=s.password) or "ok-msg")
    assert cli.run_init(config_dir=config_dir) == 0
    v = config.read_env_file(config_dir)
    assert v["SWEA_ROOT"] == str(root_dir) and v["SWEA_ID"] == DUMMY_ID and "SWEA_PW" not in v
    assert fake_keyring.store == {(config.KEYRING_SERVICE, DUMMY_ID): DUMMY_PW}
    assert verified == {"user": DUMMY_ID, "pw": DUMMY_PW}
    out = capsys.readouterr().out
    assert "[OK] 설정 저장" in out and "[OK] ok-msg" in out
    assert DUMMY_PW not in out


def test_init_no_check_skips_verify(root_dir, config_dir, monkeypatch):
    _feed(monkeypatch, [str(root_dir), DUMMY_ID], [DUMMY_PW, DUMMY_PW])
    monkeypatch.setattr(cli.service, "verify_login", lambda s: pytest.fail("verify_login 호출됨"))
    assert cli.run_init(no_check=True, config_dir=config_dir) == 0


def test_init_reprompts_on_bad_root_and_password_mismatch(root_dir, config_dir, fake_keyring, monkeypatch):
    _feed(monkeypatch, [str(root_dir / "nope"), str(root_dir), DUMMY_ID], ["a", "b", "", "", DUMMY_PW, DUMMY_PW])
    assert cli.run_init(no_check=True, config_dir=config_dir) == 0
    assert fake_keyring.store[(config.KEYRING_SERVICE, DUMMY_ID)] == DUMMY_PW


def test_init_existing_env_declined(root_dir, config_dir, monkeypatch, capsys):
    (config_dir / ".env").write_text("SWEA_ID=old\n", encoding="utf-8")
    _feed(monkeypatch, ["n"], [])
    assert cli.run_init(no_check=True, config_dir=config_dir) == 0
    assert (config_dir / ".env").read_text(encoding="utf-8") == "SWEA_ID=old\n"
    assert "변경하지 않았습니다" in capsys.readouterr().out


def test_init_existing_env_accepted_and_plain_pw_migrated(root_dir, config_dir, fake_keyring, monkeypatch, capsys):
    (config_dir / ".env").write_text("SWEA_ID=old\nSWEA_PW=plain\n", encoding="utf-8")
    _feed(monkeypatch, ["y", str(root_dir), DUMMY_ID], [DUMMY_PW, DUMMY_PW])
    assert cli.run_init(no_check=True, config_dir=config_dir) == 0
    text = (config_dir / ".env").read_text(encoding="utf-8")
    assert "plain" not in text and "SWEA_PW" not in text
    assert "옮겼습니다" in capsys.readouterr().out


def test_init_keyring_failure_leaves_env_untouched(root_dir, config_dir, fake_keyring, monkeypatch):
    fake_keyring.fail = fake_keyring.errors.KeyringError("locked")
    _feed(monkeypatch, [str(root_dir), DUMMY_ID], [DUMMY_PW, DUMMY_PW])
    with pytest.raises(ConfigMissing):
        cli.run_init(no_check=True, config_dir=config_dir)
    assert not (config_dir / ".env").exists()


def test_init_verify_failure_keeps_settings_and_exits_1(root_dir, config_dir, fake_keyring, monkeypatch, capsys):
    _feed(monkeypatch, [str(root_dir), DUMMY_ID], [DUMMY_PW, DUMMY_PW])

    def bad(s):
        raise LoginFailed("bad creds")

    monkeypatch.setattr(cli.service, "verify_login", bad)
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    assert cli.main(["init"]) == 1
    assert (config_dir / ".env").exists() and fake_keyring.store
    assert "bad creds" in capsys.readouterr().err


def test_migrate_moves_plain_password(config_dir, fake_keyring, capsys):
    (config_dir / ".env").write_text(f"SWEA_ROOT=x\nSWEA_ID={DUMMY_ID}\nSWEA_PW=plain-pw\n", encoding="utf-8")
    assert cli.run_init(config_dir=config_dir, migrate=True) == 0
    assert fake_keyring.store == {(config.KEYRING_SERVICE, DUMMY_ID): "plain-pw"}
    text = (config_dir / ".env").read_text(encoding="utf-8")
    assert "plain-pw" not in text and "SWEA_ROOT=x" in text
    out = capsys.readouterr().out
    assert "옮기고" in out and "plain-pw" not in out


def test_migrate_nothing_to_move(config_dir, fake_keyring, capsys):
    (config_dir / ".env").write_text(f"SWEA_ID={DUMMY_ID}\n", encoding="utf-8")
    assert cli.run_init(config_dir=config_dir, migrate=True) == 0
    assert "옮길 것이 없습니다" in capsys.readouterr().out
    fake_keyring.store[(config.KEYRING_SERVICE, DUMMY_ID)] = "pw"
    assert cli.run_init(config_dir=config_dir, migrate=True) == 0
    assert "이미 저장" in capsys.readouterr().out


def test_migrate_without_id(config_dir):
    (config_dir / ".env").write_text("SWEA_PW=plain\n", encoding="utf-8")
    with pytest.raises(ConfigMissing, match="SWEA_ID"):
        cli.run_init(config_dir=config_dir, migrate=True)


def test_init_via_main_uses_default_config_dir(root_dir, fake_keyring, monkeypatch):
    _feed(monkeypatch, [str(root_dir), DUMMY_ID], [DUMMY_PW, DUMMY_PW])
    assert cli.main(["init", "--no-check"]) == 0
    assert (config.CONFIG_DIR / ".env").is_file()


# =============================================================================
# logout
# =============================================================================


def test_logout_removes_session_files(config_dir, capsys):
    (config_dir / "session.json").write_text("{}")
    (config_dir / "login_state.json").write_text("{}")
    (config_dir / ".env").write_text("SWEA_ID=x\n")
    assert cli.run_logout(config_dir=config_dir) == 0
    assert not (config_dir / "session.json").exists() and (config_dir / ".env").exists()
    assert "session.json" in capsys.readouterr().out


def test_logout_nothing(config_dir, capsys):
    assert cli.run_logout(config_dir=config_dir) == 0
    assert "삭제할 파일 없음" in capsys.readouterr().out


def test_logout_all_requires_confirmation(config_dir, fake_keyring, monkeypatch, capsys):
    (config_dir / ".env").write_text(f"SWEA_ID={DUMMY_ID}\n")
    fake_keyring.store[(config.KEYRING_SERVICE, DUMMY_ID)] = "pw"
    monkeypatch.setattr("builtins.input", lambda p="": "n")
    assert cli.run_logout(all_=True, config_dir=config_dir) == 0
    assert (config_dir / ".env").exists() and fake_keyring.store
    assert "취소" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda p="": "y")
    assert cli.run_logout(all_=True, config_dir=config_dir) == 0
    assert not (config_dir / ".env").exists() and fake_keyring.store == {}


def test_logout_all_keyring_failure_still_removes_files(config_dir, fake_keyring, monkeypatch, capsys):
    (config_dir / ".env").write_text(f"SWEA_ID={DUMMY_ID}\n")
    (config_dir / "session.json").write_text("{}")
    fake_keyring.fail = fake_keyring.errors.KeyringError("locked")
    monkeypatch.setattr("builtins.input", lambda p="": "y")
    assert cli.run_logout(all_=True, config_dir=config_dir) == 0
    captured = capsys.readouterr()
    assert "[경고]" in captured.err
    assert not (config_dir / "session.json").exists()
    assert (config_dir / ".env").exists()  # 자격 증명 삭제 실패 시 .env 는 남김 (all_=False 재시도)


def test_logout_via_main(monkeypatch):
    (config.CONFIG_DIR / "session.json").write_text("{}")
    assert cli.main(["logout"]) == 0
    assert not (config.CONFIG_DIR / "session.json").exists()


# =============================================================================
# check
# =============================================================================


def _make_check_dir(root_dir: Path, code: str) -> Path:
    d = root_dir / "sim" / "1234"
    d.mkdir(parents=True)
    (d / "input.txt").write_text("1\n2 3\n", encoding="utf-8")
    (d / "output.txt").write_text("#1 5\n", encoding="utf-8")
    (d / "1234.py").write_text(code, encoding="utf-8")
    return d


def test_check_pass(cfg, root_dir, capsys):
    _make_check_dir(root_dir, "input()\na,b=map(int,input().split())\nprint(f'#1 {a+b}')\n")
    assert cli.main(["check", "sim", "1234", "--timeout", "30"]) == 0
    out = capsys.readouterr().out
    assert "[OK] 1234 통과" in out and "기대 vs 실제" not in out


def test_check_fail_exit_6_with_diff(cfg, root_dir, capsys):
    _make_check_dir(root_dir, "print('#1 6')\n")
    assert cli.main(["check", "sim", "1234", "--timeout", "30"]) == 6
    captured = capsys.readouterr()
    assert "[FAIL] 1234 실패" in captured.out
    assert "~ 기대: #1 5" in captured.out and "실제: #1 6" in captured.out
    assert "[오류]" in captured.err


def test_check_runtime_error_shows_stderr(cfg, root_dir, capsys):
    _make_check_dir(root_dir, "raise SystemExit(3)\n")
    assert cli.main(["check", "sim", "1234", "--timeout", "30"]) == 6
    out = capsys.readouterr().out
    assert "exit 3" in out


def test_check_timeout(cfg, root_dir, capsys):
    _make_check_dir(root_dir, "import time\nwhile True: time.sleep(0.05)\n")
    assert cli.main(["check", "sim", "1234", "--timeout", "1"]) == 6
    assert "시간 초과" in capsys.readouterr().out


def test_check_missing_dir_exit_2(cfg, capsys):
    assert cli.main(["check", "sim", "1234"]) == 2
    assert "문제 폴더가 없습니다" in capsys.readouterr().err


def test_check_bad_topic_exit_2(cfg):
    assert cli.main(["check", "../x", "1234"]) == 2


def test_check_passes_timeout_to_checker(cfg, root_dir, monkeypatch):
    d = _make_check_dir(root_dir, "pass\n")
    seen = {}

    def fake(problem_dir, settings, timeout):
        seen["timeout"] = timeout
        return checker.CheckResult(True, "x", "x", "", 0.1, False, [("same", "x", "x")])

    monkeypatch.setattr(cli.checker, "run_and_compare", fake)
    assert cli.main(["check", "sim", "1234", "--timeout", "2.5"]) == 0
    assert seen["timeout"] == 2.5


# =============================================================================
# M8/M9: submit
# =============================================================================

from swea_fetcher.errors import SubmitError  # noqa: E402
from swea_fetcher.gitops import GitResult  # noqa: E402
from swea_fetcher.service import SubmitOutcome  # noqa: E402
from swea_fetcher.submit import SubmitResult  # noqa: E402


def _submit_result(passed: bool, **kw) -> SubmitResult:
    base = dict(summary="Pass" if passed else "오답: 10개 테스트케이스 중 7개 통과", score="100.00" if passed else "70.00",
                test_cases=10, corrected=10 if passed else 7, execution_time="0.123 ms")
    base.update(kw)
    return SubmitResult(passed, **base)


@pytest.fixture
def submit_stub(cfg, monkeypatch):
    """service.submit_problem 스텁 + 터미널(tty) 흉내. seen 에 호출 인자 기록."""
    seen: dict = {"calls": []}
    st = {"result": _submit_result(True), "git": None, "raise": None}

    def fake(settings, topic, num, *, push=False, message=None, progress=None):
        seen["calls"].append({"topic": topic, "num": num, "push": push, "message": message})
        if st["raise"]:
            raise st["raise"]
        git = st["git"] if push and st["result"].passed else None
        return SubmitOutcome(st["result"], git, ["`import sys` 줄을 빼고 제출합니다"], CONTEST_PROB_ID)

    monkeypatch.setattr(cli.service, "submit_problem", fake)

    class Tty:
        @staticmethod
        def isatty():
            return True

    monkeypatch.setattr(cli.sys, "stdin", Tty())
    st["seen"] = seen
    return st


def _answer(monkeypatch, text: str, prompts: list[str] | None = None):
    def fake_input(prompt=""):
        if prompts is not None:
            prompts.append(prompt)
        return text

    monkeypatch.setattr("builtins.input", fake_input)


def test_submit_prompt_default_is_no(submit_stub, monkeypatch, capsys):
    prompts: list[str] = []
    _answer(monkeypatch, "", prompts)
    assert cli.main(["submit", "sim", "1234"]) == 0
    assert submit_stub["seen"]["calls"] == []
    assert "취소" in capsys.readouterr().out
    assert prompts and "1회 감소" in prompts[0] and "[y/N]" in prompts[0]


@pytest.mark.parametrize("answer", ["n", "N", "no", "yes please", "ㅇ"])
def test_submit_prompt_rejections(submit_stub, monkeypatch, answer):
    _answer(monkeypatch, answer)
    assert cli.main(["submit", "sim", "1234"]) == 0
    assert submit_stub["seen"]["calls"] == []


@pytest.mark.parametrize("answer", ["y", "Y", "yes", " YES "])
def test_submit_prompt_accepts(submit_stub, monkeypatch, answer, capsys):
    _answer(monkeypatch, answer)
    assert cli.main(["submit", "sim", "1234"]) == 0
    assert submit_stub["seen"]["calls"] == [{"topic": "sim", "num": 1234, "push": False, "message": None}]
    out = capsys.readouterr().out
    assert "[PASS] 1234 Pass" in out and "0.123 ms" in out


def test_submit_yes_skips_prompt(submit_stub, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda p="": pytest.fail("프롬프트가 떠서는 안 됨"))
    assert cli.main(["submit", "sim", "1234", "-y"]) == 0
    assert len(submit_stub["seen"]["calls"]) == 1


def test_submit_non_tty_without_yes_refuses(submit_stub, monkeypatch, capsys):
    class NoTty:
        @staticmethod
        def isatty():
            return False

    monkeypatch.setattr(cli.sys, "stdin", NoTty())
    monkeypatch.setattr("builtins.input", lambda p="": pytest.fail("프롬프트가 떠서는 안 됨"))
    assert cli.main(["submit", "sim", "1234"]) == 2
    assert submit_stub["seen"]["calls"] == []
    assert "-y" in capsys.readouterr().err


def test_submit_wrong_answer_exit_8(submit_stub, capsys):
    submit_stub["result"] = _submit_result(False)
    assert cli.main(["submit", "sim", "1234", "-y"]) == 8
    captured = capsys.readouterr()
    assert "[FAIL] 1234 오답: 10개 테스트케이스 중 7개 통과" in captured.out
    assert "[오류] 1234 채점 결과" in captured.err


def test_submit_wrong_answer_with_push_says_not_pushed(submit_stub, capsys):
    submit_stub["result"] = _submit_result(False)
    submit_stub["git"] = GitResult(True, True, "abc", "m", "", "푸시됨")
    assert cli.main(["submit", "sim", "1234", "-y", "--push"]) == 8
    out = capsys.readouterr().out
    assert "Pass 가 아니라 푸시하지 않았습니다" in out and "푸시됨" not in out
    assert submit_stub["seen"]["calls"][0]["push"] is True


def test_submit_run_error_printed(submit_stub, capsys):
    submit_stub["result"] = _submit_result(False, summary="오답 · 런타임 에러", run_error="ZeroDivisionError: division by zero")
    assert cli.main(["submit", "sim", "1234", "-y"]) == 8
    out = capsys.readouterr().out
    assert "--- 런타임 에러 ---" in out and "ZeroDivisionError" in out


def test_submit_push_and_message_forwarded(submit_stub, capsys):
    submit_stub["git"] = GitResult(True, True, "abc1234", "solve: 1234", "", "푸시됨 abc1234")
    assert cli.main(["submit", "sim", "1234", "-y", "--push", "-m", "solve: 1234"]) == 0
    assert submit_stub["seen"]["calls"] == [{"topic": "sim", "num": 1234, "push": True, "message": "solve: 1234"}]
    out = capsys.readouterr().out
    assert "[OK] 푸시됨 abc1234" in out and "solve: 1234" in out


def test_submit_long_message_flag(submit_stub):
    submit_stub["git"] = GitResult(True, True, "abc", "m", "", "푸시됨")
    assert cli.main(["submit", "sim", "1234", "-y", "--push", "--message", "hello"]) == 0
    assert submit_stub["seen"]["calls"][0]["message"] == "hello"


def test_submit_error_exit_8_with_hint(submit_stub, capsys):
    submit_stub["raise"] = SubmitError("허용하지 않는 키워드가 사용되었습니다", hint="코드를 고친 뒤 다시 제출하세요")
    assert cli.main(["submit", "sim", "1234", "-y"]) == 8
    err = capsys.readouterr().err
    assert "허용하지 않는 키워드" in err and "→ 코드를 고친 뒤" in err


def test_submit_nested_topic_and_int_num(submit_stub):
    assert cli.main(["submit", "test/IM_test", "25730", "-y"]) == 0
    assert submit_stub["seen"]["calls"][0] == {"topic": "test/IM_test", "num": 25730, "push": False, "message": None}


def test_submit_requires_int_num():
    with pytest.raises(SystemExit) as ei:
        cli.main(["submit", "sim", "abc", "-y"])
    assert ei.value.code == 2


def test_submit_without_settings_exit_1(monkeypatch, capsys):
    monkeypatch.setattr(cli.service, "submit_problem", lambda *a, **k: pytest.fail("설정 없이 호출됨"))
    assert cli.main(["submit", "sim", "1234", "-y"]) == 1
    assert "설정이 없습니다" in capsys.readouterr().err


def test_check_push_flag_was_removed(cfg, capsys):
    """M7 의 `check --push` 는 M8 에서 삭제 — argparse 오류(exit 2)."""
    with pytest.raises(SystemExit) as ei:
        cli.main(["check", "sim", "1234", "--push"])
    assert ei.value.code == 2
    assert "--push" in capsys.readouterr().err


def test_normalize_argv_keeps_submit_and_push_subcommands():
    assert cli.normalize_argv(["submit", "sim", "1"]) == ["submit", "sim", "1"]
    assert cli.normalize_argv(["push", "sim", "1"]) == ["push", "sim", "1"]
