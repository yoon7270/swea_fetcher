# -*- mode: python ; coding: utf-8 -*-
r"""PyInstaller 스펙 — swea-fetch-gui (M4c).

빌드(Windows):  .venv\Scripts\pyinstaller packaging\swea-fetch-gui.spec --noconfirm
산출:          dist\swea-fetch-gui.exe  (커밋하지 않음 — .gitignore 의 dist/)
빌드(macOS):    python packaging/make_icns.py && .venv/bin/pyinstaller packaging/swea-fetch-gui.spec --noconfirm
산출:          dist/SWEA Fetch.app
Windows 는 onefile + windowed (백신 오탐 시 ONEFILE 을 False 로). macOS 는 .app 번들(onedir 기반).
"""
from pathlib import Path
import os
import sys

IS_MAC = sys.platform == "darwin"

# Qt는 Windows ICU를 사용한다. 다른 앱의 PATH에 있는 동명 ICU/UCRT를
# 수집하면 QtCore import가 실패하므로 시스템 DLL 경로를 먼저 검색한다.
if os.name == "nt":
    os.environ["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32") + os.pathsep + os.environ.get("PATH", "")

ROOT = Path(SPECPATH).parent


def _qt_svg_plugins():
    """체크 표시(QSS image: SVG)와 SVG 아이콘이 exe 에서 보이려면 Qt 의 SVG 이미지 플러그인이 번들에 있어야 한다 (M21).
    PyInstaller 훅이 보통 넣지만 환경에 따라 빠질 수 있어 명시적으로 추가한다."""
    try:
        import PySide6

        base = Path(PySide6.__file__).parent / "plugins"
    except Exception:  # noqa: BLE001
        return []
    out = []
    ext = "dylib" if IS_MAC else "dll"
    prefix = "lib" if IS_MAC else ""
    for sub, name in (("imageformats", f"{prefix}qsvg.{ext}"), ("iconengines", f"{prefix}qsvgicon.{ext}")):
        f = base / sub / name
        if not f.exists():  # PySide6 휠은 plugins 가 Qt/ 아래에 있기도 하다
            f = base.parent / "Qt" / "plugins" / sub / name
        if f.exists():
            out.append((str(f), f"PySide6/plugins/{sub}"))
    return out
PKG = ROOT / "swea_fetcher"
ONEFILE = not IS_MAC  # macOS 는 .app 번들 안에 풀어 둔다 (onefile+windowed 는 권장되지 않음)
ICON = ROOT / "design" / "icons" / ("app.icns" if IS_MAC else "app.ico")

a = Analysis(
    [str(ROOT / "packaging" / "launch_gui.py")],
    pathex=[str(ROOT)],
    binaries=_qt_svg_plugins(),  # qsvg(이미지)·qsvgicon(아이콘) — 체크박스 체크·SVG 아이콘
    datas=[
        (str(PKG / "gui" / "theme" / "icons"), "swea_fetcher/gui/theme/icons"),
        # Pretendard 400/700 + OFL 라이선스 (M21, 원본 무수정). 없으면 앱은 Malgun Gothic 폴백으로 실행
        (str(PKG / "gui" / "theme" / "fonts"), "swea_fetcher/gui/theme/fonts"),
    ],
    hiddenimports=[
        "keyring.backends.macOS" if IS_MAC else "keyring.backends.Windows",
        "keyring.backends.chainer",
        "keyring.backends.fail",
        "PySide6.QtSvg",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 쓰지 않는 Qt 모듈 — 용량 절감
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
        "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtRemoteObjects",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        "tkinter", "pytest", "pytestqt",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="swea-fetch-gui",
        icon=str(ICON) if ICON.exists() else None,
        console=False,
        upx=False,
        strip=False,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="swea-fetch-gui",
        icon=str(ICON) if ICON.exists() else None,
        console=False,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="swea-fetch-gui")

if IS_MAC:
    app = BUNDLE(
        coll if not ONEFILE else exe,
        name="SWEA Fetch.app",
        icon=str(ICON) if ICON.exists() else None,
        bundle_identifier="com.yoon7270.swea-fetch",
        info_plist={
            "CFBundleName": "SWEA Fetch",
            "CFBundleDisplayName": "SWEA Fetch",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
