"""검증 페이지 (스펙 §6.2): 주제·번호(또는 .py 드롭) → [실행] → 배지 + diff 뷰 (+ stderr 탭)."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QMessageBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedLayout,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import checker, service, storage
from ...config import Settings
from ...errors import AiError
from ..coach_widgets import CoachBar, CoachTab, ask_consent, has_consent, set_consent
from ..theme import tokens
from ..git_dialog import ask_push
from ..widgets import Badge, Banner, Button, DiffView, EmptyState, make_busy_bar, set_class, set_invalid
from ... import lookup  # noqa: F401  (cached label 은 service 경유)
from ..workers import CheckWorker, CoachWorker, FuncWorker, GitWorker, SubmitWorker

REVERT_HELP_URL = "https://github.com/yoon7270/swea_fetcher/blob/main/docs/troubleshooting.md#자동-푸시를-되돌리려면"

DEFAULT_TIMEOUT = checker.DEFAULT_TIMEOUT


class CheckPage(QWidget):
    busy_changed = Signal(bool, str)
    status_message = Signal(str)
    goto_requested = Signal(str)
    coach_changed = Signal()  # 오답 기록·복습 일정이 바뀜 (제출 직후, 정답 풀이 열람 후) — 메인이 복습 배지를 갱신

    def __init__(self, qsettings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.qs = qsettings
        self.settings: Settings | None = None
        self._worker: CheckWorker | None = None
        self._git_worker: GitWorker | None = None
        self._submit_worker: SubmitWorker | None = None
        self._target_worker: FuncWorker | None = None
        self._pending_submit: tuple[str, int, bool] | None = None
        self._git_auto = False
        self._last_target: tuple[str, int] | None = None  # 마지막으로 검증한 (topic, num) — [커밋 + 푸시] 대상
        self._coach_worker: CoachWorker | None = None
        self._coach_mode: str | None = None  # 코치 바 상태: "pass" | "wrong" | "local" (로컬 검증 실패) | None
        self._coach_judge: tuple[str, str, str | None] = ("", "", None)  # 힌트 프롬프트용 (채점 요약, run_error, 실행 시간)
        self._coach_kind = "review"  # 마지막으로 표시한 응답 종류 ([다시 받기] 대상)
        self._coach_code: dict[str, str] = {}  # 엔진별 마지막 정답 코드 ([코드 복사])
        self._coach_single = False  # 이번 요청의 대상이 엔진 1개 (전체 실패 시 탭을 지우고 배너로 알린다)
        self._coach_only: str | None = None  # 개별 재요청이면 대상 엔진 키
        self._last_coach_request: tuple[str, bool, str | None] | None = None  # (종류, force_new, only)
        self.setAcceptDrops(True)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        m = tokens.SPACE * 3
        root.setContentsMargins(m, m, m, m)
        root.setSpacing(tokens.SPACE * 2)
        head = QHBoxLayout()
        title = QLabel("풀이 검증")
        set_class(title, "title")
        self.badge = Badge()
        self.badge.hide()
        self.mismatch = QLabel()
        set_class(self.mismatch, "muted")
        self.mismatch.hide()
        self.elapsed = QLabel()
        set_class(self.elapsed, "muted")
        self.elapsed.hide()
        self.submit_badge = Badge()  # SWEA 채점 결과 "Pass" / "오답 …" (M8)
        self.submit_badge.hide()
        self.git_badge = Badge()  # "푸시됨 abc1234" / "커밋만" / "변경 없음" / 오류 (M7)
        self.git_badge.hide()
        self.push_btn = Button("커밋 + 푸시")  # 실행 후 항상 표시. 통과면 primary, 실패면 보조 스타일
        self.push_btn.hide()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.badge)
        head.addWidget(self.mismatch)
        head.addWidget(self.elapsed)
        head.addWidget(self.submit_badge)
        head.addWidget(self.git_badge)
        head.addWidget(self.push_btn)
        root.addLayout(head)
        self.busy = make_busy_bar()
        root.addWidget(self.busy)
        self.banner = Banner()
        root.addWidget(self.banner)
        self.coach_bar = CoachBar()  # AI 코치 제안 줄 (M17) — 제출/검증 결과 직후에만
        root.addWidget(self.coach_bar)
        self.coach_tab = CoachTab()

        self.form_card = QFrame()
        set_class(self.form_card, "card")
        grid = QGridLayout(self.form_card)
        grid.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        grid.setHorizontalSpacing(tokens.SPACE)
        grid.setVerticalSpacing(tokens.SPACE)
        self.topic = QComboBox()
        self.topic.setObjectName("TopicCombo")
        self.topic.setEditable(True)
        self.topic.setMinimumWidth(160)
        self.topic.lineEdit().setPlaceholderText("주제")
        self.topic.setAccessibleName("주제 폴더")
        self.num = QLineEdit()
        self.num.setObjectName("NumInput")
        set_class(self.num, "mono")
        self.num.setPlaceholderText("번호")
        self.num.setFixedWidth(100)
        self.num.setAccessibleName("문제 번호")
        self.run_btn = Button("실행")
        set_class(self.run_btn, "primary")
        self.cancel_btn = Button("취소")
        self.cancel_btn.setToolTip("실행 중인 풀이 프로세스를 중단합니다")
        self.cancel_btn.hide()
        self.submit_btn = Button("SWEA 제출")  # M8: 제출 → 채점 → Pass 면 (자동) 커밋+푸시
        self.submit_btn.setToolTip("SWEA 에 제출해 채점받습니다 (제출 횟수 1회 소모). Pass 면 커밋 + 푸시로 이어집니다")
        lt, ln = QLabel("주제"), QLabel("번호")
        set_class(lt, "muted")
        set_class(ln, "muted")
        lt.setBuddy(self.topic)
        ln.setBuddy(self.num)
        grid.addWidget(lt, 0, 0)
        grid.addWidget(self.topic, 0, 1)
        grid.addWidget(ln, 0, 2)
        grid.addWidget(self.num, 0, 3)
        grid.addWidget(self.run_btn, 0, 4)
        grid.addWidget(self.cancel_btn, 0, 5, 1, 1, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self.submit_btn, 0, 6, 1, 1, Qt.AlignmentFlag.AlignLeft)
        grid.setColumnStretch(7, 1)
        self._grid = grid
        self._run_on_row2 = False
        # 입력창이 드롭을 가로채 파일 경로를 텍스트로 넣지 않도록 — 드롭은 페이지(dropEvent)가 처리한다
        for w in (self.topic, self.topic.lineEdit(), self.num, self.run_btn, self.submit_btn):
            w.setAcceptDrops(False)
        self.hint = QLabel(self._hint_text())
        set_class(self.hint, "hint")
        self.hint.setWordWrap(True)  # 720 폭에서 잘리지 않도록
        grid.addWidget(self.hint, 2, 1, 1, 5)
        self.err_label = QLabel()
        set_class(self.err_label, "error")
        self.err_label.hide()
        grid.addWidget(self.err_label, 3, 1, 1, 5)
        root.addWidget(self.form_card)

        holder = QWidget()
        self.stack = QStackedLayout(holder)
        self.empty = EmptyState("실행하면 결과가 여기에 표시됩니다", "최근 페이지에서 문제를 우클릭 → 검증하기 로도 됩니다")
        self.tabs = QTabWidget()
        self.diff = DiffView()
        self.stderr = QPlainTextEdit()
        self.stderr.setReadOnly(True)
        self.stderr.setObjectName("log")
        self.tabs.addTab(self.diff, "출력 비교")
        self.git_log = QPlainTextEdit()  # git 출력 (M7) — 결과가 있을 때만 탭 추가
        self.git_log.setReadOnly(True)
        self.git_log.setObjectName("log")
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.tabs)
        root.addWidget(holder, 1)

        self.run_btn.clicked.connect(self.start)
        self.cancel_btn.clicked.connect(self.cancel)
        self.push_btn.clicked.connect(self.request_push)
        self.submit_btn.clicked.connect(self.request_submit)
        self.num.returnPressed.connect(self.start)
        self.topic.lineEdit().returnPressed.connect(self.start)
        self.banner.action_clicked.connect(self._banner_action)
        self.coach_bar.review_clicked.connect(lambda: self.request_coach("review"))
        self.coach_bar.hint_clicked.connect(lambda: self.request_coach("hint"))
        self.coach_bar.solution_clicked.connect(lambda: self.request_coach("solution"))
        self.coach_bar.later_clicked.connect(self._coach_later)
        self.coach_tab.cancel_clicked.connect(self.cancel_coach)
        self.coach_tab.retry_clicked.connect(lambda key, force_new: self.request_coach(self._coach_kind, force_new=force_new, only=key))
        self.coach_tab.settings_requested.connect(lambda: self.goto_requested.emit("settings"))
        self.coach_tab.copy_clicked.connect(self._copy_coach_code)
        self.num.textEdited.connect(lambda _t: self._clear_invalid())
        self.topic.lineEdit().textEdited.connect(lambda _t: self._clear_invalid())

    # --- 상태 ---------------------------------------------------------------------
    def set_settings(self, settings: Settings | None) -> None:
        self.settings = settings
        self.topic.clear()
        if settings is not None:
            self.topic.addItems(service.list_topics(settings))
            self.topic.setCurrentText(self.qs.value("fetch/last_topic", "", type=str))

    def set_target(self, topic: str, num: int) -> None:
        """최근 목록/드롭에서 호출: 주제·번호 채우기 (실행은 사용자가)."""
        if self.topic.findText(topic) < 0:
            self.topic.addItem(topic)
        self.topic.setCurrentText(topic)
        self.num.setText(str(num))
        self.run_btn.setFocus()

    def timeout(self) -> float:
        return float(self.qs.value("check/timeout", DEFAULT_TIMEOUT, type=float))

    def _hint_text(self) -> str:
        return f"또는 .py 파일이나 {{번호}} 폴더를 이 창에 끌어다 놓으세요 · 타임아웃 {self.timeout():.0f}초 (설정에서 변경)"

    def refresh_hint(self) -> None:
        self.hint.setText(self._hint_text())

    def resizeEvent(self, e) -> None:  # noqa: N802
        """창 너비 < 880 (= 페이지 너비 < 700, 사이드바 148 제외) 이면 [실행] 을 행2 로 내린다 (스펙 §6.2·§11, W2)."""
        super().resizeEvent(e)
        narrow = self.width() < 700
        if narrow != self._run_on_row2:
            self._grid.removeWidget(self.run_btn)
            self._grid.removeWidget(self.cancel_btn)
            self._grid.removeWidget(self.submit_btn)
            if narrow:
                self._grid.addWidget(self.run_btn, 1, 1, 1, 1, Qt.AlignmentFlag.AlignLeft)
                self._grid.addWidget(self.cancel_btn, 1, 2, 1, 2, Qt.AlignmentFlag.AlignLeft)
                self._grid.addWidget(self.submit_btn, 1, 4, 1, 3, Qt.AlignmentFlag.AlignLeft)
            else:
                self._grid.addWidget(self.run_btn, 0, 4)
                self._grid.addWidget(self.cancel_btn, 0, 5, 1, 1, Qt.AlignmentFlag.AlignLeft)
                self._grid.addWidget(self.submit_btn, 0, 6, 1, 1, Qt.AlignmentFlag.AlignLeft)
            self._run_on_row2 = narrow

    def _clear_invalid(self) -> None:
        set_invalid(self.num, False)
        set_invalid(self.topic, False)
        self.err_label.hide()

    # --- 드래그앤드롭 -------------------------------------------------------------
    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            set_class(self.form_card, "card", "drop")
            e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        set_class(self.form_card, "card", "")

    def dropEvent(self, e) -> None:  # noqa: N802
        set_class(self.form_card, "card", "")
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            folder = p if p.is_dir() else p.parent
            if folder.name.isdigit() and folder.parent.name:
                topic = self._topic_for(folder.parent)
                self.set_target(topic, int(folder.name))
                self.banner.hide()
                self.status_message.emit(f"{topic}/{folder.name} 을 선택했습니다 — [실행]을 누르세요")
                return
        names = ", ".join(Path(u.toLocalFile()).name for u in e.mimeData().urls())
        self.banner.show_message("warning", "{주제}\\{번호}\\ 폴더 안의 .py 파일(또는 폴더)을 끌어다 놓으세요", f"놓은 항목: {names}")

    def _topic_for(self, topic_dir: Path) -> str:
        """드롭한 폴더의 주제: 루트 안이면 루트 기준 상대 경로(`test/IM_test`), 밖이면 폴더 이름만."""
        if self.settings is not None:
            try:
                rel = topic_dir.resolve().relative_to(Path(self.settings.root).resolve())
                if rel.parts:
                    return "/".join(rel.parts)
            except (OSError, ValueError):
                pass
        return topic_dir.name

    # --- 실행 -----------------------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        for w in (self.topic, self.num):
            w.setEnabled(not busy)
        self.run_btn.setEnabled(not busy)
        self.submit_btn.setEnabled(not busy and self._submit_worker is None)
        self.cancel_btn.setVisible(busy)
        self.cancel_btn.setEnabled(busy)
        if busy:
            self.setFocus()
        self.run_btn.setText("실행 중…" if busy else "실행")
        self._sync_busy()
        self.busy_changed.emit(busy, "검증 중…" if busy else "")

    def _sync_busy(self) -> None:
        """busy 막대는 실행·제출·AI 워커 중 하나라도 돌고 있으면 표시 (한 워커가 끝나며 다른 워커의 막대를 끄지 않게)."""
        self.busy.setVisible(any(w is not None for w in (self._worker, self._submit_worker, self._coach_worker)))

    def start(self) -> None:
        if self._worker is not None:
            return
        if self.settings is None:
            self.banner.show_message("error", "설정이 없습니다", "루트 폴더·SWEA ID·비밀번호를 먼저 저장하세요", [("settings", "설정으로 이동")])
            return
        topic = self.topic.currentText().strip()
        num_s = self.num.text().strip()
        self._clear_invalid()
        if not topic:
            set_invalid(self.topic, True)
            self.err_label.setText("주제 폴더 이름을 입력하세요")
            self.err_label.show()
            return
        if not num_s.isdigit():
            set_invalid(self.num, True)
            self.err_label.setText("문제 번호를 숫자로 입력하세요")
            self.err_label.show()
            return
        try:
            problem_dir = storage.resolve_problem_dir(self.settings.root, topic, int(num_s))
        except ValueError as e:
            self.banner.show_message("error", str(e))
            return
        if not problem_dir.is_dir() or not (problem_dir / f"{num_s}.py").exists():
            self.banner.show_message("error", f"{num_s}.py 가 없습니다: {problem_dir}", "먼저 저장 페이지에서 문제를 받으세요", [("fetch", "저장 페이지로")])
            return
        self.banner.hide()
        self._hide_coach_bar()
        self.badge.set_state("실행 중…", "running")
        self.mismatch.hide()
        self.elapsed.hide()
        self.push_btn.hide()
        self.git_badge.hide()
        self.submit_badge.hide()
        self._last_target = (topic, int(num_s))
        self._worker = CheckWorker(problem_dir, self.settings, self.timeout(), self)
        self._worker.progress.connect(self.status_message)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._cleanup)
        self._set_busy(True)
        self._worker.start()

    def cancel(self) -> None:
        """[취소]: 실행 중인 풀이 프로세스 kill (M5 #3). 저장 쪽엔 취소가 없다."""
        if self._worker is not None:
            self.cancel_btn.setEnabled(False)
            self.status_message.emit("취소 중…")
            self._worker.cancel()

    def _cleanup(self) -> None:
        self._worker = None
        self._set_busy(False)

    def _on_done(self, res: checker.CheckResult) -> None:
        if res.cancelled:
            self.badge.set_state("취소됨", "idle")
            self.elapsed.hide()
            self.mismatch.hide()
            self.banner.show_message("info", "실행을 취소했습니다", f"{res.elapsed:.1f}초 만에 중단. 다시 [실행]을 누르면 처음부터 실행합니다")
            self.status_message.emit("취소됨")
            return
        self.stack.setCurrentIndex(1)
        first_bad = self.diff.set_rows(res.diff)
        bad = sum(1 for k, _, _ in res.diff if k != "same")
        # stderr 탭: 있을 때만 (AI 코치 탭은 남긴다 — 응답을 잃지 않게)
        for i in range(self.tabs.count() - 1, 0, -1):
            if self.tabs.widget(i) is not self.coach_tab:
                self.tabs.removeTab(i)
        if res.stderr.strip():
            self.stderr.setPlainText(res.stderr)
            self.tabs.addTab(self.stderr, "stderr (오류)")
        self.tabs.setCurrentWidget(self.stderr if (res.stderr.strip() and not res.passed and not res.timed_out) else self.diff)
        self._coach_after_check(res)

        self.elapsed.setText(f"{res.elapsed:.2f}s")
        self.elapsed.show()
        self._show_push_button(res.passed)
        if res.passed:
            self.badge.set_state("통과", "success")
            self.mismatch.hide()
            self.status_message.emit(f"통과 · {res.elapsed:.2f}s")
        elif res.timed_out:
            self.badge.set_state("시간 초과", "error")
            self.banner.show_message("error", f"{self.timeout():.0f}초 안에 끝나지 않아 중단했습니다",
                                     "무한 루프이거나 입력을 읽지 못한 경우입니다. 설정에서 타임아웃을 늘릴 수 있습니다", [("settings", "설정으로 이동")])
        elif not res.expected.strip():
            self.badge.set_state("기대 출력 없음", "warning")
            self.banner.show_message("warning", f"{self.settings.output_name} 가 없습니다 — 뼈대만 받은 문제입니다",
                                     f"문제 페이지의 출력 예시를 {self.settings.output_name} 에 붙여넣으세요")
        else:
            self.badge.set_state("실패", "error")
            self.mismatch.setText(f"불일치 {bad}줄")
            self.mismatch.show()
            if res.note:
                self.banner.show_message("warning", res.note)
            self.status_message.emit(f"실패 · 불일치 {bad}줄")
        _ = first_bad

    def _on_failed(self, title: str, hint: str, detail: str) -> None:
        self.badge.set_state("오류", "error")
        self.banner.show_message("error", title, hint or detail[-400:])

    def _banner_action(self, key: str) -> None:
        if key == "coach-retry":
            if self._last_coach_request is not None:
                self.request_coach(*self._last_coach_request)
            return
        if key == "revert-help":
            QDesktopServices.openUrl(QUrl(REVERT_HELP_URL))
            return
        if key == "push":
            self.request_push()
            return
        self.goto_requested.emit(key)

    # --- SWEA 제출 (M8) ------------------------------------------------------------------
    def _target_from_form(self) -> tuple[str, int] | None:
        topic = self.topic.currentText().strip()
        num_s = self.num.text().strip()
        self._clear_invalid()
        if not topic:
            set_invalid(self.topic, True)
            self.err_label.setText("주제 폴더 이름을 입력하세요")
            self.err_label.show()
            return None
        if not num_s.isdigit():
            set_invalid(self.num, True)
            self.err_label.setText("문제 번호를 숫자로 입력하세요")
            self.err_label.show()
            return None
        return topic, int(num_s)

    def request_submit(self, topic: str | None = None, num: int | None = None) -> None:
        """[SWEA 제출] → 확인(제출 횟수 1회 소모) → SubmitWorker. Pass 면 설정에 따라 자동 커밋+푸시 또는 [커밋 + 푸시] 안내."""
        if self._submit_worker is not None or self._worker is not None or self.settings is None:
            if self.settings is None:
                self.banner.show_message("error", "설정이 없습니다", "루트 폴더·SWEA ID·비밀번호를 먼저 저장하세요", [("settings", "설정으로 이동")])
            return
        if topic is None or num is None:
            t = self._target_from_form()
            if t is None:
                return
            topic, num = t
        else:
            self.set_target(topic, num)
        try:
            problem_dir = storage.resolve_problem_dir(self.settings.root, topic, num)
        except ValueError as e:
            self.banner.show_message("error", str(e))
            return
        if not (problem_dir / f"{num}.py").is_file():
            self.banner.show_message("error", f"{num}.py 가 없습니다: {problem_dir}", "먼저 저장 페이지에서 문제를 받으세요", [("fetch", "저장 페이지로")])
            return
        auto = bool(self.settings.auto_push_on_pass)
        self._pending_submit = (topic, num, auto)
        self._show_submit_confirm()

    def _show_submit_confirm(self) -> None:
        """제출 확인창 (B1): 제출 대상 맥락 표시 + [다시 찾기]. [다시 찾기] 는 클럽 상자를 다시 훑어 라벨 갱신."""
        if self._pending_submit is None or self.settings is None:
            return
        topic, num, auto = self._pending_submit
        label = service.cached_submit_label(self.settings, num) or "확인 필요 — [다시 찾기] 를 누르세요"
        body = f"{topic}/{num}/{num}.py 를 SWEA 에 제출합니다.\n제출 대상: {label}\n제출 가능 횟수가 1회 감소합니다."
        body += "\n\nPass 면 확인 없이 커밋 + 푸시합니다 (설정에서 켜져 있음)." if auto else "\n\nPass 면 [커밋 + 푸시] 버튼이 활성화됩니다."
        box = QMessageBox(QMessageBox.Icon.Question, "SWEA 제출", body, parent=self)
        ok = box.addButton("제출", QMessageBox.ButtonRole.AcceptRole)
        refresh = box.addButton("다시 찾기", QMessageBox.ButtonRole.ActionRole)
        cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(ok)
        box.setEscapeButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is refresh:
            self._refresh_submit_target()
            return
        if clicked is not ok:
            self._pending_submit = None
            return
        self._pending_submit = None
        self._last_target = (topic, num)
        self._git_auto = auto
        self.banner.hide()
        self._hide_coach_bar()
        self.submit_badge.set_state("제출 중…", "running")
        self.git_badge.hide()
        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("채점 중…")
        self.busy.show()
        self.busy_changed.emit(True, "SWEA 채점 중…")
        self._submit_worker = SubmitWorker(self.settings, topic, num, auto, self)
        self._submit_worker.progress.connect(self.status_message)
        self._submit_worker.finished_ok.connect(self._on_submit_done)
        self._submit_worker.failed.connect(self._on_submit_failed)
        self._submit_worker.finished.connect(self._submit_cleanup)
        self._submit_worker.start()

    def _refresh_submit_target(self) -> None:
        """[다시 찾기]: 클럽 상자를 다시 훑어(find_category refresh) 라벨 갱신 후 확인창 재표시."""
        if self._pending_submit is None or self.settings is None or self._target_worker is not None:
            return
        _topic, num, _auto = self._pending_submit
        self.status_message.emit("제출 대상 다시 찾는 중…")
        self._target_worker = FuncWorker(lambda: service.resolve_submit_target(self.settings, num, refresh=True), self)
        self._target_worker.finished_ok.connect(lambda _t: self._show_submit_confirm())
        self._target_worker.failed.connect(lambda t, h, d: self.banner.show_message("error", f"대상 확인 실패: {t}", h))
        self._target_worker.finished.connect(self._target_cleanup)
        self._target_worker.start()

    def _target_cleanup(self) -> None:
        self._target_worker = None

    def _submit_cleanup(self) -> None:
        self._submit_worker = None
        self.submit_btn.setEnabled(self._worker is None)
        self.submit_btn.setText("SWEA 제출")
        self._sync_busy()
        self.busy_changed.emit(False, "")

    def _on_submit_done(self, outcome) -> None:
        res = outcome.submit
        for n in outcome.notes:
            self.status_message.emit(n)
        cat = f" · categoryType={outcome.category_type} · categoryId={outcome.category_id}" if outcome.category_type else ""
        self._show_git_log(f"[SWEA 제출 응답] contestProbId={outcome.contest_prob_id}{cat}\n" + json.dumps(res.raw, ensure_ascii=False, indent=1))
        if res.passed:
            self.submit_badge.set_state("Pass", "success")
            self._show_push_button(True)
            if outcome.git is not None:
                self._on_git_done(outcome.git)
                self.banner.show_message("success", f"SWEA Pass → 커밋 + 푸시했습니다 ({outcome.git.commit_hash})",
                                         outcome.git.note, [("revert-help", "되돌리기 안내")])
            else:
                self.banner.show_message("success", "SWEA 채점 결과: Pass",
                                         "이 풀이를 GitHub 에 올리려면 [커밋 + 푸시] 를 누르세요", [("push", "커밋 + 푸시")])
            self.status_message.emit("SWEA Pass")
        else:
            self.submit_badge.set_state("오답", "error")
            self._show_push_button(False)
            body = res.summary + (f"\n\n{res.run_error}" if res.run_error else "")
            self.banner.show_message("error", "SWEA 채점 결과: 오답 — 푸시하지 않았습니다", body)
            self.status_message.emit(res.summary)
        self._coach_after_submit(res)

    def _on_submit_failed(self, title: str, hint: str, detail: str) -> None:
        self.submit_badge.set_state("제출 실패", "error")
        self.banner.show_message("error", title, hint or detail[-400:])

    # --- 커밋 + 푸시 (M7) ----------------------------------------------------------------
    def _show_push_button(self, passed: bool) -> None:
        """실행 후 항상 표시. 통과면 주 버튼, 실패면 보조 스타일 + 툴팁."""
        set_class(self.push_btn, "primary" if passed else "")
        self.push_btn.setToolTip("" if passed else "실패한 풀이도 커밋할 수 있습니다")
        self.push_btn.setEnabled(True)
        self.push_btn.show()

    def request_push(self, topic: str | None = None, num: int | None = None) -> None:
        """[커밋 + 푸시] → 확인 다이얼로그(매번) → GitWorker. 최근 페이지 메뉴에서도 호출된다."""
        if self._git_worker is not None or self.settings is None:
            return
        if topic is None or num is None:
            if self._last_target is None:
                return
            topic, num = self._last_target
        self._last_target = (topic, num)
        try:
            choice = ask_push(self, self.settings, topic, num)
        except ValueError as e:
            self.banner.show_message("error", str(e))
            return
        if choice is None:
            return
        if isinstance(choice, list):
            self.banner.show_message("error", "커밋할 수 없습니다", "\n".join(choice))
            return
        message, push = choice
        self._start_git(message, push=push, auto=False)

    def _start_git(self, message: str | None, push: bool, auto: bool) -> None:
        if self._git_worker is not None or self.settings is None or self._last_target is None:
            return
        topic, num = self._last_target
        self._git_auto = auto
        self.push_btn.setEnabled(False)
        self.git_badge.set_state("git 실행 중…", "running")
        self._git_worker = GitWorker(self.settings, topic, num, message, push, self)
        self._git_worker.progress.connect(self.status_message)
        self._git_worker.finished_ok.connect(self._on_git_done)
        self._git_worker.failed.connect(self._on_git_failed)
        self._git_worker.finished.connect(self._git_cleanup)
        self._git_worker.start()

    def _git_cleanup(self) -> None:
        self._git_worker = None
        self.push_btn.setEnabled(True)

    def wait_workers(self, ms: int = 5000) -> None:
        if self._coach_worker is not None and self._coach_worker.isRunning():
            self._coach_worker.cancel()  # 최대 5분을 기다리지 않고 프로세스 트리를 먼저 종료
        for w in (self._coach_worker, self._git_worker, self._worker, self._submit_worker, self._target_worker):
            if w is not None and w.isRunning():
                w.wait(ms)

    def _show_git_log(self, text: str) -> None:
        self.git_log.setPlainText(text)
        if self.tabs.indexOf(self.git_log) < 0:
            self.tabs.addTab(self.git_log, "git / 제출 응답")

    def _on_git_done(self, result) -> None:
        self._show_git_log(result.output)
        if result.pushed:
            label = f"{'자동 ' if self._git_auto else ''}푸시됨 {result.commit_hash}"
            self.git_badge.set_state(label, "success")
            if self._git_auto:
                self.banner.show_message("info", f"검증 통과 → 자동으로 커밋 + 푸시했습니다 ({result.commit_hash})",
                                         "샘플 통과가 정답을 뜻하진 않습니다. 잘못 올렸다면 되돌리기 안내를 보세요",
                                         [("revert-help", "되돌리기 안내"), ("settings", "자동 푸시 설정")])
        elif result.committed:
            self.git_badge.set_state(f"커밋만 {result.commit_hash}", "success")
        else:
            self.git_badge.set_state("변경 없음", "idle")
        self.status_message.emit(result.note)

    def _on_git_failed(self, title: str, hint: str, detail: str) -> None:
        self.git_badge.set_state("git 오류", "error")
        if hint and hint.startswith("$ git"):
            self._show_git_log(hint)
            hint = ""
        self.banner.show_message("error", title, hint or detail[-400:], [("settings", "GitHub 연동 설정")])

    # --- AI 코치 (M17) --------------------------------------------------------------------
    def _hide_coach_bar(self) -> None:
        self._coach_mode = None
        self.coach_bar.hide()

    def _coach_after_submit(self, res) -> None:
        """SWEA 채점 결과 뒤: 코치 바 (Pass = 코드 평가, 오답 = 힌트 [+ 정답 풀이]). 오답 기록은 service 가 이미 저장했다."""
        self._coach_judge = (res.summary, res.run_error, res.execution_time)
        self._coach_mode = "pass" if res.passed else "wrong"
        self._refresh_coach_bar()
        self.coach_changed.emit()

    def _coach_after_check(self, res: checker.CheckResult) -> None:
        """로컬 검증 실패 뒤에도 [힌트] (B). 횟수에는 넣지 않는다. 통과·기대 출력 없음이면 바를 숨긴다."""
        if res.passed or not res.expected.strip():
            self._hide_coach_bar()
            return
        if res.timed_out:
            summary, err = "제한시간 초과 (로컬 실행)", ""
        elif res.returncode not in (0, None) and res.stderr.strip():
            summary, err = "로컬 실행 중 런타임 에러", res.stderr.strip().splitlines()[-1][:255]
        else:
            bad = sum(1 for k, _, _ in res.diff if k != "same")
            summary, err = f"로컬 검증 실패: 샘플 출력과 {bad}줄 불일치", ""
        self._coach_judge = (summary, err, None)
        self._coach_mode = "local"
        self._refresh_coach_bar()

    def _refresh_coach_bar(self) -> None:
        """기록(records.json)·힌트 진행을 다시 읽어 코치 바를 갱신한다 (파일 2개, UI 스레드 허용)."""
        if self._coach_mode is None or self.settings is None or self._last_target is None:
            self.coach_bar.hide()
            return
        if self._coach_mode == "pass":
            self.coach_bar.show_pass()
        else:
            topic, num = self._last_target
            rec = service.get_coach_record(self.settings, num)
            self.coach_bar.show_wrong(
                rec.wrong_count if rec else 0,
                self.settings.ai_wrong_threshold,
                self.settings.review_days,
                rec.offer_dismissed if rec else False,
                service.hint_level(self.settings, topic, num),
                local=self._coach_mode == "local",
                solution_viewed=bool(rec and rec.solution_viewed_at),
            )
        try:  # 대상 엔진이 2개(둘 다 모드)면 "각각 1번씩 요청" 고지 (경로 확인뿐이라 UI 스레드 허용)
            sel = service.resolve_engines(self.settings)
            self.coach_bar.set_dual([e.short_label for e in sel.engines] if len(sel.engines) >= 2 else None)
        except AiError:
            self.coach_bar.set_dual(None)
        self.coach_bar.set_requesting(self._coach_worker is not None)

    def _coach_later(self) -> None:
        if self.settings is not None and self._last_target is not None:
            service.dismiss_offer(self.settings, self._last_target[1])
        self._refresh_coach_bar()

    def request_coach(self, kind: str, force_new: bool = False, only: str | None = None) -> None:
        """코치 버튼 → 엔진 확인 → (첫 사용이면) 동의 1회 → CoachWorker. 클릭 없이는 어떤 AI 프로세스도 뜨지 않는다.

        only: 개별 [다시 받기]/[다시 시도] — 그 엔진만 재요청하고 다른 패널은 유지한다 (M18).
        """
        if self._coach_worker is not None or self.settings is None or self._last_target is None:
            return
        topic, num = self._last_target
        try:
            sel = service.resolve_engines(self.settings)
        except AiError as e:
            self._show_ai_error(e.code, str(e), e.hint)
            return
        engines = [e for e in sel.engines if only in (None, e.name)]
        missing = [k for k in sel.missing if only in (None, k)]
        if not engines and not missing:
            return
        need = [e for e in engines if not has_consent(self.qs, e.name)]  # 미동의 엔진을 한 다이얼로그에 모은다
        if need:
            if not ask_consent(self, [e.label for e in need], dual=len(engines) >= 2):
                return
            for e in need:
                set_consent(self.qs, e.name)
        self._last_coach_request = (kind, force_new, only)
        self._coach_only = only
        self._coach_single = only is None and len(sel.engines) + len(sel.missing) == 1
        if only is None:
            self._coach_code = {}
        else:
            self._coach_code.pop(only, None)
        summary, run_error, exec_time = self._coach_judge
        self.banner.hide()
        self._coach_kind = kind
        extra = {"engines": [only]} if only else {}
        self._coach_worker = CoachWorker(
            self.settings, kind, topic, num, self,
            submit_summary=summary, run_error=run_error, execution_time=exec_time, force_new=force_new, **extra,
        )
        w = self._coach_worker
        w.progress.connect(self.status_message)
        w.engine_done.connect(self._on_coach_engine_done)
        w.finished_ok.connect(self._on_coach_done)
        w.ai_failed.connect(self._on_coach_ai_failed)
        w.failed.connect(self._on_coach_failed)
        w.finished.connect(self._coach_cleanup)
        self.coach_bar.set_requesting(True)
        if self.tabs.indexOf(self.coach_tab) < 0:
            self.tabs.addTab(self.coach_tab, "AI 코치")
        self.tabs.setCurrentWidget(self.coach_tab)
        self.stack.setCurrentIndex(1)  # 제출만 하고 로컬 실행이 없으면 결과 영역이 빈 상태에 머무르므로
        self.coach_tab.begin(engines, missing, only, kind, num)
        self.coach_tab.set_busy(True)
        self._sync_busy()
        self.busy_changed.emit(True, "AI 코치 응답 대기 중…")
        w.start()

    def cancel_coach(self) -> None:
        if self._coach_worker is not None:
            self.coach_tab.cancel_btn.setEnabled(False)
            self.status_message.emit("AI 요청 취소 중…")
            self._coach_worker.cancel()

    def _coach_cleanup(self) -> None:
        self._coach_worker = None
        self.coach_tab.stop()
        self.coach_tab.set_busy(False)
        self.coach_bar.set_requesting(False)
        self._sync_busy()
        self.busy_changed.emit(False, "")

    def _remove_coach_tab(self) -> None:
        idx = self.tabs.indexOf(self.coach_tab)
        if idx >= 0:
            self.tabs.removeTab(idx)

    def _on_coach_engine_done(self, outcome) -> None:
        """엔진 하나의 결과 (먼저 끝난 쪽부터). 해당 패널만 채운다."""
        num = self._last_target[1] if self._last_target else 0
        if outcome.answer is not None:
            self._coach_code[outcome.engine] = outcome.answer.code
        self.coach_tab.apply_outcome(outcome, num)

    def _on_coach_done(self, result) -> None:
        if result is None or result.cancelled:
            if result is not None and self.coach_tab.has_answers():
                self.coach_tab.cancel_loading()  # 이미 표시된 답은 유지, 로딩 중이던 패널만 "취소했습니다"
            else:
                self._remove_coach_tab()
            self.banner.show_message("info", "요청을 취소했습니다", "AI 에게 보낸 요청을 중단했습니다")
            self.status_message.emit("AI 요청 취소됨")
            return
        if result.all_failed:
            if self._coach_single:  # 단일 대상은 기존처럼 탭을 지우고 배너로
                f = result.outcomes[0].failure
                self._remove_coach_tab()
                self._show_ai_error(f.code, f.title, f.hint)
                return
            if self._coach_only is None:  # 둘 다 실패: 패널마다 인라인 오류는 유지하고 요약 배너만
                actions = [("coach-retry", "다시 시도")]
                self.banner.show_message("error", "두 엔진 모두 응답하지 못했습니다", "각 패널의 오류 내용을 확인하세요", actions)
            self.status_message.emit("AI 코치 응답 실패")
            return
        self.tabs.setCurrentWidget(self.coach_tab)
        self.coach_tab.show_growth_tip(getattr(result, "growth_tip", None))  # 성장 팁 (M19): 같은 약점 3번 연속일 때만
        if result.kind == "hint":
            self.coach_bar.set_hint_done(result.hint_done)
        elif result.kind == "solution":
            self.coach_tab.show_review_due(result.review_due)
            self.coach_changed.emit()  # 복습 예약 → 메인이 복습 배지 갱신
            self._refresh_coach_bar()
        self.status_message.emit(self._coach_flash(result))

    @staticmethod
    def _coach_flash(result) -> str:
        """상태바 문구: 단일은 "AI 코치 응답 (엔진, 캐시)", 둘 다는 엔진별 소요 시간/실패."""
        if len(result.outcomes) == 1:
            a = result.outcomes[0].answer
            return f"AI 코치 응답 ({a.engine}{', 캐시' if a.from_cache else ''})"
        parts = []
        for o in result.outcomes:
            if o.answer is not None:
                parts.append(f"{o.label} " + ("캐시" if o.answer.from_cache else f"{o.answer.elapsed:.1f}초"))
            else:
                parts.append(f"{o.label} 실패")
        return "AI 코치 응답 — " + " · ".join(parts)

    def _on_coach_ai_failed(self, code: str, title: str, hint: str) -> None:
        self._coach_request_failed(code, title, hint)
        self._show_ai_error(code, title, hint)

    def _on_coach_failed(self, title: str, hint: str, detail: str) -> None:
        self._coach_request_failed("failed", title, hint or detail[-400:])
        self.banner.show_message("error", title, hint or detail[-400:])

    def _coach_request_failed(self, code: str, title: str, hint: str) -> None:
        """요청 전체가 시작하지 못함. 개별 재요청이고 다른 답이 있으면 탭을 지우지 않고 그 패널에 인라인 오류를 남긴다."""
        if self._coach_only is not None and self.coach_tab.has_answers():
            self.coach_tab.fail_loading(service.CoachFailure(code, title, hint))
        else:
            self._remove_coach_tab()

    def _show_ai_error(self, code: str, title: str, hint: str) -> None:
        """AiError → 배너 (design-spec §9): 엔진 없음 = warning + [설정으로 이동], 그 외 = error + [다시 시도]."""
        if code == "missing":
            self.banner.show_message("warning", "AI 엔진을 찾지 못했습니다", hint or title, [("settings", "설정으로 이동")])
        else:
            actions = [("coach-retry", "다시 시도")] if self._last_coach_request is not None else None
            self.banner.show_message("error", title, hint, actions)

    def _copy_coach_code(self, key: str) -> None:
        code = self._coach_code.get(key, "")
        if code:
            QGuiApplication.clipboard().setText(code)
            self.status_message.emit("정답 코드를 복사했습니다 (파일로는 저장되지 않습니다)")
