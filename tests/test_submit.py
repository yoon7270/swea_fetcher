"""submit: 소스 변환, compile.do → submit.do 순서/파라미터, 채점 판정. 실서버 호출 없음 (FakeSession + JSON 픽스처).

M9 작업 지시서: 제출은 사용자의 실제 제출 횟수를 소모하므로 회귀를 테스트로 고정한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swea_fetcher import submit
from swea_fetcher.errors import SessionExpired, SubmitError
from swea_fetcher.submit import SubmitContext, parse_result, prepare_source
from tests.conftest import CONTEST_PROB_ID, FIXTURE_DIR, FakeResponse, FakeSession, login_redirect

ID = CONTEST_PROB_ID
BOX_ID = "AZ-xsmtqr73HBIS2"

SKELETON = '''# 1234. A+B
import sys
sys.stdin = open("input.txt", "r")
T = int(input())
for test_case in range(1, T + 1):
    a, b = map(int, input().split())
    print(f"#{test_case} {a + b}")
'''
SKELETON_STRIPPED_BODY = '''T = int(input())
for test_case in range(1, T + 1):
    a, b = map(int, input().split())
    print(f"#{test_case} {a + b}")
'''


def fx(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"submit_{name}.json").read_text(encoding="utf-8"))


def fx_resp(name: str) -> FakeResponse:
    return FakeResponse(200, json_data=fx(name), headers={"Content-Type": "application/json"})


def solver_page(cat_id: str = ID, cat_type: str = "CODE", title: str = "1234. A+B") -> FakeResponse:
    return FakeResponse(
        200,
        text=f"<html><body><form id='mainForm'><input name='contestProbId' value='{ID}'>"
        f"<input name='categoryId' value='{cat_id}'><input name='categoryType' value='{cat_type}'>"
        f"<h3 class='problem_title'>{title}</h3></form></body></html>",
    )


@pytest.fixture
def ctx() -> SubmitContext:
    return SubmitContext(ID, ID, "CODE", "1234. A+B")


@pytest.fixture
def box_ctx() -> SubmitContext:
    return SubmitContext(ID, BOX_ID, "BOX", "1234. A+B")


# =============================================================================
# 픽스처 위생: 계정 식별자·쿠키 없음
# =============================================================================


@pytest.mark.parametrize("path", sorted(FIXTURE_DIR.glob("submit_*.json")), ids=lambda p: p.name)
def test_fixture_has_no_account_or_cookie(path: Path):
    text = path.read_text(encoding="utf-8").lower()
    for needle in ("session=", "cookie", "@", "userid", "user_id", "pwd", "password", "dummy_user"):
        assert needle not in text, f"{path.name} 에 '{needle}'"
    data = json.loads(text)
    assert "result" in data


# =============================================================================
# prepare_source — 소스 변환
# =============================================================================


def test_prepare_strips_skeleton_lines_and_keeps_body():
    out, notes = prepare_source(SKELETON)
    assert "import sys" not in out and "sys.stdin" not in out
    assert out.startswith("# 1234. A+B\n")
    assert SKELETON_STRIPPED_BODY in out
    assert len(notes) == 1 and "import sys" in notes[0]
    compile(out, "<submit>", "exec")


def test_prepare_strips_import_sys_alone():
    out, notes = prepare_source("import sys\nprint(1)\n")
    assert "import sys" not in out and "print(1)" in out and notes


def test_prepare_strips_stdin_line_alone():
    out, notes = prepare_source('sys.stdin = open("input.txt", "r")\nprint(1)\n')
    assert "sys.stdin" not in out and notes


@pytest.mark.parametrize(
    "line",
    [
        "import sys  # 표준 입력",
        "  import sys",
        "sys.stdin=open('input.txt')",
        'sys.stdin = open("input.txt", "r")  # sample',
        "\timport sys\t",
    ],
)
def test_prepare_strips_variants(line):
    out, notes = prepare_source(f"{line}\nprint(1)\n")
    assert "sys" not in out and "print(1)" in out and notes


def test_prepare_keeps_comments_blank_lines_and_line_count():
    src = "# header\n\nimport sys\n\n# body\nx = 1  # note\n\nsys.stdin = open('input.txt')\nprint(x)\n"
    out, _ = prepare_source(src)
    assert "# header" in out and "# body" in out and "x = 1  # note" in out
    # 줄은 지워도 줄바꿈은 남겨 행 번호가 유지된다 (컴파일 오류 행 번호 대조용)
    assert out.count("\n") == src.count("\n")
    assert out.splitlines()[2] == "" and out.splitlines()[7] == ""


def test_prepare_untouched_source_has_no_notes():
    src = "from collections import deque\nprint(deque([1]))\n"
    out, notes = prepare_source(src)
    assert out == src and notes == []


@pytest.mark.parametrize(
    "src",
    [
        "import sys\nsys.setrecursionlimit(10**6)\nprint(1)\n",
        "import sys\ninput = sys.stdin.readline\nprint(input())\n",
        "import sys\nsys.stdin = open('input.txt')\nprint(sys.maxsize)\n",
        "print(1)\nimport sys as s\nsys.exit()\n",
    ],
)
def test_prepare_rejects_remaining_sys_usage(src):
    with pytest.raises(SubmitError) as ei:
        prepare_source(src)
    assert "sys." in str(ei.value)
    assert "setrecursionlimit" in ei.value.hint
    assert ei.value.exit_code == 8


def test_prepare_does_not_flag_names_that_merely_contain_sys():
    out, _ = prepare_source("mysys = 1\nsystem = mysys.bit_length()\nsubsys.x = 2\n")
    assert "mysys" in out and "subsys.x" in out


def test_prepare_sys_check_is_textual_not_ast():
    """정규식 검사라 문자열/주석 안의 `sys.` 도 거부한다 — 보수적(제출 안 함) 방향이라 현 동작 고정."""
    with pytest.raises(SubmitError):
        prepare_source("print('sys.')\n")


def test_prepare_mixed_import_line_is_left_as_is():
    """`import sys, os` 는 현재 구현이 건드리지 않고 로컬 검사도 통과시킨다 (compile.do 의 NK 가 잡는다) — 현 동작 고정."""
    src = "import sys, os\nprint(os.sep)\n"
    out, notes = prepare_source(src)
    assert out == src and notes == []


def test_prepare_rejects_empty_after_strip():
    with pytest.raises(SubmitError, match="비어"):
        prepare_source("import sys\nsys.stdin = open('input.txt')\n\n")


def test_prepare_rejects_over_100kb():
    src = "x = 1\n" * (submit.MAX_SOURCE_BYTES // 6 + 10)
    with pytest.raises(SubmitError, match="100KB"):
        prepare_source(src)


def test_prepare_size_limit_counts_after_strip():
    body = "x = 1\n" * (submit.MAX_SOURCE_BYTES // 6 - 2)
    assert len(body.encode()) < submit.MAX_SOURCE_BYTES
    out, _ = prepare_source("import sys\n" + body)
    assert len(out.encode()) < submit.MAX_SOURCE_BYTES


# =============================================================================
# get_context — 풀이 화면 hidden 값
# =============================================================================


def test_get_context_posts_category_and_reads_hidden(settings):
    s = FakeSession([solver_page(BOX_ID, "BOX", "1234. [03] A+B")])
    ctx = submit.get_context(s, settings, ID, "BOX", BOX_ID)
    call = s.calls[0]
    assert call["method"] == "POST" and call["url"] == submit.client.SOLVER_URL
    assert call["data"] == {"contestProbId": ID, "categoryId": BOX_ID, "categoryType": "BOX", "isPostMethod": "Y"}
    assert ctx == SubmitContext(ID, BOX_ID, "BOX", "1234. [03] A+B")


def test_get_context_default_is_code_with_contest_prob_id(settings):
    s = FakeSession([solver_page()])
    ctx = submit.get_context(s, settings, ID)
    assert s.calls[0]["data"]["categoryType"] == "CODE" and s.calls[0]["data"]["categoryId"] == ID
    assert (ctx.category_type, ctx.category_id) == ("CODE", ID)


def test_get_context_falls_back_to_sent_values_when_hidden_missing(settings):
    s = FakeSession([FakeResponse(200, text="<html><body><h3 class='problem_title'>t</h3></body></html>")])
    ctx = submit.get_context(s, settings, ID, "BOX", BOX_ID)
    assert (ctx.category_type, ctx.category_id, ctx.title) == ("BOX", BOX_ID, "t")


def test_get_context_error_page(settings, error_html):
    with pytest.raises(SubmitError, match="풀이 화면"):
        submit.get_context(FakeSession([FakeResponse(200, text=error_html)]), settings, ID)


def test_get_context_non_200(settings):
    with pytest.raises(SubmitError, match="HTTP 500"):
        submit.get_context(FakeSession([FakeResponse(500, text="")]), settings, ID)


def test_get_context_session_expired_propagates(settings):
    with pytest.raises(SessionExpired):
        submit.get_context(FakeSession([login_redirect()]), settings, ID)


# =============================================================================
# compile_source / submit_source — 요청 파라미터·헤더·순서
# =============================================================================


def _assert_request(call: dict, url: str, ctx: SubmitContext, source: str):
    assert call["method"] == "POST" and call["url"] == url
    assert call["data"] == {
        "source": source,
        "langType": "py",
        "probId": ctx.contest_prob_id,
        "categoryId": ctx.category_id,
        "categoryType": ctx.category_type,
        "useOptimize": "",
    }
    assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert call["headers"]["Referer"] == submit.client.SOLVER_URL
    assert call["timeout"] == 90
    assert call["allow_redirects"] is False


def test_compile_request_shape(box_ctx):
    s = FakeSession([fx_resp("compile_ok")])
    s.cookies.set("SESSION", "cookie-value")
    submit.compile_source(s, box_ctx, "print(1)\n")
    _assert_request(s.calls[0], submit.COMPILE_URL, box_ctx, "print(1)\n")
    assert s.cookies.get("SESSION") == "cookie-value"  # 세션 쿠키가 있는 같은 세션으로 보낸다


def test_submit_request_shape(box_ctx):
    s = FakeSession([fx_resp("pass")])
    res = submit.submit_source(s, box_ctx, "print(1)\n")
    _assert_request(s.calls[0], submit.SUBMIT_URL, box_ctx, "print(1)\n")
    assert res.passed is True


def test_compile_ok_returns_data(ctx):
    data = submit.compile_source(FakeSession([fx_resp("compile_ok")]), ctx, "x")
    assert data["vo"]["exitValue"] == "0"


@pytest.mark.parametrize(
    "fixture, expect",
    [("compile_nk", "import sys"), ("compile_h", "컴파일 오류")],
)
def test_compile_failure_raises_and_maps_reason(ctx, fixture, expect):
    with pytest.raises(SubmitError) as ei:
        submit.compile_source(FakeSession([fx_resp(fixture)]), ctx, "x")
    assert expect in str(ei.value)
    assert "<br>" not in str(ei.value) and "&nbsp;" not in str(ei.value)


def test_compile_h_includes_cleaned_cmp_error(ctx):
    with pytest.raises(SubmitError) as ei:
        submit.compile_source(FakeSession([fx_resp("compile_h")]), ctx, "x")
    assert "SyntaxError: invalid syntax" in str(ei.value)


@pytest.mark.parametrize("code, expect", [("EB", "100KB"), ("NS", "라이브러리"), ("FI", "파일 입력"), ("UP", "package"), ("SC", "System call"), ("ZZ", "컴파일 오류 (ZZ)")])
def test_compile_error_code_mapping(ctx, code, expect):
    data = fx("compile_ok")
    data["vo"]["exitValue"] = code
    with pytest.raises(SubmitError) as ei:
        submit.compile_source(FakeSession([FakeResponse(200, json_data=data)]), ctx, "x")
    assert expect in str(ei.value)


def test_compile_failure_does_not_call_submit(ctx):
    """compile 실패 → submit.do 미호출 (제출 횟수 미소모)."""
    s = FakeSession([fx_resp("compile_nk")])
    with pytest.raises(SubmitError):
        submit.compile_source(s, ctx, "x")
    assert [c["url"] for c in s.calls] == [submit.COMPILE_URL]


@pytest.mark.parametrize("resp", [FakeResponse(500, text=""), FakeResponse(200, text="<html>login</html>"), fx_resp("server_error")])
def test_post_json_errors(ctx, resp):
    with pytest.raises(SubmitError):
        submit.compile_source(FakeSession([resp]), ctx, "x")


def test_post_json_login_redirect_is_session_expired(ctx):
    with pytest.raises(SessionExpired):
        submit.submit_source(FakeSession([login_redirect()]), ctx, "x")


@pytest.mark.parametrize("code, expect", [("ES", "횟수"), ("TU", "시간"), ("AP", "AP"), ("XX", "XX")])
def test_submit_failed_codes(ctx, code, expect):
    data = fx("failed_es")
    data["submitFailed"] = code
    with pytest.raises(SubmitError, match=expect):
        submit.submit_source(FakeSession([FakeResponse(200, json_data=data)]), ctx, "x")


# =============================================================================
# parse_result — processSubmit() 판정
# =============================================================================


def test_parse_pass():
    r = parse_result(fx("pass"))
    assert r.passed is True and r.summary == "Pass"
    assert r.score == "100.00" and r.test_cases == 10 and r.corrected == 10
    assert r.timed_out is False and r.run_error == "" and r.execution_time == "0.123 ms"
    assert r.raw["vo"]["runValue"] == "Pass "


def test_parse_wrong_answer_counts():
    r = parse_result(fx("wrong"))
    assert r.passed is False
    assert r.summary == "오답: 10개 테스트케이스 중 7개 통과"
    assert (r.test_cases, r.corrected, r.score) == (10, 7, "70.00")


def test_parse_timeout():
    r = parse_result(fx("timeout"))
    assert r.passed is False and r.timed_out is True
    assert "제한시간 초과" in r.summary and r.summary.startswith("오답: 10개")


def test_parse_run_error_cleans_html():
    r = parse_result(fx("runerror"))
    assert r.passed is False and "런타임 에러" in r.summary
    assert "ZeroDivisionError" in r.run_error
    assert "<br>" not in r.run_error and "&nbsp;" not in r.run_error


def test_parse_score_only_when_no_testcases():
    r = parse_result(fx("score_only"))
    assert r.passed is False and r.summary == "오답: 40.00 / 100.0"
    assert not r.test_cases and r.corrected is None


def test_parse_grading_result_note():
    r = parse_result(fx("grading_partial"))
    assert "(3,7)" in r.summary and "Output" in r.summary


@pytest.mark.parametrize(
    "patch",
    [
        {"runValue": "Pass ", "timeOut": "Y"},  # Pass 지만 시간 초과
        {"runValue": "Pass ", "runError": "err"},  # Pass 지만 런타임 에러
        {"runValue": "Pass ", "usrScore": "0"},  # Pass 지만 0점
        {"runValue": "Pass ", "usrScore": "0.00"},
        {"runValue": "", "usrScore": "100.00"},  # runValue 에 Pass 없음
    ],
)
def test_parse_pass_requires_all_conditions(patch):
    data = fx("pass")
    data["vo"].update(patch)
    assert parse_result(data).passed is False


def test_parse_unknown_or_empty_response():
    r = parse_result({})
    assert r.passed is False and r.summary == "오답: 0 / 100.0"
    r = parse_result({"result": "success", "vo": None})
    assert r.passed is False


def test_parse_run_error_truncated_to_255():
    data = fx("runerror")
    data["vo"]["runError"] = "e" * 1000
    assert len(parse_result(data).run_error) == 255


def test_parse_keeps_raw_for_diagnosis():
    data = fx("wrong")
    assert parse_result(data).raw is data


# =============================================================================
# 순서: compile → submit (service 가 조합하지만 모듈 단위로도 고정)
# =============================================================================


def test_compile_then_submit_sequence(ctx):
    s = FakeSession([fx_resp("compile_ok"), fx_resp("pass")])
    submit.compile_source(s, ctx, "x")
    res = submit.submit_source(s, ctx, "x")
    assert [c["url"] for c in s.calls] == [submit.COMPILE_URL, submit.SUBMIT_URL]
    assert res.passed


# =============================================================================
# read_solution
# =============================================================================


def test_read_solution(tmp_path):
    (tmp_path / "1234.py").write_text("print(1)\n", encoding="utf-8")
    assert submit.read_solution(tmp_path, 1234) == "print(1)\n"


def test_read_solution_missing(tmp_path):
    with pytest.raises(SubmitError, match="1234.py"):
        submit.read_solution(tmp_path, 1234)


def test_clean_helper():
    assert submit._clean("a&nbsp;<b>b</b><br>c") == "a b\nc"
    assert submit._clean(None) == "" and submit._clean("") == ""
    assert submit._int("7") == 7 and submit._int(7) == 7 and submit._int("") is None and submit._int("x") is None
