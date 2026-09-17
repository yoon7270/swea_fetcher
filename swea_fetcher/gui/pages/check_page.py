"""검증 페이지 (스펙 §6.2): 주제·번호(또는 .py 드롭) → [실행] → 배지 + diff 뷰 (+ stderr 탭)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
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
from ..theme import tokens
from ..git_dialog import ask_push
from ..widgets import Badge, Banner, DiffView, EmptyState, make_busy_bar, set_class, set_invalid
from ..workers import CheckWorker, GitWorker

REVERT_HELP_URL = "https://github.com/yoon7270/swea_fetcher/blob/main/docs/troubleshooting.md#자동-푸시를-되돌리려면"

DEFAULT_TIMEOUT = checker.DEFAULT_TIMEOUT


class CheckPage(QWidget):
    busy_changed = Signal(bool, str)
    status_message = Signal(str)
    goto_requested = Signal(str)

    def __init__(self, qsettings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.qs = qsettings
        self.settings: Settings | None = None
        self._worker: CheckWorker | None = None
        self._git_worker: GitWorker | None = None
        self._git_auto = False
        self._last_target: tuple[str, int] | None = None  # 마지막으로 검증한 (topic, num) — [커밋 + 푸시] 대상
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
        self.git_badge = Badge()  # "푸시됨 abc1234" / "커밋만" / "변경 없음" / 오류 (M7)
        self.git_badge.hide()
        self.push_btn = QPushButton("커밋 + 푸시")  # 실행 후 항상 표시. 통과면 primary, 실패면 보조 스타일
        self.push_btn.hide()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.badge)
        head.addWidget(self.mismatch)
        head.addWidget(self.elapsed)
        head.addWidget(self.git_badge)
        head.addWidget(self.push_btn)
        root.addLayout(head)
        self.busy = make_busy_bar()
        root.addWidget(self.busy)
        self.banner = Banner()
        root.addWidget(self.banner)

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
        self.run_btn = QPushButton("실행")
        set_class(self.run_btn, "primary")
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setToolTip("실행 중인 풀이 프로세스를 중단합니다")
        self.cancel_btn.hide()
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
        grid.setColumnStretch(6, 1)
        self._grid = grid
        self._run_on_row2 = False
        # 입력창이 드롭을 가로채 파일 경로를 텍스트로 넣지 않도록 — 드롭은 페이지(dropEvent)가 처리한다
        for w in (self.topic, self.topic.lineEdit(), self.num, self.run_btn):
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
        self.empty = EmptyState("실행하면 결과가 여기에 표시됩니다", "최근 페이지에서 문제를 더블클릭해도 됩니다")
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
        self.num.returnPressed.connect(self.start)
        self.topic.lineEdit().returnPressed.connect(self.start)
        self.banner.action_clicked.connect(self._banner_action)
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
            if narrow:
                self._grid.addWidget(self.run_btn, 1, 1, 1, 1, Qt.AlignmentFlag.AlignLeft)
                self._grid.addWidget(self.cancel_btn, 1, 2, 1, 2, Qt.AlignmentFlag.AlignLeft)
            else:
                self._grid.addWidget(self.run_btn, 0, 4)
                self._grid.addWidget(self.cancel_btn, 0, 5, 1, 1, Qt.AlignmentFlag.AlignLeft)
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
        self.cancel_btn.setVisible(busy)
        self.cancel_btn.setEnabled(busy)
        if busy:
            self.setFocus()
        self.run_btn.setText("실행 중…" if busy else "실행")
        self.busy.setVisible(busy)
        self.busy_changed.emit(busy, "검증 중…" if busy else "")

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
        self.badge.set_state("실행 중…", "running")
        self.mismatch.hide()
        self.elapsed.hide()
        self.push_btn.hide()
        self.git_badge.hide()
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
        # stderr 탭: 있을 때만
        while self.tabs.count() > 1:
            self.tabs.removeTab(1)
        if res.stderr.strip():
            self.stderr.setPlainText(res.stderr)
            self.tabs.addTab(self.stderr, "stderr (오류)")
        self.tabs.setCurrentIndex(1 if (res.stderr.strip() and not res.passed and not res.timed_out) else 0)

        self.elapsed.setText(f"{res.elapsed:.2f}s")
        self.elapsed.show()
        self._show_push_button(res.passed)
        if res.passed:
            self.badge.set_state("통과", "success")
            self.mismatch.hide()
            self.status_message.emit(f"통과 · {res.elapsed:.2f}s")
            if self.settings is not None and self.settings.auto_push_on_pass:
                self._start_git(None, push=True, auto=True)
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
        if key == "revert-help":
            QDesktopServices.openUrl(QUrl(REVERT_HELP_URL))
            return
        self.goto_requested.emit(key)

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
        for w in (self._git_worker, self._worker):
            if w is not None and w.isRunning():
                w.wait(ms)

    def _show_git_log(self, text: str) -> None:
        self.git_log.setPlainText(text)
        if self.tabs.indexOf(self.git_log) < 0:
            self.tabs.addTab(self.git_log, "git")

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
