"""template.render_skeleton"""

from dataclasses import replace

from swea_fetcher.template import render_skeleton


def test_skeleton_header_and_body(problem_info):
    src = render_skeleton(problem_info, "input.txt")
    lines = src.splitlines()
    assert lines[0] == "# 25730. 항아리 게임"
    assert lines[1] == "import sys"
    assert lines[2] == 'sys.stdin = open("input.txt", "r")'
    assert lines[3] == "T = int(input())"
    assert lines[4] == "for test_case in range(1, T + 1):"
    assert lines[5] == "    pass"
    assert src.endswith("\n")
    compile(src, "<skeleton>", "exec")  # 문법적으로 유효한 파이썬


def test_skeleton_uses_custom_input_name(problem_info):
    assert 'open("in.txt", "r")' in render_skeleton(problem_info, "in.txt")


def test_skeleton_empty_title(problem_info):
    src = render_skeleton(replace(problem_info, title=""), "input.txt")
    assert src.splitlines()[0] == "# 25730."


def test_skeleton_whitespace_title_is_treated_as_empty(problem_info):
    src = render_skeleton(replace(problem_info, title="   "), "input.txt")
    assert src.splitlines()[0] == "# 25730."


def test_skeleton_title_is_stripped(problem_info):
    src = render_skeleton(replace(problem_info, title="  A+B  "), "input.txt")
    assert src.splitlines()[0] == "# 25730. A+B"


def test_skeleton_no_braces_injection(problem_info):
    """제목에 중괄호가 있어도 str.format 이 깨지지 않아야 한다."""
    src = render_skeleton(replace(problem_info, title="{num} {x}"), "input.txt")
    assert src.splitlines()[0] == "# 25730. {num} {x}"
