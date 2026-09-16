"""역할 간 공유 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProblemInfo:
    """parse() 결과. 페이지 종류에 따라 num 이 None 일 수 있다."""

    contest_prob_id: str
    num: int | None  # (C) solver 페이지에서만 채워짐. None 이면 cli 가 --num 요구
    title: str
    input_url: str | None  # 절대 URL
    output_url: str | None
    input_filename: str | None  # 페이지에 표시된 원래 파일명 (안내 메시지용)
    output_filename: str | None
    page_kind: str  # "solver" | "club" | "detail"


@dataclass(frozen=True)
class SaveResult:
    """save_problem() 결과."""

    problem_dir: Path
    written: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)  # 이미 있어서 건너뛴 파일 (예: {num}.py)
