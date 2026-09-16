"""storage: 경로 계산, 텍스트 정규화, 저장/충돌/롤백."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from swea_fetcher import storage
from swea_fetcher.errors import AlreadyExists
from swea_fetcher.storage import normalize_text, resolve_problem_dir, save_problem

IN = b"3\n1 2\n3 4\n5 6\n"
OUT = b"#1 3\n#2 7\n#3 11\n"


# =============================================================================
# resolve_problem_dir
# =============================================================================


def test_resolve_ok(root_dir: Path):
    assert resolve_problem_dir(root_dir, "stack", 1234) == (root_dir / "stack" / "1234").resolve()


def test_resolve_topic_is_stripped(root_dir: Path):
    assert resolve_problem_dir(root_dir, "  dp ", 1) == (root_dir / "dp" / "1").resolve()


def test_resolve_nested_topic_is_rejected(root_dir: Path):
    with pytest.raises(ValueError):
        resolve_problem_dir(root_dir, "a/b", 1)


@pytest.mark.parametrize("topic", ["", "   ", None])
def test_resolve_empty_topic(root_dir: Path, topic):
    with pytest.raises(ValueError, match="비어"):
        resolve_problem_dir(root_dir, topic, 1)


@pytest.mark.parametrize("topic", ["..", "../x", "a..b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b"])
def test_resolve_forbidden_topic_chars(root_dir: Path, topic):
    with pytest.raises(ValueError, match="문자"):
        resolve_problem_dir(root_dir, topic, 1)


@pytest.mark.parametrize("num", [0, -1, True, False, "1234", 12.5, None])
def test_resolve_invalid_num(root_dir: Path, num):
    with pytest.raises(ValueError, match="번호"):
        resolve_problem_dir(root_dir, "topic", num)


def test_resolve_result_is_inside_root(root_dir: Path):
    target = resolve_problem_dir(root_dir, "x", 7)
    assert root_dir.resolve() in target.parents


# =============================================================================
# normalize_text
# =============================================================================


@pytest.mark.parametrize(
    "raw, expected",
    [
        (b"a\nb\n", "a\nb\n"),
        (b"a\r\nb\r\n", "a\nb\n"),
        (b"a\rb\r", "a\nb\n"),
        (b"a\nb", "a\nb\n"),  # 끝 개행 보장
        (b"a\nb\n\n\n", "a\nb\n"),  # 끝 개행은 하나로
        (b"", "\n"),
        (b"\xef\xbb\xbfa\n", "a\n"),  # UTF-8 BOM 제거
        ("한글\n".encode("utf-8"), "한글\n"),
        ("한글\n".encode("cp949"), "한글\n"),  # cp949 폴백
        (b"  a  \n", "  a  \n"),  # 앞뒤 공백은 보존
    ],
)
def test_normalize_text(raw, expected):
    assert normalize_text(raw) == expected


def test_normalize_text_undecodable_replaces(caplog):
    import logging

    # utf-8 도 cp949 도 아닌 바이트
    raw = b"\xff\xfe\x81\x00abc"
    with caplog.at_level(logging.WARNING, logger="swea_fetcher.storage"):
        text = normalize_text(raw)
    assert text.endswith("\n")
    assert "abc" in text


# =============================================================================
# save_problem — 정상
# =============================================================================


def test_save_creates_all_files(root_dir, settings, problem_info):
    res = save_problem(root_dir, "sim", problem_info, IN, OUT, settings)
    d = (root_dir / "sim" / "25730").resolve()
    assert res.problem_dir == d
    assert [p.name for p in res.written] == ["input.txt", "output.txt", "25730.py"]
    assert res.skipped == []
    assert (d / "input.txt").read_bytes() == IN
    assert (d / "output.txt").read_bytes() == OUT
    py = (d / "25730.py").read_text(encoding="utf-8")
    assert py.startswith("# 25730. 항아리 게임\n")
    assert 'open("input.txt", "r")' in py


def test_save_writes_lf_only_and_utf8(root_dir, settings, problem_info):
    save_problem(root_dir, "sim", problem_info, b"1\r\n2\r\n", "출력\r\n".encode("cp949"), settings)
    d = root_dir / "sim" / "25730"
    assert (d / "input.txt").read_bytes() == b"1\n2\n"
    assert (d / "output.txt").read_bytes() == "출력\n".encode("utf-8")


def test_save_uses_custom_file_names(root_dir, settings, problem_info):
    s = replace(settings, input_name="in.txt", output_name="out.txt")
    res = save_problem(root_dir, "sim", problem_info, IN, OUT, s)
    assert [p.name for p in res.written] == ["in.txt", "out.txt", "25730.py"]
    assert 'open("in.txt", "r")' in (res.problem_dir / "25730.py").read_text(encoding="utf-8")


def test_save_into_existing_dir_keeps_other_files(root_dir, settings, problem_info):
    d = root_dir / "sim" / "25730"
    d.mkdir(parents=True)
    (d / "notes.md").write_text("keep me")
    save_problem(root_dir, "sim", problem_info, IN, OUT, settings)
    assert (d / "notes.md").read_text() == "keep me"


# =============================================================================
# save_problem — 충돌 / force
# =============================================================================


def test_save_conflict_raises_and_writes_nothing(root_dir, settings, problem_info):
    d = root_dir / "sim" / "25730"
    d.mkdir(parents=True)
    (d / "input.txt").write_text("old")
    with pytest.raises(AlreadyExists) as ei:
        save_problem(root_dir, "sim", problem_info, IN, OUT, settings)
    assert ei.value.existing == [d / "input.txt"]
    assert "--force" in str(ei.value)
    assert (d / "input.txt").read_text() == "old"
    assert not (d / "output.txt").exists()
    assert not (d / "25730.py").exists()


def test_save_conflict_lists_both_files(root_dir, settings, problem_info):
    d = root_dir / "sim" / "25730"
    d.mkdir(parents=True)
    (d / "input.txt").write_text("old")
    (d / "output.txt").write_text("old")
    with pytest.raises(AlreadyExists) as ei:
        save_problem(root_dir, "sim", problem_info, IN, OUT, settings)
    assert set(ei.value.existing) == {d / "input.txt", d / "output.txt"}


def test_save_force_overwrites_io_but_never_py(root_dir, settings, problem_info):
    d = root_dir / "sim" / "25730"
    d.mkdir(parents=True)
    (d / "input.txt").write_text("old")
    (d / "output.txt").write_text("old")
    (d / "25730.py").write_text("# my solution\n")
    res = save_problem(root_dir, "sim", problem_info, IN, OUT, settings, force=True)
    assert (d / "input.txt").read_bytes() == IN
    assert (d / "output.txt").read_bytes() == OUT
    assert (d / "25730.py").read_text() == "# my solution\n"
    assert res.skipped == [d.resolve() / "25730.py"]
    assert [p.name for p in res.written] == ["input.txt", "output.txt"]


def test_save_existing_py_only_is_not_a_conflict(root_dir, settings, problem_info):
    d = root_dir / "sim" / "25730"
    d.mkdir(parents=True)
    (d / "25730.py").write_text("# my solution\n")
    res = save_problem(root_dir, "sim", problem_info, IN, OUT, settings)  # force 없음
    assert (d / "25730.py").read_text() == "# my solution\n"
    assert [p.name for p in res.skipped] == ["25730.py"]


# =============================================================================
# save_problem — 에러 / 롤백
# =============================================================================


def test_save_without_num_raises_value_error(root_dir, settings, problem_info):
    with pytest.raises(ValueError, match="번호"):
        save_problem(root_dir, "sim", replace(problem_info, num=None), IN, OUT, settings)
    assert not (root_dir / "sim").exists()


def test_save_bad_topic_creates_nothing(root_dir, settings, problem_info):
    with pytest.raises(ValueError):
        save_problem(root_dir, "../evil", problem_info, IN, OUT, settings)
    assert list(root_dir.iterdir()) == []
    assert not (root_dir.parent / "evil").exists()


def test_rollback_removes_new_dir_when_write_fails(root_dir, settings, problem_info, monkeypatch):
    real_write = storage._write
    calls = {"n": 0}

    def flaky(path, content):
        calls["n"] += 1
        if calls["n"] == 2:  # output.txt 쓰기에서 실패
            raise OSError("disk full")
        real_write(path, content)

    monkeypatch.setattr(storage, "_write", flaky)
    with pytest.raises(OSError, match="disk full"):
        save_problem(root_dir, "sim", problem_info, IN, OUT, settings)
    assert not (root_dir / "sim" / "25730").exists()


def test_rollback_in_existing_dir_removes_only_written_files(root_dir, settings, problem_info, monkeypatch):
    d = root_dir / "sim" / "25730"
    d.mkdir(parents=True)
    (d / "notes.md").write_text("keep me")

    real_write = storage._write
    calls = {"n": 0}

    def flaky(path, content):
        calls["n"] += 1
        if calls["n"] == 3:  # 25730.py 쓰기에서 실패
            raise OSError("disk full")
        real_write(path, content)

    monkeypatch.setattr(storage, "_write", flaky)
    with pytest.raises(OSError):
        save_problem(root_dir, "sim", problem_info, IN, OUT, settings)
    assert d.exists()
    assert (d / "notes.md").read_text() == "keep me"
    assert not (d / "input.txt").exists()
    assert not (d / "output.txt").exists()
    assert not (d / "25730.py").exists()


def test_decode_happens_before_any_file_is_created(root_dir, settings, problem_info, monkeypatch):
    def boom(data):
        raise RuntimeError("decode boom")

    monkeypatch.setattr(storage, "normalize_text", boom)
    with pytest.raises(RuntimeError):
        save_problem(root_dir, "sim", problem_info, IN, OUT, settings)
    assert not (root_dir / "sim").exists()


# =============================================================================
# M2 추가: force 롤백 복원, save_skeleton
# =============================================================================


def test_rollback_with_force_restores_overwritten_originals(root_dir, settings, problem_info, monkeypatch):
    d = root_dir / "sim" / "25730"
    d.mkdir(parents=True)
    (d / "input.txt").write_bytes(b"old-in")
    (d / "output.txt").write_bytes(b"old-out")

    real_write = storage._write
    calls = {"n": 0}

    def flaky(path, content):
        calls["n"] += 1
        if calls["n"] == 2:  # output.txt 쓰기에서 실패 (input.txt 는 이미 덮어씀)
            raise OSError("disk full")
        real_write(path, content)

    monkeypatch.setattr(storage, "_write", flaky)
    with pytest.raises(OSError):
        save_problem(root_dir, "sim", problem_info, IN, OUT, settings, force=True)
    assert (d / "input.txt").read_bytes() == b"old-in"
    assert (d / "output.txt").read_bytes() == b"old-out"
    assert not (d / "25730.py").exists()


def test_save_skeleton_creates_dir_empty_input_and_py(root_dir, settings, problem_info):
    res = storage.save_skeleton(root_dir, "sim", problem_info, settings)
    d = (root_dir / "sim" / "25730").resolve()
    assert res.problem_dir == d
    assert [p.name for p in res.written] == ["input.txt", "25730.py"]
    assert res.skipped == []
    assert (d / "input.txt").read_bytes() == b""
    assert not (d / "output.txt").exists()
    assert (d / "25730.py").read_text(encoding="utf-8").startswith("# 25730. 항아리 게임\n")


def test_save_skeleton_keeps_existing_files(root_dir, settings, problem_info):
    d = root_dir / "sim" / "25730"
    d.mkdir(parents=True)
    (d / "input.txt").write_text("my sample")
    (d / "25730.py").write_text("# mine")
    res = storage.save_skeleton(root_dir, "sim", problem_info, settings)
    assert res.written == []
    assert [p.name for p in res.skipped] == ["input.txt", "25730.py"]
    assert (d / "input.txt").read_text() == "my sample"
    assert (d / "25730.py").read_text() == "# mine"


def test_save_skeleton_is_idempotent(root_dir, settings, problem_info):
    storage.save_skeleton(root_dir, "sim", problem_info, settings)
    res = storage.save_skeleton(root_dir, "sim", problem_info, settings)
    assert res.written == [] and len(res.skipped) == 2


def test_save_skeleton_without_num(root_dir, settings, problem_info):
    with pytest.raises(ValueError, match="번호"):
        storage.save_skeleton(root_dir, "sim", replace(problem_info, num=None), settings)


def test_save_skeleton_rollback_removes_new_dir(root_dir, settings, problem_info, monkeypatch):
    def boom(path, content):
        raise OSError("disk full")

    monkeypatch.setattr(storage, "_write", boom)
    with pytest.raises(OSError):
        storage.save_skeleton(root_dir, "sim", problem_info, settings)
    assert not (root_dir / "sim" / "25730").exists()


def test_save_skeleton_custom_input_name(root_dir, settings, problem_info):
    s = replace(settings, input_name="in.txt")
    res = storage.save_skeleton(root_dir, "sim", problem_info, s)
    assert [p.name for p in res.written] == ["in.txt", "25730.py"]
    assert 'open("in.txt", "r")' in (res.problem_dir / "25730.py").read_text(encoding="utf-8")
