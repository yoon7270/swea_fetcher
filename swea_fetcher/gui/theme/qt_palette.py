"""앱 QPalette 생성 (스펙 §17.8(c) · §17.9) — QSS 가 닿지 않는 곳(Fusion 이 팔레트로 그리는 코너·팝업 틈·스핀박스 화살표)이
앱 색으로 칠해지게 한다. 테마·모드 전환마다 app.setPalette(qt_palette(tokens.current())) 로 갱신한다.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

from swea_fetcher.gui.theme.tokens import Palette


def qt_palette(p: Palette) -> QPalette:
    """토큰 팔레트 → QPalette. 역할 매핑은 지시서 M22-A 5."""
    pal = QPalette()
    R = QPalette.ColorRole
    mapping = {
        R.Window: p.bg,
        R.WindowText: p.text,
        R.Text: p.text,
        R.ButtonText: p.text,
        R.Base: p.surface,
        R.AlternateBase: p.bg_subtle,
        R.Button: p.secondary,
        R.Mid: p.border_strong,
        R.Dark: p.border_strong,
        R.Midlight: p.border,
        R.Light: p.border,
        R.Highlight: p.primary,
        R.HighlightedText: p.on_primary,
        R.PlaceholderText: p.text_placeholder,
        R.ToolTipBase: p.toast_bg,
        R.ToolTipText: p.toast_text,
        R.Link: p.link,
        R.LinkVisited: p.link,
        R.BrightText: p.on_primary,
    }
    for role, color in mapping.items():
        pal.setColor(role, QColor(color))
    for role in (R.Text, R.ButtonText, R.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.text_disabled))
    return pal
