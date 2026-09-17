"""저장 페이지 (스펙 §6.1): 번호·주제·옵션 → [저장]/[미리보기] → 결과 카드 + 로그."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import service
from ...config import Settings
from ...service import FetchOptions, FetchOutcome
from ..theme import tokens
from ..widgets import Badge, Banner, ElidedLabel, LogView, make_busy_bar, open_in_explorer, open_with_default_app, set_class, set_invalid, svg_icon
from ..workers import FetchWorker


class FetchPage(QWidget):
    busy_changed = Signal(bool, str)  # (busy, 창 제목 접미)
    saved = Signal(object)  # FetchOutcome — 최근 목록 갱신용
    status_message = Signal(str)
    goto_requested = Signal(str)  # 페이지 key

    def __init__(self, qsettings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.qs = qsettings
        self.settings: Settings | None = None
        self._worker: FetchWorker | None = None
        self._last_outcome: FetchOutcome | None = None
        self._last_args: tuple[str, str, FetchOptions] | None = None
        self._build()

    # --- UI -----------------------------------------------------------------------
    def _build(self) -> None:
        # 내용이 창보다 길어지면(결과 카드 + 로그) 겹치지 않고 스크롤되도록 QScrollArea 안에 둔다 (스펙 §11)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("page")
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        root = QVBoxLayout(inner)
        m = tokens.SPACE * 3
        root.setContentsMargins(m, m, m, m)
        root.setSpacing(tokens.SPACE * 2)

        head = QHBoxLayout()
        title = QLabel("문제 저장")
        set_class(title, "title")
        keys = QLabel("Enter 저장 · Ctrl+Enter 미리보기 · Esc 로그 지우기")
        set_class(keys, "hint")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(keys)
        root.addLayout(head)
        self.busy = make_busy_bar()
        root.addWidget(self.busy)
        self.banner = Banner()
        root.addWidget(self.banner)

        card = QFrame()
        set_class(card, "card")
        form = QGridLayout(card)
        form.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        form.setHorizontalSpacing(tokens.SPACE * 2)
        form.setVerticalSpacing(tokens.SPACE)
        form.setColumnMinimumWidth(0, 72)
        self.target = QLineEdit()
        self.target.setObjectName("TargetInput")
        set_class(self.target, "mono")
        self.target.setPlaceholderText("25730  또는 문제 URL / contestProbId")
        self.target.setAccessibleName("문제 번호")
        self.topic = QComboBox()
        self.topic.setObjectName("TopicCombo")
        self.topic.setEditable(True)
        self.topic.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.topic.setMinimumWidth(240)
        self.topic.lineEdit().setPlaceholderText("BFS, test/IM_test …")
        self.topic.setAccessibleName("주제 폴더")
        topic_hint = QLabel("루트 아래 폴더 이름 (test/IM_test 처럼 중첩 가능)")
        set_class(topic_hint, "hint")
        l1, l2 = QLabel("문제 번호"), QLabel("주제")
        for lab, w in ((l1, self.target), (l2, self.topic)):
            lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            set_class(lab, "muted")
            lab.setBuddy(w)
        form.addWidget(l1, 0, 0)
        form.addWidget(self.target, 0, 1, 1, 2)
        form.addWidget(l2, 1, 0)
        form.addWidget(self.topic, 1, 1)
        form.addWidget(topic_hint, 1, 2)
        self.err_label = QLabel()
        set_class(self.err_label, "error")
        self.err_label.hide()
        form.addWidget(self.err_label, 2, 1, 1, 2)
        opts = QHBoxLayout()
        opts.setSpacing(tokens.SPACE * 2)
        self.force = QCheckBox("덮어쓰기")
        self.force.setToolTip("input.txt / output.txt 를 덮어씁니다. {번호}.py 는 유지")
        self.skeleton = QCheckBox("뼈대만")
        self.skeleton.setToolTip("첨부를 받지 않고 폴더 + {번호}.py + 빈 input.txt 만 만듭니다")
        self.refresh = QCheckBox("색인 새로고침")
        self.refresh.setToolTip("번호 색인 캐시를 무시하고 다시 찾습니다")
        for w in (self.force, self.skeleton, self.refresh):
            opts.addWidget(w)
        opts.addStretch(1)
        form.addLayout(opts, 3, 1, 1, 2)
        btns = QHBoxLayout()
        self.run_btn = QPushButton("저장")
        set_class(self.run_btn, "primary")
        self.run_btn.setDefault(True)
        self.preview_btn = QPushButton("미리보기")
        btns.addWidget(self.run_btn)
        btns.addWidget(self.preview_btn)
        btns.addStretch(1)
        form.addLayout(btns, 4, 1, 1, 2)
        form.setColumnStretch(2, 1)
        root.addWidget(card)

        # 결과 카드 (§5.10)
        self.card = QFrame()
        self.card.setObjectName("ResultCard")
        set_class(self.card, "card")
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        cl.setSpacing(tokens.SPACE)
        th = QHBoxLayout()
        self.card_icon = QLabel()
        self.card_icon.setFixedSize(16, 16)
        self.card_badge = Badge("미리보기", "idle")
        self.card_badge.hide()
        self.card_title = QLabel()
        set_class(self.card_title, "section")
        th.addWidget(self.card_icon)
        th.addWidget(self.card_badge)
        th.addWidget(self.card_title, 1)
        cl.addLayout(th)
        self.card_path = ElidedLabel()  # 긴 경로 가운데 생략, 가로 스크롤 방지 (W6)
        set_class(self.card_path, "mono")
        cl.addWidget(self.card_path)
        self.card_files = _FileRows()
        cl.addWidget(self.card_files)
        self.card_note = QLabel()
        set_class(self.card_note, "muted")
        self.card_note.setWordWrap(True)
        self.card_note.hide()
        cl.addWidget(self.card_note)
        cb = QHBoxLayout()
        self.open_dir_btn = QPushButton("폴더 열기")
        self.open_py_btn = QPushButton("PyCharm 에서 열기")
        self.commit_btn = QPushButton("이대로 저장")
        set_class(self.commit_btn, "primary")
        self.commit_btn.setFixedHeight(tokens.CONTROL_H_SM)
        cb.addWidget(self.open_dir_btn)
        cb.addWidget(self.open_py_btn)
        cb.addWidget(self.commit_btn)
        cb.addStretch(1)
        cl.addLayout(cb)
        self.card.hide()
        root.addWidget(self.card)

        self.log = LogView(self.qs, "fetch/log_expanded")
        root.addWidget(self.log, 1)

        # 동작
        self.run_btn.clicked.connect(lambda: self.start(dry_run=False))
        self.preview_btn.clicked.connect(lambda: self.start(dry_run=True))
        self.target.returnPressed.connect(lambda: self.start(dry_run=False))
        self.topic.lineEdit().returnPressed.connect(lambda: self.start(dry_run=False))
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=lambda: self.start(dry_run=True))
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=lambda: self.start(dry_run=True))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._esc)
        self.open_dir_btn.clicked.connect(self._open_dir)
        self.open_py_btn.clicked.connect(self._open_py)
        self.commit_btn.clicked.connect(self._commit_preview)
        self.banner.action_clicked.connect(self._banner_action)
        self.target.textEdited.connect(lambda _t: self._clear_invalid())
        self.topic.lineEdit().textEdited.connect(lambda _t: self._clear_invalid())

    # --- 상태 -----------------------------------------------------------------------
    def set_settings(self, settings: Settings | None) -> None:
        self.settings = settings
        self.topic.clear()
        if settings is not None:
            self.topic.addItems(service.list_topics(settings))
            last = self.qs.value("fetch/last_topic", "", type=str)
            self.topic.setCurrentText(last)
        self.target.setFocus()

    def _set_busy(self, busy: bool) -> None:
        for w in (self.preview_btn, self.target, self.topic, self.force, self.skeleton, self.refresh):
            w.setEnabled(not busy)
        self.run_btn.setEnabled(not busy)
        if busy:
            self.setFocus()
        self.run_btn.setText("저장 중…" if busy and self._last_args and not self._last_args[2].dry_run else "저장")
        self.busy.setVisible(busy)
        self.busy_changed.emit(busy, "저장 중…" if busy else "")

    def _clear_invalid(self) -> None:
        set_invalid(self.target, False)
        set_invalid(self.topic, False)
        self.err_label.hide()

    def _esc(self) -> None:
        if self.banner.isVisible():  # 배너는 포커스를 받지 않으므로 표시 여부로 판단 (§10)
            self.banner.hide()
        else:
            self.log.clear()
            self.status_message.emit("로그를 지웠습니다")

    # --- 실행 -----------------------------------------------------------------------
    def start(self, dry_run: bool, opts_override: FetchOptions | None = None) -> None:
        if self._worker is not None:
            return
        if self.settings is None:
            self.banner.show_message("error", "설정이 없습니다", "루트 폴더·SWEA ID·비밀번호를 먼저 저장하세요", [("settings", "설정으로 이동")])
            return
        target = self.target.text().strip()
        topic = self.topic.currentText().strip()
        self._clear_invalid()
        if not target:
            set_invalid(self.target, True)
            self.err_label.setText("문제 번호 또는 URL 을 입력하세요")
            self.err_label.show()
            self.target.setFocus()
            return
        if not topic:
            set_invalid(self.topic, True)
            self.err_label.setText("주제 폴더 이름을 입력하세요")
            self.err_label.show()
            self.topic.setFocus()
            return
        opts = opts_override or FetchOptions(
            force=self.force.isChecked(),
            skeleton_only=self.skeleton.isChecked(),
            dry_run=dry_run,
            refresh_index=self.refresh.isChecked(),
        )
        self._last_args = (target, topic, opts)
        self.banner.hide()
        self.card.hide()
        self.log.append(f"{'미리보기' if opts.dry_run else '저장'} 시작: {target} → {topic}")
        self._worker = FetchWorker(self.settings, target, topic, opts, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._cleanup)
        self._set_busy(True)
        self._worker.start()

    def _on_progress(self, msg: str) -> None:
        self.log.append(msg)
        self.status_message.emit(msg)

    def _cleanup(self) -> None:
        self._worker = None
        self._set_busy(False)
        self.target.setFocus()

    def _rerun(self, **changes) -> None:
        """배너 조치 버튼: 옵션을 바꿔 같은 입력으로 재실행. 체크박스도 함께 바꾼다 (스펙 §9)."""
        if not self._last_args:
            return
        target, topic, opts = self._last_args
        new = FetchOptions(**{**opts.__dict__, **changes})
        self.force.setChecked(new.force)
        self.skeleton.setChecked(new.skeleton_only)
        self.refresh.setChecked(new.refresh_index)
        self.target.setText(target)
        self.topic.setCurrentText(topic)
        self.start(dry_run=new.dry_run, opts_override=new)

    def _banner_action(self, key: str) -> None:
        if key == "force":
            self._rerun(force=True, dry_run=False)
        elif key == "skeleton":
            self._rerun(skeleton_only=True, dry_run=False)
        elif key == "refresh":
            self._rerun(refresh_index=True)
        elif key == "retry":
            self._rerun()
        elif key == "settings":
            self.goto_requested.emit("settings")
        elif key == "log":
            self.log.toggle.setChecked(True)
            self.log.text.verticalScrollBar().setValue(self.log.text.verticalScrollBar().maximum())

    def _commit_preview(self) -> None:
        if self._last_args:
            _t, _p, opts = self._last_args
            needs_force = bool(self._last_outcome and self._last_outcome.preview and self._last_outcome.preview.get("needs_force"))
            self._rerun(dry_run=False, force=opts.force or needs_force)

    # --- 결과 -----------------------------------------------------------------------
    def _on_done(self, outcome: FetchOutcome) -> None:
        self._last_outcome = outcome
        self.qs.setValue("fetch/last_topic", outcome.topic)
        if self.topic.findText(outcome.topic) < 0:
            self.topic.addItem(outcome.topic)
        self.topic.setCurrentText(outcome.topic)
        info, s = outcome.info, self.settings
        p = tokens.LIGHT
        if outcome.notices:
            self.banner.show_message("warning", " · ".join(outcome.notices))
        if outcome.result is not None:
            r = outcome.result
            written, skipped = set(r.written), set(r.skipped)
            self.card_icon.setPixmap(svg_icon("status-success", None, 16).pixmap(16, 16))
            self.card_icon.show()
            self.card_badge.hide()
            self.card_title.setText(f"{info.num}. {info.title}")
            self.card_path.setText(str(r.problem_dir) + "\\")
            self.card_path.setToolTip(str(r.problem_dir))
            skel = self._last_args is not None and self._last_args[2].skeleton_only
            plan = [(s.input_name, info.input_filename), (f"{info.num}.py", None)] if skel else [
                (s.input_name, info.input_filename), (s.output_name, info.output_filename), (f"{info.num}.py", None)]
            rows = []
            for name, src in plan:
                path = r.problem_dir / name
                if path in written:
                    if name.endswith(".py"):
                        desc = _ui("뼈대 생성")
                    elif skel:
                        desc = _ui("빈 파일")
                    else:
                        desc = f"{_fmt_size(path)}, {_ui('원본')} {_esc(src)}"
                    badge = _badge_html("생성", p.surface_alt, p.text_2)
                elif path in skipped:
                    desc = _ui("기존 파일 유지")
                    badge = _badge_html("유지", p.surface_alt, p.text_2)
                else:
                    continue
                rows.append((f"{_pad(name)} ({desc}) {badge}", None))
            self.card_files.set_rows(rows)
            self.card_note.setVisible(skel)
            self.card_note.setText(f"샘플은 문제 페이지에서 직접 {s.input_name} 에 붙여넣으세요")
            self.open_dir_btn.show()
            self.open_py_btn.show()
            self.commit_btn.hide()
            self.card.show()
            self.status_message.emit(f"저장 완료 · {info.num}")
            self.saved.emit(outcome)
        else:
            pv = outcome.preview or {}
            self.card_icon.hide()
            self.card_badge.set_state("미리보기", "idle")
            self.card_title.setText(f"{info.num}. {info.title}")
            self.card_path.setText(f"{pv.get('problem_dir')}\\")
            labels = {"create": ("생성 예정", p.surface_alt, p.text_2), "create_empty": ("빈 파일 생성 예정", p.surface_alt, p.text_2),
                      "keep": ("유지", p.surface_alt, p.text_2), "overwrite": ("덮어씀", p.warning_bg, p.warning_text),
                      "conflict": ("이미 있음", p.warning_bg, p.warning_text)}
            rows = []
            for fp in pv.get("files", []):
                text, bg, fg = labels.get(fp.action, (fp.action, p.surface_alt, p.text_2))
                src = f"← {_esc(fp.source)} ({fp.size} B)" if fp.source else ""
                rows.append((f"{_pad(fp.name)} {src} {_badge_html(text, bg, fg)}".replace("  ", " "), fp.preview or None))
            self.card_files.set_rows(rows)
            self.card_note.hide()
            self.open_dir_btn.hide()
            self.open_py_btn.hide()
            self.commit_btn.setText("덮어쓰고 저장" if pv.get("needs_force") else "이대로 저장")
            self.commit_btn.show()
            self.card.show()
            self.status_message.emit("미리보기 — 저장하지 않았습니다")

    def _on_failed(self, title: str, hint: str, detail: str) -> None:
        self.card.hide()
        self.log.append(f"오류: {title}", error=True)
        if detail:
            self.log.append(detail, error=True)
        state, actions = "error", []
        if "이미 저장된 파일" in title:
            state, title, actions = "warning", "이미 저장된 문제입니다", [("force", "덮어쓰고 다시 저장")]
        elif "첨부 링크가 없습니다" in title:
            state, title, actions = "warning", "샘플 첨부가 없는 문제입니다", [("skeleton", "뼈대만 저장")]
        elif "찾지 못했습니다" in title and "문제 번호" in title:
            actions = [("refresh", "색인 새로고침 후 재시도")]
            self.target.setFocus()
        elif "설정이 없습니다" in title or "로그인" in title and "실패" in title:
            actions = [("settings", "설정으로 이동")]
        elif "네트워크" in title:
            actions = [("retry", "다시 시도")]
        elif title.startswith("내부 오류"):
            actions = [("log", "로그 보기")]
        elif "contestProbId" in title or "입력" in title:
            self.target.setFocus()
        self.banner.show_message(state, title, hint, actions)

    def _open_dir(self) -> None:
        if self._last_outcome and self._last_outcome.result:
            if open_in_explorer(self._last_outcome.result.problem_dir):
                self.status_message.emit("폴더를 열었습니다")

    def _open_py(self) -> None:
        oc = self._last_outcome
        if oc and oc.result:
            py = oc.result.problem_dir / f"{oc.info.num}.py"
            if py.exists() and open_with_default_app(py):
                self.status_message.emit(f"{py.name} 을 열었습니다")


class _FileRows(QWidget):
    """파일 행 목록: 한 줄 QLabel(rich text) + 선택적 미리보기 QLabel. (QLabel 은 <table>/<div> 높이 계산이 틀려 행마다 따로 둔다)"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(2)

    def set_rows(self, rows: list[tuple[str, str | None]]) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for html, preview in rows:
            lab = QLabel(html)
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            set_class(lab, "mono")
            self._lay.addWidget(lab)
            if preview:
                pv = QLabel(preview)
                pv.setObjectName("preview")
                pv.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                set_class(pv, "mono")
                pv.setContentsMargins(tokens.SPACE, 3, tokens.SPACE, 3)
                self._lay.addWidget(pv)

    def text(self) -> str:  # 테스트 호환
        return "\n".join(self._lay.itemAt(i).widget().text() for i in range(self._lay.count()) if self._lay.itemAt(i).widget())


def _fmt_size(path) -> str:
    try:
        n = path.stat().st_size
    except OSError:
        return "?"
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} KB"


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pad(name: str, width: int = 12) -> str:
    """고정폭 글꼴에서 열을 맞추기 위한 공백 패딩 (nbsp)."""
    return _esc(name) + "&nbsp;" * max(1, width - len(name))


def _ui(text: str) -> str:
    """mono 행 안의 한글 설명은 UI 글꼴로 (스펙 §2.2 — Consolas 에 한글 글리프 없음)."""
    return f"<span style='font-family:{tokens.FONT_FAMILY}'>{_esc(text)}</span>"


def _badge_html(text: str, bg: str, fg: str) -> str:
    """Qt rich text 는 span 의 radius/padding 을 그리지 못하므로 [텍스트] + 색으로 표현 (색 단독 아님)."""
    return f"<span style='color:{fg};font-weight:600;font-family:{tokens.FONT_FAMILY}'>[{text}]</span>"
