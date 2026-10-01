"""M22: gui/**/*.py 에 색 리터럴이 없어야 한다 (색은 tokens.current().<필드> 로만). 위반은 파일:라인 으로 보고."""

from __future__ import annotations

import re
from pathlib import Path

import swea_fetcher.gui as gui_pkg

GUI = Path(gui_pkg.__file__).parent
EXEMPT = {GUI / "theme" / "tokens.py"}
PATTERNS = [
    (re.compile(r"#[0-9A-Fa-f]{6}\b"), "#RRGGBB 리터럴"),
    (re.compile(r"QColor\(\s*[\"']"), "QColor(\"…\")"),
    (re.compile(r"QColor\(\s*\d"), "QColor(r, g, b …)"),
    (re.compile(r"Qt\.GlobalColor\.(?!transparent)"), "Qt.GlobalColor"),
    (re.compile(r"(?<!app\.)setStyleSheet\("), "위젯 setStyleSheet("),  # 앱 전체 QSS(app.setStyleSheet) 적용은 제외
    (re.compile(r"\brgba?\("), "rgb()/rgba()"),
]
SVG_ALLOWED = {"#424A53", "#1A7F37", "#9A6700", "#CF222E", "#FFFFFF", "#656D76"}  # 기본 스트로크 + 상태 아이콘 3색(+error) + 흰 글리프 + 콤보 화살표(#656D76)


def _scan():
    bad = []
    for f in sorted(GUI.rglob("*.py")):
        if f in EXEMPT:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "noqa-color" in line:
                continue
            code = line.split("#", 1)[0] if "#" in line and not re.search(r"#[0-9A-Fa-f]{6}\b", line.split("#", 1)[1][:6]) else line
            for rx, what in PATTERNS:
                target = line if what.startswith("#RRGGBB") else code
                if rx.search(target):
                    bad.append(f"{f.relative_to(GUI.parent.parent)}:{n}: {what}: {line.strip()}")
    return bad


def test_no_hardcoded_colors_in_gui_sources():
    bad = _scan()
    assert not bad, "\n".join(bad)


def test_svg_color_literals_are_whitelisted():
    icons = GUI / "theme" / "icons"
    bad = []
    for f in sorted(icons.glob("*.svg")):
        if f.name == "app.svg":
            continue
        for lit in re.findall(r"#[0-9A-Fa-f]{6}\b", f.read_text(encoding="utf-8")):
            if lit.upper() not in SVG_ALLOWED:
                bad.append(f"{f.name}: {lit}")
    assert not bad, bad
