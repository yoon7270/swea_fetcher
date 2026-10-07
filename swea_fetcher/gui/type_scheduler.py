"""배경 풀이 유형 분류 스케줄러 (M24.2): 앱이 열려 있고 한가한 동안 카탈로그의 풀이 유형을 한 묶음씩 분류한다.

- 틱(2분)마다 조건을 보고, 되면 TypeBgWorker 를 **하나** 띄운다. 워커 하나는 한 묶음(5문제)만 분류하고 끝난다 (service.classify_background).
- 한가하다 = 시작한 지 START_DELAY_S 가 지났고, 저장·검증·제출·코치·추천·지문·성장 워커가 하나도 돌지 않는다 (MainWindow.is_busy 가 가리키는 값을 읽기만 한다).
- 켜짐 = 성장 기록·추천·AI 분석이 모두 켜져 있고 "백그라운드 유형 분류"(SWEA_TYPE_BG)가 켜져 있으며 동의한 엔진이 있다 (동의 전에는 아무 것도 하지 않는다).
  설정은 틱마다 다시 읽으므로 토글을 끄면 다음 틱부터 멈춘다 (이미 도는 한 묶음은 끝까지 간다).
- 멈춤 규칙: AI 사용량·요청 한도 오류 / 오늘 AI 호출이 실패해 쉬는 날 / 하루 상한 → 그날은 멈춤. 연속 3번 실패 → 그날은 멈춤.
  시간당 상한 → 다음 정시까지, 네트워크·로그인 문제 → 10분, 엔진 없음·할 일 없음 → 30분 쉼 (재시도·로그인 반복 없음).
  실패한 묶음은 이번 앱 실행 동안 건너뛴다 (같은 문제가 계속 막지 않게).
- Qt 시그널: progress_changed(분류한 수, 전체, 상한 "" | day | hour) / classified() (새 분류가 캐시에 쌓임) / status_changed(마지막 결과 상태).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .. import service
from ..config import Settings
from .workers import TypeBgWorker

TICK_MS = 2 * 60 * 1000  # 틱 간격
START_DELAY_S = 60.0  # 앱을 켠 뒤 이만큼은 건드리지 않는다 (시작 속도·첫 화면 작업 우선)
NETWORK_COOLDOWN = timedelta(minutes=10)
IDLE_COOLDOWN = timedelta(minutes=30)


class TypeScheduler(QObject):
    progress_changed = Signal(int, int, str)
    classified = Signal()
    status_changed = Signal(str)

    def __init__(
        self,
        settings_fn: Callable[[], Settings | None],
        consented_fn: Callable[[], frozenset],
        busy_fn: Callable[[], bool],
        start_level_fn: Callable[[], int | None] = lambda: None,
        *,
        clock: Callable[[], float] = time.monotonic,
        now_fn: Callable[[], datetime] = datetime.now,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings, self._consented, self._busy, self._start_level = settings_fn, consented_fn, busy_fn, start_level_fn
        self._clock, self._now = clock, now_fn
        self._born = clock()
        self._worker: TypeBgWorker | None = None
        self._fails = 0  # 연속 실패 횟수
        self._stop_day = None  # 이 날짜(date)는 더 하지 않는다
        self._until: datetime | None = None  # 이 시각 전에는 쉰다
        self._exclude: set[int] = set()  # 이번 앱 실행에서 실패한 묶음의 문제 번호
        self.last_status = ""
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self.tick)

    # --- 수명 ---
    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def running(self) -> bool:
        return self._worker is not None

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def wait_workers(self, ms: int = 5000) -> None:
        """창 닫기: 먼저 AI 프로세스를 죽이고 스레드가 끝나길 기다린다 (실행 중 QThread 가 파괴되지 않게)."""
        self._timer.stop()
        w = self._worker
        if w is not None and w.isRunning():
            w.cancel()
            w.wait(ms)

    # --- 판단 ---
    def blocker(self) -> str:
        """지금 시작하지 않는 이유 ("" 이면 시작해도 된다): off | consent | running | starting | stopped | cooldown | busy."""
        s = self._settings()
        if s is None or not (s.growth and s.recommend and s.recommend_ai and s.type_bg):
            return "off"
        if not self._consented():
            return "consent"
        if self._worker is not None:
            return "running"
        if self._clock() - self._born < START_DELAY_S:
            return "starting"
        now = self._now()
        if self._stop_day == now.date():
            return "stopped"
        if self._until is not None and now < self._until:
            return "cooldown"
        if self._busy():
            return "busy"
        return ""

    def tick(self) -> bool:
        """틱: 조건이 맞으면 워커 하나를 띄운다. 시작했으면 True. QTimer.timeout 의 인자는 받지 않는다."""
        if self.blocker():
            return False
        s = self._settings()
        w = TypeBgWorker(s, self._consented(), self._start_level(), sorted(self._exclude), self)
        w.finished_ok.connect(self._on_result)
        w.failed.connect(lambda _title, _hint, _detail: self._on_failure(()))
        w.finished.connect(self._cleanup)
        self._worker = w
        w.start()
        return True

    # --- 결과 ---
    def _on_result(self, res) -> None:
        status = str(getattr(res, "status", ""))
        self.last_status = status
        now = self._now()
        done, total = tuple(getattr(res, "progress", (0, 0)) or (0, 0))
        capped = str(getattr(res, "capped", "") or "")
        if status == "ok":
            self._fails = 0
        elif status == "failed":
            self._on_failure(tuple(getattr(res, "attempted", ()) or ()))
        elif status in ("limit", "paused") or (status == "capped" and capped == "day"):
            self._stop_day = now.date()
        elif status == "capped":  # 시간당 상한: 다음 정시까지
            self._until = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        elif status == "network":
            self._until = now + NETWORK_COOLDOWN
        elif status in ("nothing", "no_engine"):
            self._until = now + IDLE_COOLDOWN
        if status == "ok" and capped == "day":
            self._stop_day = now.date()
        if total:
            self.progress_changed.emit(int(done), int(total), capped)
        if getattr(res, "changed", False):
            self.classified.emit()
        self.status_changed.emit(status)

    def _on_failure(self, attempted) -> None:
        self._fails += 1
        self._exclude.update(int(n) for n in attempted)
        if self._fails >= service.CLASSIFY_FAIL_STOP:
            self._stop_day = self._now().date()

    def _cleanup(self) -> None:
        w, self._worker = self._worker, None
        if w is not None:
            w.deleteLater()
