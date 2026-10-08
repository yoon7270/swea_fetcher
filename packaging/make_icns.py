"""design/icons/app.svg → design/icons/app.icns (macOS 전용, iconutil 사용). .app 빌드 전에 한 번 실행."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "design" / "icons" / "app.svg"
ICNS = ROOT / "design" / "icons" / "app.icns"
# iconutil 이 요구하는 iconset 파일명 → 픽셀 크기
SIZES = {
    "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
}


def main() -> int:
    if sys.platform != "darwin":
        print("macOS 에서만 실행할 수 있습니다 (iconutil 필요)", file=sys.stderr)
        return 1
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 — 렌더링에 필요
    renderer = QSvgRenderer(QByteArray(SVG.read_bytes()))
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "app.iconset"
        iconset.mkdir()
        for name, px in SIZES.items():
            img = QImage(px, px, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            renderer.render(p)
            p.end()
            img.save(str(iconset / name), "PNG")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS)], check=True)
    print(f"wrote {ICNS} ({ICNS.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
