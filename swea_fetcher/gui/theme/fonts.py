"""번들 글꼴(Pretendard 400·700) 등록 — 스펙 §16.3.

QApplication 생성 직후, QSS 적용 전에 load_fonts() 를 부른다. 파일이 없거나 등록이 실패해도 예외 없이
로그 한 줄만 남기고 계속한다 — tokens.FONT_FAMILY 의 폴백 체인(Malgun Gothic …)이 대신 쓰인다.
글꼴 파일은 원본 그대로 둔다(SIL OFL 1.1, Reserved Font Name — 수정·서브셋 금지).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QFontDatabase

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_FILES = ("Pretendard-Regular.otf", "Pretendard-Bold.otf")  # 400 / 700 두 웨이트만 (스펙 §16.3)
FONT_FAMILY_NAME = "Pretendard"

_log = logging.getLogger(__name__)


def load_fonts(font_dir: Path | None = None) -> list[str]:
    """글꼴 파일을 QFontDatabase 에 등록하고, 등록에 성공한 파일명 목록을 돌려준다 (전부 실패하면 빈 목록)."""
    base = Path(font_dir) if font_dir is not None else FONT_DIR
    loaded: list[str] = []
    for name in FONT_FILES:
        path = base / name
        if not path.is_file():
            _log.warning("글꼴 파일이 없어 건너뜁니다: %s", path)
            continue
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            _log.warning("글꼴 등록 실패(폴백 사용): %s", path)
            continue
        loaded.append(name)
    return loaded


def is_available() -> bool:
    """Pretendard 패밀리가 현재 사용 가능한지 (등록 성공 여부 확인용)."""
    return FONT_FAMILY_NAME in QFontDatabase.families()
