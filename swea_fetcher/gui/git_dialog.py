"""[커밋 + 푸시] 확인 다이얼로그 (M7 §3).

매번 확인한다 — "다시 묻지 않음" 은 일부러 두지 않는다 (실수 푸시 방지). 자동 모드(설정)는 이 다이얼로그를 거치지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .. import gitops, service, storage
from ..config import Settings
from .widgets import set_class


class PushDialog(QDialog):
    """커밋 메시지(편집 가능) · 대상 폴더 · 브랜치 → 원격 표시. 결과: self.choice = None | (message, push)."""

    def __init__(self, repo: gitops.RepoInfo, problem_dir: Path, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("커밋 + 푸시")
        self.setModal(True)
        self.choice: tuple[str, bool] | None = None
        self.repo = repo

        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.message = QLineEdit(message)
        self.message.setMinimumWidth(420)
        self.message.setAccessibleName("커밋 메시지")
        self.message.selectAll()
        try:
            rel = problem_dir.resolve().relative_to(repo.toplevel).as_posix()
        except ValueError:
            rel = str(problem_dir)
        folder = QLabel(rel)
        set_class(folder, "mono")
        target = QLabel(self._target_text(repo))
        set_class(target, "mono")
        target.setToolTip(repo.remote or "원격 없음")
        form.addRow("커밋 메시지", self.message)
        form.addRow("대상 폴더", folder)
        form.addRow("브랜치 → 원격", target)
        lay.addLayout(form)
        note = QLabel("문제 폴더만 커밋합니다. 다른 변경은 건드리지 않고, force push 는 하지 않습니다.")
        set_class(note, "hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        if repo.dirty_outside:
            warn = QLabel("루트에 이 문제 폴더 밖의 변경이 있습니다 — 그 변경은 포함되지 않습니다.")
            set_class(warn, "muted")
            warn.setWordWrap(True)
            lay.addWidget(warn)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.cancel_btn = QPushButton("취소")
        self.commit_btn = QPushButton("커밋만")
        self.push_btn = QPushButton("커밋 + 푸시")
        set_class(self.push_btn, "primary")
        self.push_btn.setEnabled(bool(repo.remote))
        if not repo.remote:
            self.push_btn.setToolTip("원격 저장소(origin)가 없어 푸시할 수 없습니다")
        for b in (self.cancel_btn, self.commit_btn, self.push_btn):
            btns.addWidget(b)
        lay.addLayout(btns)
        self.cancel_btn.clicked.connect(self.reject)
        self.commit_btn.clicked.connect(lambda: self._accept(False))
        self.push_btn.clicked.connect(lambda: self._accept(True))
        self.push_btn.setDefault(bool(repo.remote))
        self.message.returnPressed.connect(lambda: self._accept(bool(repo.remote)))
        self.message.setFocus()

    @staticmethod
    def _target_text(repo: gitops.RepoInfo) -> str:
        branch = repo.branch or "(detached HEAD)"
        if repo.upstream:
            return f"{branch} → {repo.upstream}"
        if repo.remote:
            return f"{branch} → origin/{branch} (첫 푸시: -u 로 upstream 설정)"
        return f"{branch} (원격 없음)"

    def _accept(self, push: bool) -> None:
        msg = self.message.text().strip()
        if not msg:
            self.message.setFocus()
            return
        self.choice = (msg, push)
        self.accept()


def ask_push(parent: QWidget | None, settings: Settings, topic: str, num: int) -> tuple[str, bool] | None | list[str]:
    """다이얼로그를 띄워 (message, push) 를 받는다. 취소면 None, 전제 조건 미충족이면 사유 목록(list[str])."""
    problem_dir = storage.resolve_problem_dir(settings.root, topic, num)
    if gitops.git_available() is None:
        return ["git 이 설치되어 있지 않습니다 — https://git-scm.com 에서 설치하세요"]
    repo = gitops.find_repo(settings.root, problem_dir)
    reasons = gitops.preflight(repo, problem_dir, push=False)
    if reasons or repo is None:
        return reasons or ["루트 폴더가 git 저장소가 아닙니다 — README 'GitHub 연동' 절 참고"]
    message = service.commit_message_for(settings, topic, num, problem_dir)
    dlg = PushDialog(repo, problem_dir, message, parent)
    dlg.exec()
    return dlg.choice
