"""errors: exit code 규약과 계층 구조."""

from pathlib import Path

import pytest

from swea_fetcher import errors as E


@pytest.mark.parametrize(
    "exc, code",
    [
        (E.ConfigMissing("x"), 1),
        (E.LoginFailed("x"), 1),
        (E.MfaRequired("x"), 1),
        (E.LoginLocked("x"), 1),
        (E.SessionExpired("x"), 1),
        (E.InvalidInput("x"), 2),
        (E.ProblemNotFound("x"), 2),
        (E.ParseError("x"), 2),
        (E.AlreadyExists("x"), 3),
        (E.AttachmentNotFound("x"), 4),
        (E.NetworkError("x"), 5),
    ],
)
def test_exit_codes(exc, code):
    assert isinstance(exc, E.SweaFetchError)
    assert exc.exit_code == code


def test_login_failed_keeps_server_code():
    e = E.LoginFailed("msg", code="LoginIdPwdFail")
    assert e.code == "LoginIdPwdFail"
    assert str(e) == "msg"
    assert E.LoginFailed("msg").code is None


def test_mfa_and_locked_are_login_failed():
    assert issubclass(E.MfaRequired, E.LoginFailed)
    assert issubclass(E.LoginLocked, E.LoginFailed)


def test_attachment_not_found_found_list_is_copied():
    src = ["a.txt"]
    e = E.AttachmentNotFound("x", found=src)
    src.append("b.txt")
    assert e.found == ["a.txt"]
    assert E.AttachmentNotFound("x").found == []


def test_already_exists_existing_paths():
    p = Path("a") / "input.txt"
    e = E.AlreadyExists("x", existing=[p])
    assert e.existing == [p]
    assert E.AlreadyExists("x").existing == []


# --- M2 추가: hint / CheckFailed ---------------------------------------------


def test_check_failed_exit_code():
    assert E.CheckFailed("x").exit_code == 6


def test_default_hint_and_override():
    e = E.NetworkError("x")
    assert e.hint == E.NetworkError.default_hint and e.hint
    e2 = E.NetworkError("x", hint="custom")
    assert e2.hint == "custom"
    e2.hint = "changed"
    assert e2.hint == "changed"


def test_empty_hint_override_suppresses_default():
    assert E.CheckFailed("x", hint="").hint == ""


def test_attachment_not_found_hint_lists_found():
    e = E.AttachmentNotFound("x", found=["a.txt", "b.txt"])
    assert "a.txt, b.txt" in e.hint and "skeleton-only" in e.hint
    assert "없음" in E.AttachmentNotFound("x").hint


def test_already_exists_hint_lists_paths():
    p = Path("r") / "t" / "1" / "input.txt"
    e = E.AlreadyExists("x", existing=[p])
    assert str(p) in e.hint and "--force" in e.hint


def test_invalid_input_hint_has_examples():
    assert "25730" in E.InvalidInput("x").hint


def test_login_failed_subclasses_keep_code_and_own_hint():
    e = E.MfaRequired("m", code="mfa")
    assert e.code == "mfa" and "2단계" in e.hint
    assert "login_state.json" in E.LoginLocked("l").hint
