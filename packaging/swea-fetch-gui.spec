# -*- mode: python ; coding: utf-8 -*-
r"""PyInstaller 스펙 — swea-fetch-gui (M4c).

빌드:  .venv\Scripts\pyinstaller packaging\swea-fetch-gui.spec --noconfirm
산출:  dist\swea-fetch-gui.exe  (커밋하지 않음 — .gitignore 의 dist/)
onefile + windowed. 백신 오탐 시 아래 ONEFILE 을 False 로 바꿔 onedir 로.
"""
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = ROOT / "swea_fetcher"
ONEFILE = True

a = Analysis(
    [str(ROOT / "packaging" / "launch_gui.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(PKG / "gui" / "theme" / "icons"), "swea_fetcher/gui/theme/icons")],
    hiddenimports=[
        "keyring.backends.Windows",
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
        icon=str(ROOT / "design" / "icons" / "app.ico"),
        console=False,
        upx=False,
        strip=False,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="swea-fetch-gui",
        icon=str(ROOT / "design" / "icons" / "app.ico"),
        console=False,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="swea-fetch-gui")
