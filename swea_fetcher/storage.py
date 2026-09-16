"""폴더 계산, 중복 검사, 파일 쓰기, 실패 시 롤백.

저장 규칙: {root}/{topic}/{num}/ 아래에 input.txt, output.txt, {num}.py
- input/output 이 이미 있으면 force 없이는 아무것도 쓰지 않는다 (AlreadyExists)
- {num}.py 는 force 여도 절대 덮어쓰지 않는다 (사용자 풀이 보호)
- 쓰기 도중 실패하면 새로 만든 폴더는 통째로, 기존 폴더면 이번에 쓴 파일만 삭제
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from .config import Settings
from .errors import AlreadyExists
from .models import ProblemInfo, SaveResult
from .template import render_skeleton

log = logging.getLogger("swea_fetcher.storage")

_FORBIDDEN_TOPIC_CHARS = re.compile(r'[/\\:*?"<>|]')


# --- 경로 ------------------------------------------------------------------------


def resolve_problem_dir(root: Path, topic: str, num: int) -> Path:
    """{root}/{topic}/{num} 을 계산한다. topic 이 부적절하거나 root 밖이면 ValueError."""
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("주제 폴더 이름이 비어 있습니다")
    if ".." in topic or _FORBIDDEN_TOPIC_CHARS.search(topic):
        raise ValueError(f"주제 폴더 이름에 쓸 수 없는 문자가 있습니다: {topic!r}")
    if not isinstance(num, int) or isinstance(num, bool) or num <= 0:
        raise ValueError(f"문제 번호가 올바르지 않습니다: {num!r}")

    root_r = Path(root).resolve()
    target = (root_r / topic / str(num)).resolve()
    if root_r != target and root_r not in target.parents:
        raise ValueError(f"저장 경로가 루트 밖입니다: {target}")
    return target


# --- 텍스트 정규화 ---------------------------------------------------------------


def normalize_text(data: bytes) -> str:
    """utf-8 → cp949 순으로 디코드. 줄바꿈은 \\n, 끝에 \\n 하나 보장."""
    text: str
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp949")
        except UnicodeDecodeError:
            log.warning("첨부 인코딩을 판별하지 못해 일부 문자를 치환합니다")
            text = data.decode("utf-8", errors="replace")
    if text.startswith("﻿"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n"


# --- 저장 ----------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def save_problem(
    root: Path,
    topic: str,
    info: ProblemInfo,
    input_bytes: bytes,
    output_bytes: bytes,
    settings: Settings,
    force: bool = False,
) -> SaveResult:
    """입력·출력·뼈대를 한 번에 저장한다. 실패 시 이번에 만든 것만 되돌린다."""
    if info.num is None:
        raise ValueError("문제 번호(num)가 없어 저장 폴더를 정할 수 없습니다")
    problem_dir = resolve_problem_dir(root, topic, info.num)

    input_path = problem_dir / settings.input_name
    output_path = problem_dir / settings.output_name
    py_path = problem_dir / f"{info.num}.py"

    # 1) 충돌 검사 — 아무것도 쓰기 전에
    existing = [p for p in (input_path, output_path) if p.exists()]
    if existing and not force:
        raise AlreadyExists(
            f"이미 저장된 파일이 있습니다: {', '.join(str(p) for p in existing)} "
            f"(덮어쓰려면 --force)",
            existing=existing,
        )

    # 2) 디코드/정규화는 파일을 만들기 전에 끝낸다
    input_text = normalize_text(input_bytes)
    output_text = normalize_text(output_bytes)

    created_dir = not problem_dir.exists()
    written: list[Path] = []
    skipped: list[Path] = []
    try:
        problem_dir.mkdir(parents=True, exist_ok=True)
        _write(input_path, input_text)
        written.append(input_path)
        _write(output_path, output_text)
        written.append(output_path)
        if py_path.exists():
            skipped.append(py_path)  # force 여도 사용자 코드는 보호
        else:
            _write(py_path, render_skeleton(info, settings.input_name))
            written.append(py_path)
    except Exception:
        _rollback(problem_dir, created_dir, written)
        raise

    log.info("저장 완료: %s (%d files)", problem_dir, len(written))
    return SaveResult(problem_dir=problem_dir, written=written, skipped=skipped)


def _rollback(problem_dir: Path, created_dir: bool, written: list[Path]) -> None:
    """새 폴더면 통째로 삭제, 기존 폴더면 이번에 쓴 파일만 삭제."""
    try:
        if created_dir:
            shutil.rmtree(problem_dir, ignore_errors=True)
        else:
            for p in written:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
    except OSError as e:  # 롤백 실패는 원래 예외를 가리지 않도록 로그만
        log.warning("롤백 중 오류: %s", e)
