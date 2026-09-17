"""QThread 워커. 네트워크·파일·subprocess 는 전부 여기서 돈다 (UI 스레드 금지).

시그널: progress(str) / finished(object) / failed(str title, str hint, str detail)
detail 은 traceback 문자열 — 로그 영역에만 표시하고 배너에는 쓰지 않는다.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

from .. import checker, config, service
from ..config import Settings
from ..errors import SweaFetchError
from ..service import FetchOptions


class BaseWorker(QThread):
    progress = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str, str, str)  # title, hint, detail

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    def work(self) -> Any:  # 하위 클래스가 구현
        raise NotImplementedError

    def run(self) -> None:  # QThread 진입점
        try:
            result = self.work()
        except SweaFetchError as e:
            self.failed.emit(str(e), e.hint, "")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"내부 오류: {type(e).__name__}: {e}", "다시 시도하거나 로그를 확인하세요", traceback.format_exc())
        else:
            self.finished_ok.emit(result)


class FetchWorker(BaseWorker):
    def __init__(self, settings: Settings, target: str, topic: str, opts: FetchOptions, parent=None) -> None:
        super().__init__(parent)
        self.settings, self.target, self.topic, self.opts = settings, target, topic, opts

    def work(self) -> service.FetchOutcome:
        return service.fetch_problem(self.settings, self.target, self.topic, self.opts, self.progress.emit)


class LoginWorker(BaseWorker):
    """설정 저장(.env + keyring) 후 로그인 확인. 비밀번호는 생성자 인자로만 받고 저장 직후 버린다."""

    def __init__(self, config_dir: Path, root: Path, user_id: str, password: str | None, parent=None) -> None:
        super().__init__(parent)
        self.config_dir, self.root, self.user_id = Path(config_dir), Path(root), user_id
        self._password = password

    def work(self) -> str:
        self.progress.emit("설정 저장")
        if self._password:
            config.save_password(self.user_id, self._password)
        self._password = None
        service.write_env(self.config_dir, self.root, self.user_id)
        config.strip_password_from_env_file(self.config_dir)
        settings = config.load_settings(self.config_dir)
        return service.verify_login(settings, self.progress.emit)


class CheckWorker(BaseWorker):
    def __init__(self, problem_dir: Path, settings: Settings, timeout: float, parent=None) -> None:
        super().__init__(parent)
        self.problem_dir, self.settings, self.timeout = Path(problem_dir), settings, timeout
        self._proc = None
        self._cancel_requested = False

    def cancel(self) -> None:
        """풀이 프로세스를 죽인다 (M5 #3). 아직 안 떴으면 뜨는 즉시 죽인다."""
        self._cancel_requested = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc._swea_cancelled = True  # checker 가 결과를 '취소됨' 으로 표시
            proc.kill()

    def _on_start(self, proc) -> None:
        self._proc = proc
        if self._cancel_requested:
            proc._swea_cancelled = True
            proc.kill()

    def work(self) -> checker.CheckResult:
        self.progress.emit(f"실행 중: {self.problem_dir.name}.py (제한 {self.timeout:.0f}초)")
        return checker.run_and_compare(self.problem_dir, self.settings, self.timeout, on_start=self._on_start)


class FuncWorker(BaseWorker):
    """임의 함수를 워커에서 실행 (list_recent 등 파일 I/O)."""

    def __init__(self, fn: Callable[[], Any], parent=None) -> None:
        super().__init__(parent)
        self.fn = fn

    def work(self) -> Any:
        return self.fn()
