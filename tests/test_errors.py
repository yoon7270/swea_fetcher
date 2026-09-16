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
