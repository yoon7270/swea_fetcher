"""QThread 워커. 네트워크·파일·subprocess 는 전부 여기서 돈다 (UI 스레드 금지).

시그널: progress(str) / finished(object) / failed(str title, str hint, str detail)
detail 은 traceback 문자열 — 로그 영역에만 표시하고 배너에는 쓰지 않는다.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

from .. import ai_engine, checker, config, service
from ..config import Settings
from ..errors import AiError, SweaFetchError
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
        return service.check_problem(self.settings, self.problem_dir, self.timeout, on_start=self._on_start)


class GitWorker(BaseWorker):
    """문제 폴더 커밋(+푸시) (M7). 결과는 gitops.GitResult, 전제 조건 미충족·git 실패는 GitError → failed."""

    def __init__(self, settings: Settings, topic: str, num: int, message: str | None, push: bool, parent=None) -> None:
        super().__init__(parent)
        self.settings, self.topic, self.num, self.message, self.push = settings, topic, num, message, push

    def work(self):
        return service.push_problem(self.settings, self.topic, self.num, message=self.message, push=self.push, progress=self.progress.emit)


class SubmitWorker(BaseWorker):
    """SWEA 제출 → 채점 결과 (M8). push=True 면 Pass 일 때 커밋+푸시까지 (service.submit_problem)."""

    def __init__(self, settings: Settings, topic: str, num: int, push: bool, parent=None) -> None:
        super().__init__(parent)
        self.settings, self.topic, self.num, self.push = settings, topic, num, push

    def work(self):
        return service.submit_problem(self.settings, self.topic, self.num, push=self.push, progress=self.progress.emit)


class GrowthWorker(BaseWorker):
    """성장 기록 주간 리포트 확정 + 주간 AI 코멘트 1건 (M19). 결과는 service.GrowthRunResult (finished_ok).

    취소 가능 (CoachWorker 와 같은 방식: 프로세스 트리 종료, 아직 안 떴으면 뜨는 즉시). 코치 요청과 병행해도 된다.
    consented: UI 스레드에서 미리 읽은 "동의받은 엔진 키" 집합 (QSettings 를 워커 스레드에서 읽지 않는다).
    시그널: stats_ready(list[date]) 새 주 확정 / comment_started(date) / comment_ready(date) / blocked(str) / failed(title, hint, detail).
    """

    stats_ready = Signal(object)
    comment_started = Signal(object)
    comment_ready = Signal(object)
    blocked = Signal(str)

    def __init__(self, settings: Settings, consented: frozenset | set, force_week=None, parent=None) -> None:
        super().__init__(parent)
        self.settings, self.consented, self.force_week = settings, frozenset(consented), force_week
        self._proc = None
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        proc = self._proc
        if proc is not None:
            ai_engine.kill_tree(proc)

    def _on_start(self, proc) -> None:
        self._proc = proc
        if self._cancel_requested:
            ai_engine.kill_tree(proc)

    def work(self) -> service.GrowthRunResult:
        res = service.generate_growth(
            self.settings, consent_ok=lambda key: key in self.consented, on_start=self._on_start, on_begin=self.comment_started.emit,
            is_cancelled=lambda: self._cancel_requested, on_stats=self.stats_ready.emit,
            on_comment=lambda week, _text: self.comment_ready.emit(week), force_week=self.force_week,
        )
        if res.blocked:
            self.blocked.emit(res.blocked)
        if res.failure is not None:
            self.failed.emit(res.failure.title, res.failure.hint, "")
        return res


class RecommendWorker(BaseWorker):
    """오늘의 추천 (M24): 카탈로그 갱신 · 수준·세트 계산 · AI 선별. 파일·네트워크·AI 는 전부 여기서 (UI 스레드 금지).

    mode: "auto"(성장 탭이 처음 보일 때·날짜가 바뀐 뒤: 카탈로그 확인 → 규칙 세트 → AI → 오래된 카탈로그 조용히 갱신) /
          "rules"(규칙 세트만 다시 읽기: 시작 수준 변경·해결 배지 갱신) / "rebuild"(규칙 세트를 읽되 배경 분류로 새로 알게 된 유형을 반영) /
          "shuffle"([다른 추천]) / "retry_ai"(동의·[다시 시도] 뒤 AI 만) /
          "refresh_catalog"(수동 [새로 받기]/[다시 시도]).
    consented: UI 스레드에서 미리 읽은 "동의받은 엔진 키" 집합 (QSettings 를 워커 스레드에서 읽지 않는다). touched: 사용자가 이미 만졌는지 (R11).
    풀이 유형 분류 (M24.1): 세트를 만들기 전에 (오늘 세트가 없을 때) 또는 세트를 보여 준 뒤 (있을 때) AI 로 유형을 분류해 캐시에 쌓는다.
    새 유형이 알려져 세트에 유형 미확인 칸이 있고 사용자가 아직 안 만졌으면 세트를 다시 만들어 rule_ready 를 한 번 더 보낸다.
    시그널: rule_ready(RecommendResult) / ai_started(list[str] 엔진 키) / ai_ready(RecommendResult) / catalog_progress(done, total) /
            catalog_updated(CatalogStatus) / catalog_failed(code, hint, usable) / notice("logged_out") /
            classify_started() / classify_progress(done) / classify_done(status) / 상속 failed(title, hint, detail).
    cancel(): 플래그 + 등록된 AI 프로세스 트리 종료 (both 의 두 프로세스 모두). 카탈로그 갱신은 페이지 사이에서 멈춘다.
    """

    rule_ready = Signal(object)
    ai_started = Signal(object)
    ai_ready = Signal(object)
    catalog_progress = Signal(int, int)
    catalog_updated = Signal(object)
    catalog_failed = Signal(str, str, bool)  # code, hint, 저장된 카탈로그를 쓸 수 있는가
    notice = Signal(str)
    classify_started = Signal()
    classify_progress = Signal(int)
    classify_done = Signal(str)  # ClassifyResult.status

    def __init__(self, settings: Settings, mode: str = "auto", start_level: int | None = None, consented: frozenset | set = frozenset(),
                 touched: Callable[[], bool] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.settings, self.mode, self.start_level = settings, mode, start_level
        self.consented = frozenset(consented)
        self.touched = touched
        self._procs: list[Any] = []
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        for proc in list(self._procs):
            ai_engine.kill_tree(proc)

    def _on_start(self, proc) -> None:
        self._procs.append(proc)
        if self._cancel_requested:
            ai_engine.kill_tree(proc)

    def _cancelled(self) -> bool:
        return self._cancel_requested

    def _refresh(self, force: bool) -> bool:
        """카탈로그를 (필요하면) 받는다. 실패는 catalog_failed 로 알리고 False. 새로 받았으면 catalog_updated."""
        prev = service.catalog_status(self.settings)
        try:
            st = service.refresh_catalog(self.settings, progress=self.catalog_progress.emit, is_cancelled=self._cancelled, force=force)
        except service.CatalogError as e:
            self.catalog_failed.emit(e.code, e.hint, prev.usable)
            return False
        if st.fetched_at != prev.fetched_at:
            self.catalog_updated.emit(st)
        if not st.usable:
            self.catalog_failed.emit("blocked", "", False)
            return False
        return True

    def _rules(self, shuffle: bool = False, rebuild: bool = False) -> Any:
        res = service.recommend_today(self.settings, start_level=self.start_level, shuffle=shuffle, rebuild=rebuild)
        self.rule_ready.emit(res)
        return res

    def _classify(self, retry: bool = False) -> Any:
        """풀이 유형 분류 (동의·엔진·상한은 service 가 판단). 하는 일이 없으면 신호도 없다."""
        if not self.settings.recommend_ai or self._cancel_requested:
            return None
        res = service.classify_types(
            self.settings, consent_ok=lambda key: key in self.consented, start_level=self.start_level, on_start=self._on_start,
            on_begin=lambda _engine: self.classify_started.emit(), on_progress=self.classify_progress.emit, is_cancelled=self._cancelled, retry=retry,
        )
        self.classify_done.emit(res.status)
        return res

    def _ai(self, base: Any, retry: bool = False) -> None:
        if not self.settings.recommend_ai or self._cancel_requested:
            return
        res = service.recommend_ai(
            self.settings, base, consent_ok=lambda key: key in self.consented, on_start=self._on_start,
            on_begin=self.ai_started.emit, is_cancelled=self._cancelled, is_touched=self.touched, retry=retry,
        )
        self.ai_ready.emit(res)

    def work(self) -> None:
        s = self.settings
        if not service.recommend_enabled(s):
            return None
        if self.mode == "refresh_catalog":  # 수동 [새로 받기]/[다시 시도]: 받은 뒤 이어서 정답 목록·규칙·AI
            if self._refresh(force=True):
                self._tail()
            return None
        if self.mode == "rules":
            self._rules()
            return None
        if self.mode == "shuffle":
            self._rules(shuffle=True)
            return None
        if self.mode == "rebuild":  # 배경 분류로 새로 알게 된 유형을 반영 (사용자가 아직 안 만졌을 때만 세트를 다시 만든다)
            self._rules(rebuild=not self._is_touched())
            return None
        if self.mode == "retry_ai":
            cls = self._classify(retry=True)
            self._ai(self._rules(rebuild=bool(cls and cls.changed and not self._is_touched())), retry=True)
            return None
        # auto
        usable = service.catalog_status(s).usable
        if not usable and not self._refresh(force=False):
            return None
        self._tail()
        if usable and not self._cancel_requested:  # 있던 카탈로그가 오래됐으면 마지막에 조용히 갱신
            st = service.catalog_status(s)
            if st.stale and st.auto_due and self._refresh(force=False):
                self._rules()
        return None

    def _tail(self) -> None:
        """카탈로그가 준비된 뒤: SWEA 정답 목록(필요할 때) → 규칙 세트 → AI."""
        if service.refresh_passed(self.settings, is_cancelled=self._cancelled) < 0:
            self.notice.emit("logged_out")
        has_set = service.has_day_set(self.settings)
        base = self._rules() if has_set else None  # 오늘 세트가 있으면 바로 보여 주고, 유형 분류는 그 뒤에
        cls = self._classify()
        changed = bool(cls is not None and cls.changed)
        if base is None or changed:  # 세트가 없었으면 분류 뒤에 만든다 / 있었으면 새로 알게 된 유형으로 미확인 칸이 있을 때만 다시 만든다
            base = self._rules(rebuild=has_set and changed and not self._is_touched())
        self._ai(base)

    def _is_touched(self) -> bool:
        return bool(self.touched is not None and self.touched())


class TypeBgWorker(BaseWorker):
    """배경 풀이 유형 분류 **한 묶음** (M24.2). 결과는 service.ClassifyResult (finished_ok). 파일·네트워크·AI 는 전부 여기서.

    consented: UI 스레드에서 미리 읽은 "동의받은 엔진 키" 집합. exclude: 이번 앱 실행에서 건너뛸 문제 번호 (실패한 묶음).
    cancel(): 플래그 + AI 프로세스 트리 종료 (앱을 닫을 때 최대 몇 분을 기다리지 않게).
    """

    def __init__(self, settings: Settings, consented: frozenset | set = frozenset(), start_level: int | None = None, exclude=(), parent=None) -> None:
        super().__init__(parent)
        self.settings, self.start_level = settings, start_level
        self.consented = frozenset(consented)
        self.exclude = tuple(exclude)
        self._procs: list[Any] = []
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        for proc in list(self._procs):
            ai_engine.kill_tree(proc)

    def _on_start(self, proc) -> None:
        self._procs.append(proc)
        if self._cancel_requested:
            ai_engine.kill_tree(proc)

    def work(self) -> service.ClassifyResult:
        return service.classify_background(
            self.settings, consent_ok=lambda key: key in self.consented, start_level=self.start_level, exclude=self.exclude,
            on_start=self._on_start, is_cancelled=lambda: self._cancel_requested,
        )


class FuncWorker(BaseWorker):
    """임의 함수를 워커에서 실행 (list_recent 등 파일 I/O)."""

    def __init__(self, fn: Callable[[], Any], parent=None) -> None:
        super().__init__(parent)
        self.fn = fn

    def work(self) -> Any:
        return self.fn()


class CoachWorker(BaseWorker):
    """AI 코치 요청 1건 (M17, 둘 다 모드는 M18). 결과는 service.CoachResult.

    취소 가능: 등록된 모든 엔진 프로세스 트리를 종료하고, 아직 안 뜬 엔진은 뜨는 즉시 종료한다.
    engine_done(EngineOutcome): 엔진 하나의 결과가 확정될 때마다 (먼저 끝난 답부터 점진 표시용). 워커 스레드에서 emit → queued.
    AiError(엔진이 하나도 없음 등 요청 자체가 시작 못 함)는 ai_failed(code, title, hint) 로 나뉘어 나온다 — 페이지가 배너 종류를 고른다.
    호출 전 사용자 동의는 페이지 책임 (이 워커는 곧바로 service.ask_coach_multi 를 부른다).
    """

    ai_failed = Signal(str, str, str)  # code, title, hint
    engine_done = Signal(object)  # service.EngineOutcome

    def __init__(self, settings: Settings, kind: str, topic: str = "", num: int = 0, parent=None, **kwargs) -> None:
        super().__init__(parent)
        self.settings, self.kind, self.topic, self.num, self.kwargs = settings, kind, topic, num, kwargs
        self._procs: dict[str, Any] = {}
        self._cancel_requested = False

    def cancel(self) -> None:
        """진행 중 프로세스를 전부 죽인다. 아직 안 떴으면 뜨는 즉시(on_start) 죽인다."""
        self._cancel_requested = True
        for proc in list(self._procs.values()):
            ai_engine.kill_tree(proc)

    def _on_start(self, key: str, proc) -> None:
        self._procs[key] = proc
        if self._cancel_requested:
            ai_engine.kill_tree(proc)

    def work(self) -> service.CoachResult:
        return service.ask_coach_multi(
            self.settings, self.kind, self.topic, self.num, progress=self.progress.emit,
            on_start=self._on_start, on_engine_done=self.engine_done.emit,
            is_cancelled=lambda: self._cancel_requested, **self.kwargs,
        )

    def run(self) -> None:  # QThread 진입점
        try:
            result = self.work()
        except AiError as e:
            self.ai_failed.emit(e.code, str(e), e.hint)
        except SweaFetchError as e:
            self.failed.emit(str(e), e.hint, "")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"내부 오류: {type(e).__name__}: {e}", "다시 시도하거나 로그를 확인하세요", traceback.format_exc())
        else:
            self.finished_ok.emit(result)
