"""design/icons/app.svg → design/icons/app.ico (256/128/64/48/32/16). 빌드 전에 한 번 실행."""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "design" / "icons" / "app.svg"
ICO = ROOT / "design" / "icons" / "app.ico"
SIZES = (256, 128, 64, 48, 32, 16)


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    renderer = QSvgRenderer(QByteArray(SVG.read_bytes()))
    frames = []
    for s in SIZES:
        img = QImage(s, s, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        renderer.render(p)
        p.end()
        buf = io.BytesIO()
        from PySide6.QtCore import QBuffer, QIODevice

        qb = QBuffer()
        qb.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(qb, "PNG")
        buf.write(bytes(qb.data()))
        buf.seek(0)
        frames.append(Image.open(buf).convert("RGBA"))
    frames[0].save(ICO, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[1:])
    print(f"wrote {ICO} ({ICO.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
