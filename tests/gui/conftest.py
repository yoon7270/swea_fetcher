"""GUI 테스트 공통: offscreen 플랫폼, QSettings 를 tmp 로, 워커가 실제 네트워크를 타지 않도록 service 스텁."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SWEA_GUI_MOTION", "off")  # 모션은 기본 off — 애니메이션을 기다리지 않게 (M21-C). 모션 자체 테스트만 켠다

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QSettings  # noqa: E402

from swea_fetcher import config  # noqa: E402
from tests.conftest import DUMMY_ID, DUMMY_PW  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path: Path, monkeypatch):
    """MainWindow 의 QSettings("swea-fetch","gui") 를 tmp ini 파일로 돌린다.

    org/app 생성자는 setDefaultFormat 을 무시하고 항상 NativeFormat(레지스트리)을 쓰므로
    main_window 모듈의 QSettings 이름 자체를 ini 팩토리로 바꾼다.
    """
    from swea_fetcher.gui import main_window

    ini = tmp_path / "qsettings" / "gui.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)

    def factory(*_args, **_kw):
        return QSettings(str(ini), QSettings.Format.IniFormat)

    monkeypatch.setattr(main_window, "QSettings", factory)
    seed = QSettings(str(ini), QSettings.Format.IniFormat)
    seed.setValue("ui/color_mode", "light")  # 기존 값 단정이 OS 모드에 흔들리지 않게 라이트 고정 (M22). 다크 테스트는 모드를 직접 지정
    seed.sync()
    yield


@pytest.fixture(autouse=True)
def _light_tokens():
    """토큰 전역 상태(테마·모드)를 테스트마다 블루 라이트로 되돌린다 (M22)."""
    from swea_fetcher.gui.theme import tokens

    def reset() -> None:
        tokens.set_theme(tokens.DEFAULT_THEME)
        tokens.set_color_mode("light")
        tokens.set_system_dark(False)

    reset()
    yield
    reset()


@pytest.fixture
def valid_config(root_dir: Path, config_dir: Path, fake_keyring) -> Path:
    from swea_fetcher import service

    service.write_env(config_dir, root_dir, DUMMY_ID)
    fake_keyring.store[(config.KEYRING_SERVICE, DUMMY_ID)] = DUMMY_PW
    return config_dir


@pytest.fixture
def main_window(qtbot, valid_config):
    from swea_fetcher.gui.main_window import MainWindow

    win = MainWindow(config_dir=valid_config)
    qtbot.addWidget(win)
    return win


@pytest.fixture
def main_window_no_config(qtbot, config_dir):
    from swea_fetcher.gui.main_window import MainWindow

    win = MainWindow(config_dir=config_dir)
    qtbot.addWidget(win)
    return win
