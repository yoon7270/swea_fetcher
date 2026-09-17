"""풀이 실행·검증: {num}.py 를 input.txt 로 실행해 output.txt 와 행 단위로 비교한다.

- cwd=problem_dir 로 실행 (뼈대가 open("input.txt") 상대경로를 쓰므로)
- stdin 도 input.txt 로 연결 (사용자가 sys.stdin= 줄을 지웠을 때 대비)
- 비교: \\r\\n→\\n, 각 줄 우측 공백 제거, 끝 빈 줄 제거
- 타임아웃 시 프로세스 kill. stdout/stderr 는 MAX_OUTPUT 바이트에서 잘라 표시
- 인터프리터: resolve_python() — exe(동결) 안에서는 sys.executable 이 GUI 자신이므로 PATH 의 python 을 찾는다
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings

DEFAULT_TIMEOUT = 10.0
MAX_OUTPUT = 1_000_000  # 1 MB

DiffRow = tuple[str, str | None, str | None]  # ("same"|"changed"|"missing"|"extra", expected_line, actual_line)


class PythonNotFound(RuntimeError):
    """풀이를 실행할 Python 인터프리터를 찾지 못함."""


def resolve_python(settings: Settings | None = None) -> str:
    """풀이 실행용 Python 경로.

    PyInstaller exe 안에서는 sys.executable 이 GUI 자기 자신이라(복제 창이 뜸) 반드시 실제 인터프리터를 찾는다.
    순서: settings.python(SWEA_PYTHON) → 환경변수 SWEA_PYTHON → (동결 아니면) sys.executable →
          PATH 의 python / python3 / py → 없으면 PythonNotFound.
    """
    candidates: list[str] = []
    if settings is not None and settings.python:
        candidates.append(settings.python)
    if os.environ.get("SWEA_PYTHON"):
        candidates.append(os.environ["SWEA_PYTHON"])
    frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        candidates.append(sys.executable)
    for name in ("python", "python3", "py"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for c in candidates:
        p = Path(c)
        if p.is_file() and p.name.lower() != "swea-fetch-gui.exe":
            return str(p)
    raise PythonNotFound(
        "풀이를 실행할 Python 을 찾지 못했습니다. Python 을 설치해 PATH 에 두거나, "
        "설정 파일(.env)에 SWEA_PYTHON=C:\\...\\python.exe 를 추가하세요"
    )


def _python_cmd(python: str) -> list[str]:
    """py 런처면 -3 을 붙인다."""
    return [python, "-3"] if Path(python).stem.lower() == "py" else [python]


@dataclass
class CheckResult:
    passed: bool
    expected: str
    actual: str
    stderr: str
    elapsed: float
    timed_out: bool
    diff: list[DiffRow] = field(default_factory=list)
    note: str = ""  # 안내 (기대 출력 없음 등)
    returncode: int | None = None
    cancelled: bool = False  # 사용자가 취소 (GUI [취소])


# --- 비교 -------------------------------------------------------------------------


def normalize_lines(text: str) -> list[str]:
    """줄바꿈 통일, 우측 공백 제거, 끝 빈 줄 제거."""
    # "\r\r\n" 은 Windows 텍스트 모드 이중 변환의 흔적 → 줄바꿈 하나로 취급
    text = text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def diff_lines(expected: str, actual: str) -> list[DiffRow]:
    """행 단위 비교. 위치가 같은 행끼리 짝을 맞춘다 (알고리즘 문제 출력은 행 순서가 고정)."""
    exp = normalize_lines(expected)
    act = normalize_lines(actual)
    rows: list[DiffRow] = []
    for i in range(max(len(exp), len(act))):
        e = exp[i] if i < len(exp) else None
        a = act[i] if i < len(act) else None
        if e is None:
            rows.append(("extra", None, a))
        elif a is None:
            rows.append(("missing", e, None))
        elif e == a:
            rows.append(("same", e, a))
        else:
            rows.append(("changed", e, a))
    return rows


def _truncate(data: bytes) -> tuple[str, bool]:
    cut = len(data) > MAX_OUTPUT
    text = data[:MAX_OUTPUT].decode("utf-8", errors="replace")
    return (text + "\n... (출력이 1 MB 를 넘어 잘렸습니다)" if cut else text), cut


# --- 실행 -------------------------------------------------------------------------


def find_solution(problem_dir: Path) -> Path | None:
    """{num}.py 우선, 없으면 main.py, 그다음 유일한 .py."""
    problem_dir = Path(problem_dir)
    cand = problem_dir / f"{problem_dir.name}.py"
    if cand.is_file():
        return cand
    if (problem_dir / "main.py").is_file():
        return problem_dir / "main.py"
    pys = sorted(p for p in problem_dir.glob("*.py"))
    return pys[0] if len(pys) == 1 else None


def run_and_compare(
    problem_dir: Path,
    settings: Settings,
    timeout: float = DEFAULT_TIMEOUT,
    on_start=None,
) -> CheckResult:
    """풀이를 실행해 output.txt 와 비교한다. 파일이 없으면 passed=False + note.

    on_start(proc): 프로세스가 뜬 직후 호출 — GUI 가 [취소] 로 proc.kill() 할 수 있게 핸들을 넘긴다.
    취소되면 cancelled=True, passed=False.
    """
    problem_dir = Path(problem_dir)
    solution = find_solution(problem_dir)
    input_path = problem_dir / settings.input_name
    output_path = problem_dir / settings.output_name

    if solution is None:
        return CheckResult(False, "", "", "", 0.0, False, note=f"풀이 파일이 없습니다 ({problem_dir.name}.py)")
    try:
        python = resolve_python(settings)
    except PythonNotFound as e:
        return CheckResult(False, "", "", "", 0.0, False, note=str(e))
    if not input_path.is_file():
        return CheckResult(False, "", "", "", 0.0, False, note=f"{settings.input_name} 이 없습니다")

    expected = output_path.read_text(encoding="utf-8", errors="replace") if output_path.is_file() else ""
    note = "" if output_path.is_file() else f"기대 출력({settings.output_name})이 없습니다 — 뼈대만 받은 문제. 실행 결과만 표시합니다"

    start = time.perf_counter()
    timed_out = False
    returncode: int | None = None
    with open(input_path, "rb") as stdin:
        creation = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # 창 없는 GUI 에서 콘솔 창 깜빡임 방지
        proc = subprocess.Popen(
            [*_python_cmd(python), "-X", "utf8", str(solution)],
            cwd=str(problem_dir),
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation,
        )
        if on_start is not None:
            on_start(proc)
        try:
            out_b, err_b = proc.communicate(timeout=timeout)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            out_b, err_b = proc.communicate()
            timed_out = True
    elapsed = time.perf_counter() - start
    cancelled = bool(getattr(proc, "_swea_cancelled", False))
    if cancelled:
        actual, _ = _truncate(out_b)
        return CheckResult(False, expected, actual, "", elapsed, False, [], note="취소했습니다", returncode=returncode, cancelled=True)

    actual, _ = _truncate(out_b)
    stderr, _ = _truncate(err_b)
    if timed_out:
        stderr = (stderr + "\n" if stderr else "") + f"[시간 초과] {timeout:.0f}초를 넘어 중단했습니다 (무한 루프?)"

    rows = diff_lines(expected, actual)
    passed = bool(expected.strip()) and not timed_out and returncode == 0 and all(r[0] == "same" for r in rows)
    if returncode not in (0, None) and not timed_out and not note:
        note = f"프로그램이 오류로 끝났습니다 (exit {returncode}) — stderr 를 확인하세요"
    return CheckResult(passed, expected, actual, stderr, elapsed, timed_out, rows, note, returncode)


def format_diff(rows: list[DiffRow]) -> str:
    """CLI 출력용 텍스트. ' ' 같음 / '~' 다름 / '-' 누락 / '+' 초과."""
    mark = {"same": " ", "changed": "~", "missing": "-", "extra": "+"}
    lines = []
    for kind, e, a in rows:
        if kind == "same":
            lines.append(f"  {e}")
        elif kind == "changed":
            lines.append(f"~ 기대: {e}\n  실제: {a}")
        elif kind == "missing":
            lines.append(f"- 기대: {e}  (실제 출력 없음)")
        else:
            lines.append(f"+ 실제: {a}  (기대에 없음)")
    return "\n".join(lines)
