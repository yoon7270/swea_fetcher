"""checker: 정규화/diff, 풀이 파일 탐색, 실제 subprocess 실행·비교."""

from __future__ import annotations

from pathlib import Path

import pytest

from swea_fetcher import checker
from swea_fetcher.checker import diff_lines, find_solution, format_diff, normalize_lines, run_and_compare

# =============================================================================
# normalize_lines / diff_lines / format_diff
# =============================================================================


@pytest.mark.parametrize(
    "text, expected",
    [
        ("a\nb\n", ["a", "b"]),
        ("a\r\nb\r\n", ["a", "b"]),
        ("a\r\r\nb\r\r\n", ["a", "b"]),  # Windows 텍스트 모드 이중 변환
        ("a  \nb\t\n", ["a", "b"]),  # 우측 공백 제거
        ("  a\n", ["  a"]),  # 좌측 공백은 보존
        ("a\n\n\n", ["a"]),
        ("", []),
        ("\n\n", []),
        ("a\n\nb\n", ["a", "", "b"]),  # 중간 빈 줄은 보존
    ],
)
def test_normalize_lines(text, expected):
    assert normalize_lines(text) == expected


def test_diff_same():
    rows = diff_lines("#1 3\n#2 7\n", "#1 3\r\n#2 7 \r\n")
    assert rows == [("same", "#1 3", "#1 3"), ("same", "#2 7", "#2 7")]


def test_diff_changed_missing_extra():
    assert diff_lines("a\nb\nc\n", "a\nX\n") == [("same", "a", "a"), ("changed", "b", "X"), ("missing", "c", None)]
    assert diff_lines("a\n", "a\nb\n") == [("same", "a", "a"), ("extra", None, "b")]


def test_diff_both_empty():
    assert diff_lines("", "") == []


def test_format_diff_markers():
    text = format_diff([("same", "s", "s"), ("changed", "e", "a"), ("missing", "m", None), ("extra", None, "x")])
    lines = text.splitlines()
    assert lines[0] == "  s"
    assert lines[1].startswith("~ 기대: e") and lines[2].strip().startswith("실제: a")
    assert lines[3].startswith("- 기대: m")
    assert lines[4].startswith("+ 실제: x")


# =============================================================================
# find_solution
# =============================================================================


def test_find_solution_prefers_num_py(tmp_path):
    d = tmp_path / "1234"
    d.mkdir()
    (d / "main.py").write_text("")
    (d / "1234.py").write_text("")
    (d / "other.py").write_text("")
    assert find_solution(d) == d / "1234.py"


def test_find_solution_main_py_then_single_py(tmp_path):
    d = tmp_path / "1234"
    d.mkdir()
    (d / "main.py").write_text("")
    (d / "x.py").write_text("")
    assert find_solution(d) == d / "main.py"
    (d / "main.py").unlink()
    assert find_solution(d) == d / "x.py"
    (d / "y.py").write_text("")
    assert find_solution(d) is None  # 여러 개면 판단 불가


def test_find_solution_none(tmp_path):
    d = tmp_path / "1234"
    d.mkdir()
    assert find_solution(d) is None


# =============================================================================
# run_and_compare (실제 python subprocess)
# =============================================================================


@pytest.fixture
def problem_dir(root_dir: Path) -> Path:
    d = root_dir / "sim" / "1234"
    d.mkdir(parents=True)
    (d / "input.txt").write_text("2\n1 2\n3 4\n", encoding="utf-8")
    (d / "output.txt").write_text("#1 3\n#2 7\n", encoding="utf-8")
    return d


SOLUTION_OK = '''import sys
sys.stdin = open("input.txt", "r")
T = int(input())
for tc in range(1, T + 1):
    a, b = map(int, input().split())
    print(f"#{tc} {a + b}")
'''


def test_run_pass(problem_dir, settings):
    (problem_dir / "1234.py").write_text(SOLUTION_OK, encoding="utf-8")
    res = run_and_compare(problem_dir, settings, timeout=30)
    assert res.passed is True
    assert res.returncode == 0 and res.timed_out is False
    assert res.note == "" and res.stderr == ""
    assert all(k == "same" for k, _, _ in res.diff)
    assert res.elapsed > 0


