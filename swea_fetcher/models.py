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
class ImageRef:
    """지문 안 이미지 1개 (M12). data 가 있으면 표시 가능, url 만 있으면 service 가 내려받아야 한다."""

    data: bytes | None = None
    url: str | None = None  # 절대 URL (다운로드 필요 시). data URI 는 None
    alt: str = ""
    error: str | None = None  # 표시 불가 사유 (자리표시 텍스트로 쓰임)


@dataclass(frozen=True)
class ProblemContent:
    """지문(제한사항 + 본문). 파일로 쓰지 않는다 — 메모리와 앱 캐시(config_dir/cache)에만 둔다."""

    limits_html: str = ""  # box3 (없으면 "")
    body_html: str = ""  # box4, sanitize 완료. 이미지는 src="swea-img:N" 토큰
    images: dict[str, ImageRef] = field(default_factory=dict)  # "swea-img:0" → ImageRef


@dataclass(frozen=True)
class SaveResult:
    """save_problem() 결과."""

    problem_dir: Path
    written: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)  # 이미 있어서 건너뛴 파일 (예: {num}.py)
