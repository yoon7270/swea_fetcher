"""변경 감지 자동 동기화 (M11 §4). GUI 가 켜져 있는 동안에만 동작 (백그라운드 서비스 아님).

파일시스템 감시 대신 `git status --porcelain` 폴링:
- QTimer 로 POLL_SEC 마다 워커에서 git status 해시를 읽는다
- 변경이 감지되면 "마지막 변경 시각" 을 기록하고, 조용한 시간(DEBOUNCE_SEC) 이 지나면 sync_now(reason="watch")
- 다른 워커(저장·검증·제출) 실행 중이면 그 틱은 건너뛴다
- 같은 사유로 반복 실패하면 일시 중지하고 상태바에 안내 — 알림 도배 방지

순수 로직(_decide)은 시계·상태를 인자로 받아 테스트 가능하게 분리한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from .. import gitops, service
from ..config import Settings

POLL_SEC = 30.0
DEBOUNCE_SEC = 90.0
RETRY_AFTER_SEC = 60.0  # 일시 중지 후 재시도 간격


@dataclass
class _State:
    last_hash: str | None = None
    last_change_at: float | None = None  # 변경 감지 시각 (동기화되면 None)
    paused_note: str = ""  # 반복 실패로 일시 중지된 사유 (비어 있으면 정상)
    paused_at: float | None = None
    last_pushed_at: float | None = None


def status_hash(repo: gitops.RepoInfo) -> str:
    """git status --porcelain 결과의 해시 (변경 여부·내용 비교용). 빈 문자열이면 깨끗함."""
    from .. import gitops as _g

    out = _g._ok(["status", "--porcelain", "--untracked-files=all"], repo.toplevel)
    return out or ""


def _decide(state: _State, now: float, current_hash: str, busy: bool) -> str | None:
    """다음 행동 결정 (순수 함수). 반환: None(대기) / "sync"(동기화 실행).

    - 해시가 바뀌면 last_change_at 갱신
    - 변경이 있고(해시 비어있지 않음) DEBOUNCE 경과 & busy 아님 → "sync"
    - 일시 중지 중이면 RETRY_AFTER 경과 전엔 None
    """
    if current_hash != state.last_hash:
        state.last_hash = current_hash
        state.last_change_at = now if current_hash else None
    if not current_hash:
        return None  # 깨끗함
    if state.paused_note:
        if state.paused_at is not None and now - state.paused_at < RETRY_AFTER_SEC:
            return None
    if busy:
        return None
    if state.last_change_at is not None and now - state.last_change_at >= DEBOUNCE_SEC:
        return "sync"
    return None


class AutoSyncController(QObject):
    """QTimer 폴링 + 워커 실행. main_window 가 소유한다."""

    status_changed = Signal(str)  # 상태바 텍스트
    synced = Signal(object)  # GitResult (로그 표시용)

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.state = _State()
        self._worker = None
        self._timer = QTimer(self)
        self._timer.setInterval(int(POLL_SEC * 1000))
        self._timer.timeout.connect(self._tick)
        self._active = False

    # --- 설정 반영 ---------------------------------------------------------------------
    def configure(self, settings: Settings | None) -> None:
        active = bool(settings and settings.auto_push and "watch" in settings.auto_push_on)
        self._active = active
        if active:
            self.state.paused_note = ""
            self.state.paused_at = None
            if not self._timer.isActive():
                self._timer.start()
            self._emit_status(settings)
        else:
            self._timer.stop()
            self.status_changed.emit("")

    def resume(self) -> None:
        """[다시 시작]: 일시 중지 해제."""
        self.state.paused_note = ""
        self.state.paused_at = None
        self._emit_status(self.window.settings)

    # --- 폴링 ------------------------------------------------------------------------
    def _busy(self) -> bool:
        cp = getattr(self.window, "check_page", None)
        fp = getattr(self.window, "fetch_page", None)
        for w in (getattr(cp, "_worker", None), getattr(cp, "_submit_worker", None), getattr(cp, "_git_worker", None),
                  getattr(fp, "_worker", None), self._worker):
            if w is not None and w.isRunning():
                return True
        return False

    def _tick(self) -> None:
        if not self._active or self._worker is not None:
            return
        settings = getattr(self.window, "settings", None)
        if settings is None:
            return
        repo = gitops.find_repo(settings.root)
        if repo is None or not repo.remote:
            return
        now = time.monotonic()
        try:
            current = status_hash(repo)
        except Exception:  # noqa: BLE001
            return
        action = _decide(self.state, now, current, self._busy())
        if action == "sync":
            self._run_sync(settings)
        else:
            self._emit_status(settings)

    def _run_sync(self, settings: Settings) -> None:
        from .workers import FuncWorker

        self._worker = FuncWorker(lambda: service.sync_now(settings, reason="watch"), self)
        self._worker.finished_ok.connect(self._on_sync)
        self._worker.failed.connect(lambda t, h, d: self._on_sync_error(t))
        self._worker.finished.connect(self._sync_cleanup)
        self._worker.start()

    def _sync_cleanup(self) -> None:
        self._worker = None

    def _on_sync(self, result) -> None:
        settings = getattr(self.window, "settings", None)
        if result is None:
            self.state.last_change_at = None
            return
        if result.failed:
            # 같은 사유 반복이면 일시 중지
            self.state.paused_note = result.note
            self.state.paused_at = time.monotonic()
        else:
            self.state.last_change_at = None
            self.state.last_hash = ""
            if result.pushed or result.committed:
                self.state.last_pushed_at = time.monotonic()
            self.synced.emit(result)
        self._emit_status(settings)

    def _on_sync_error(self, title: str) -> None:
        self.state.paused_note = title
        self.state.paused_at = time.monotonic()
        self._emit_status(getattr(self.window, "settings", None))

    # --- 상태바 ------------------------------------------------------------------------
    def _emit_status(self, settings: Settings | None) -> None:
        if not self._active or settings is None:
            self.status_changed.emit("")
            return
        scope = "루트 전체" if settings.auto_push_scope == "root" else "문제 폴더"
        if self.state.paused_note:
            self.status_changed.emit(f"⚠ 자동 동기화 일시 중지: {self.state.paused_note}")
        else:
            self.status_changed.emit(f"⟳ 자동 동기화: 켜짐 ({scope} · 변경 감지)")

    # --- 종료 시 1회 --------------------------------------------------------------------
    def sync_on_close(self, timeout: float = 30.0) -> None:
        """앱 종료 직전 변경이 남아 있으면 1회 동기화 시도 (블로킹, 실패해도 반환)."""
        settings = getattr(self.window, "settings", None)
        if not (settings and settings.auto_push and "watch" in settings.auto_push_on):
            return
        repo = gitops.find_repo(settings.root)
        if repo is None or not repo.remote:
            return
        try:
            if not status_hash(repo):
                return
            service.sync_now(settings, reason="watch")
        except Exception:  # noqa: BLE001
            pass