def test_run_uses_stdin_when_solution_reads_stdin_only(problem_dir, settings):
    (problem_dir / "1234.py").write_text(
        "T=int(input())\nfor tc in range(1,T+1):\n    a,b=map(int,input().split())\n    print(f'#{tc} {a+b}')\n",
        encoding="utf-8",
    )
    assert run_and_compare(problem_dir, settings, timeout=30).passed is True


def test_run_wrong_answer(problem_dir, settings):
    (problem_dir / "1234.py").write_text("print('#1 3')\nprint('#2 8')\n", encoding="utf-8")
    res = run_and_compare(problem_dir, settings, timeout=30)
    assert res.passed is False
    assert res.diff[1][0] == "changed" and res.diff[1] == ("changed", "#2 7", "#2 8")
    assert res.returncode == 0 and res.note == ""


def test_run_missing_output_line(problem_dir, settings):
    (problem_dir / "1234.py").write_text("print('#1 3')\n", encoding="utf-8")
    res = run_and_compare(problem_dir, settings, timeout=30)
    assert res.passed is False
    assert [k for k, _, _ in res.diff] == ["same", "missing"]


def test_run_runtime_error_sets_stderr_and_note(problem_dir, settings):
    (problem_dir / "1234.py").write_text("print('#1 3')\nprint('#2 7')\nraise ValueError('boom')\n", encoding="utf-8")
    res = run_and_compare(problem_dir, settings, timeout=30)
    assert res.passed is False  # 출력이 맞아도 exit != 0 이면 실패
    assert res.returncode not in (0, None)
    assert "ValueError: boom" in res.stderr
    assert "exit" in res.note


def test_run_timeout_kills_process(problem_dir, settings):
    (problem_dir / "1234.py").write_text("import time\nprint('#1 3', flush=True)\nwhile True:\n    time.sleep(0.05)\n", encoding="utf-8")
    res = run_and_compare(problem_dir, settings, timeout=1.0)
    assert res.timed_out is True and res.passed is False
    assert "시간 초과" in res.stderr
    assert res.elapsed < 10


def test_run_no_solution_file(problem_dir, settings):
    res = run_and_compare(problem_dir, settings)
    assert res.passed is False and "1234.py" in res.note and res.diff == []


def test_run_no_input_file(problem_dir, settings):
    (problem_dir / "1234.py").write_text("print(1)\n", encoding="utf-8")
    (problem_dir / "input.txt").unlink()
    res = run_and_compare(problem_dir, settings)
    assert res.passed is False and "input.txt" in res.note


def test_run_without_expected_output_never_passes(problem_dir, settings):
    (problem_dir / "output.txt").unlink()
    (problem_dir / "1234.py").write_text(SOLUTION_OK, encoding="utf-8")
    res = run_and_compare(problem_dir, settings, timeout=30)
    assert res.passed is False
    assert "기대 출력" in res.note
    assert res.actual.splitlines()[:2] == ["#1 3", "#2 7"]
    assert all(k == "extra" for k, _, _ in res.diff)


def test_run_empty_expected_output_never_passes(problem_dir, settings):
    (problem_dir / "output.txt").write_text("\n", encoding="utf-8")
    (problem_dir / "1234.py").write_text("pass\n", encoding="utf-8")
    assert run_and_compare(problem_dir, settings, timeout=30).passed is False


def test_run_custom_file_names(root_dir, settings):
    from dataclasses import replace

    s = replace(settings, input_name="in.txt", output_name="out.txt")
    d = root_dir / "t" / "7"
    d.mkdir(parents=True)
    (d / "in.txt").write_text("1\n5 5\n", encoding="utf-8")
    (d / "out.txt").write_text("#1 10\n", encoding="utf-8")
    (d / "7.py").write_text("T=int(input())\na,b=map(int,input().split())\nprint(f'#1 {a+b}')\n", encoding="utf-8")
    assert run_and_compare(d, s, timeout=30).passed is True


def test_run_utf8_output_roundtrip(problem_dir, settings):
    (problem_dir / "output.txt").write_text("한글\n", encoding="utf-8")
    (problem_dir / "1234.py").write_text("print('한글')\n", encoding="utf-8")
    assert run_and_compare(problem_dir, settings, timeout=30).passed is True


def test_truncate_marks_cut():
    text, cut = checker._truncate(b"x" * (checker.MAX_OUTPUT + 10))
    assert cut is True and "잘렸습니다" in text
    text, cut = checker._truncate(b"abc")
    assert (text, cut) == ("abc", False)
