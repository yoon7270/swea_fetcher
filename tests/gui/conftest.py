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


from PySide6.QtCore import QObject, Signal  # noqa: E402


class FakeRecommendWorker(QObject):
    """오늘의 추천 워커 대역 (M24): 스레드·네트워크·AI 없음. 테스트가 시그널을 직접 내보내 흐름을 구동한다.

    생성 기록(`instances`)에 mode·start_level·consented 가 남는다. finish() 로 끝났음을 알린다.
    """

    rule_ready = Signal(object)
    ai_started = Signal(object)
    ai_ready = Signal(object)
    catalog_progress = Signal(int, int)
    catalog_updated = Signal(object)
    catalog_failed = Signal(str, str, bool)
    notice = Signal(str)
    classify_started = Signal()
    classify_progress = Signal(int)
    classify_done = Signal(str)
    failed = Signal(str, str, str)
    finished = Signal()
    instances: list = []

    def __init__(self, settings, mode="auto", start_level=None, consented=frozenset(), touched=None, parent=None) -> None:
        super().__init__(parent)
        self.settings, self.mode, self.start_level, self.consented, self.touched = settings, mode, start_level, frozenset(consented), touched
        self.running = False
        self.cancelled = False
        FakeRecommendWorker.instances.append(self)

    def start(self) -> None:
        self.running = True

    def isRunning(self) -> bool:  # noqa: N802
        return self.running

    def cancel(self) -> None:
        self.cancelled = True

    def wait(self, _ms: int = 0) -> bool:
        return True

    def finish(self) -> None:
        self.running = False
        self.finished.emit()

    @classmethod
    def last(cls) -> "FakeRecommendWorker":
        return cls.instances[-1]


@pytest.fixture(autouse=True)
def _fake_recommend_worker(monkeypatch):
    """성장 탭이 열릴 때 카드가 띄우는 RecommendWorker 가 실제 스레드·네트워크를 쓰지 않게 한다. 실제 워커가 필요한 테스트는 직접 되돌린다."""
    from swea_fetcher.gui import recommend_card

    FakeRecommendWorker.instances = []
    monkeypatch.setattr(recommend_card, "RecommendWorker", FakeRecommendWorker)
    yield FakeRecommendWorker


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
