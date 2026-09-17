"""설정 페이지 (스펙 §6.4): 계정(루트·ID·비밀번호) / 검증 타임아웃 / 진단·업데이트(M6) / 세션·계정 삭제. QScrollArea 안."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import config, doctor, service, update
from ...config import Settings
from ..theme import tokens
from ..widgets import Banner, make_busy_bar, set_class, set_invalid
from ..workers import FuncWorker, LoginWorker


class SettingsPage(QWidget):
    busy_changed = Signal(bool, str)
    settings_changed = Signal()  # 저장/삭제 후 MainWindow 가 load_settings 를 다시 시도
    status_message = Signal(str)
    timeout_changed = Signal(float)

    def __init__(self, qsettings: QSettings, config_dir: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.qs = qsettings
        self.config_dir = Path(config_dir) if config_dir is not None else config.CONFIG_DIR
        self.settings: Settings | None = None
        self._worker: LoginWorker | None = None
        self._doctor_worker: FuncWorker | None = None
        self._build()

    def _build(self) -> None:
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

        title = QLabel("설정")
        set_class(title, "title")
        root.addWidget(title)
        self.busy = make_busy_bar()
        root.addWidget(self.busy)
        self.banner = Banner()
        root.addWidget(self.banner)

        # --- 계정
        sec1 = QLabel("계정")
        set_class(sec1, "section")
        root.addWidget(sec1)
        card = QFrame()
        set_class(card, "card")
        g = QGridLayout(card)
        g.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        g.setHorizontalSpacing(tokens.SPACE)
        g.setVerticalSpacing(tokens.SPACE // 2)
        g.setColumnMinimumWidth(0, 96)
        self.root_edit = QLineEdit()
        self.root_edit.setObjectName("RootInput")
        self.root_edit.setPlaceholderText("예: C:\\Users\\<you>\\Desktop\\swea")
        browse = QPushButton("찾아보기")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.root_edit, 1)
        row.addWidget(browse)
        self.root_err = self._err_label()
        self.id_edit = QLineEdit()
        self.id_edit.setObjectName("IdInput")
        self.id_edit.setPlaceholderText("SWEA 로그인 ID (이메일)")
        self.id_edit.setMaximumWidth(280)
        self.id_err = self._err_label()
        self.pw_edit = QLineEdit()
        self.pw_edit.setObjectName("PwInput")
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_edit.setMaximumWidth(280)
        self.pw_edit.setPlaceholderText("변경할 때만 입력")
        self.pw_show = QCheckBox("표시")
        self.pw_show.toggled.connect(lambda on: self.pw_edit.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        pw_row = QHBoxLayout()
        pw_row.addWidget(self.pw_edit)
        pw_row.addWidget(self.pw_show)
        pw_row.addStretch(1)
        self.pw_err = self._err_label()
        labels = {}
        for r, (text, w) in enumerate((("루트 폴더", row), ("SWEA ID", self.id_edit), ("비밀번호", pw_row))):
            lab = QLabel(text)
            set_class(lab, "muted")
            lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            labels[text] = lab
        labels["루트 폴더"].setBuddy(self.root_edit)
        labels["SWEA ID"].setBuddy(self.id_edit)
        labels["비밀번호"].setBuddy(self.pw_edit)
        r = 0
        g.addWidget(labels["루트 폴더"], r, 0)
        g.addLayout(row, r, 1)
        r += 1
        h1 = QLabel("swea\\{주제}\\{번호}\\ 가 만들어질 상위 폴더")
        set_class(h1, "hint")
        g.addWidget(h1, r, 1)
        g.addWidget(self.root_err, r + 1, 1)
        r += 2
        g.addWidget(labels["SWEA ID"], r, 0)
        g.addWidget(self.id_edit, r, 1)
        g.addWidget(self.id_err, r + 1, 1)
        r += 2
        g.addWidget(labels["비밀번호"], r, 0)
        g.addLayout(pw_row, r, 1)
        r += 1
        h2 = QLabel("Windows 자격 증명 관리자에만 저장됩니다. 이미 저장돼 있으면 비워 두어도 됩니다")
        set_class(h2, "hint")
        h2.setWordWrap(True)
        g.addWidget(h2, r, 1)
        g.addWidget(self.pw_err, r + 1, 1)
        r += 2
        btns = QHBoxLayout()
        self.save_btn = QPushButton("저장 후 로그인 확인")
        set_class(self.save_btn, "primary")
        self.save_only_btn = QPushButton("저장만")
        btns.addWidget(self.save_btn)
        btns.addWidget(self.save_only_btn)
        btns.addStretch(1)
        g.addLayout(btns, r, 1)
        g.setColumnStretch(1, 1)
        root.addWidget(card)

        # --- 검증
        sec2 = QLabel("검증")
        set_class(sec2, "section")
        root.addWidget(sec2)
        card2 = QFrame()
        set_class(card2, "card")
        g2 = QGridLayout(card2)
        g2.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        g2.setColumnMinimumWidth(0, 96)
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 120)
        self.timeout.setSuffix(" 초")
        self.timeout.setFixedWidth(96)
        self.timeout.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)  # 스핀 버튼이 높이 제약에 깨져 보임 (W5)
        self.timeout.setValue(int(float(self.qs.value("check/timeout", 10.0, type=float))))
        self.timeout.valueChanged.connect(self._timeout_changed)
        lt = QLabel("타임아웃")
        set_class(lt, "muted")
        lt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lt.setBuddy(self.timeout)
        th = QLabel("풀이 실행 제한 시간")
        set_class(th, "hint")
        g2.addWidget(lt, 0, 0)
        g2.addWidget(self.timeout, 0, 1)
        g2.addWidget(th, 0, 2)
        g2.setColumnStretch(3, 1)
        root.addWidget(card2)

        # --- 진단·업데이트 (M6 §3·§4)
        sec4 = QLabel("진단·업데이트")
        set_class(sec4, "section")
        root.addWidget(sec4)
        card4 = QFrame()
        set_class(card4, "card")
        g4 = QGridLayout(card4)
        g4.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        g4.setVerticalSpacing(tokens.SPACE)
        d4 = QLabel("문의할 때 이슈에 붙여넣을 진단 정보 (버전·Python·설정 상태). 비밀번호·쿠키는 포함되지 않습니다")
        set_class(d4, "muted")
        d4.setWordWrap(True)
        self.doctor_btn = QPushButton("진단 정보 복사")
        self.doctor_btn.setToolTip("swea-fetch doctor 와 같은 내용을 클립보드로 복사합니다")
        self.update_check = QCheckBox("새 버전 알림 (하루 1회 GitHub Release 확인)")
        self.update_check.setChecked(not update.is_disabled(self.config_dir))
        g4.addWidget(d4, 0, 0)
        g4.addWidget(self.doctor_btn, 0, 1)
        g4.addWidget(self.update_check, 1, 0, 1, 2)
        g4.setColumnStretch(0, 1)
        root.addWidget(card4)

        # --- 삭제
        sec3 = QLabel("세션·계정 삭제")
        set_class(sec3, "section")
        root.addWidget(sec3)
        card3 = QFrame()
        set_class(card3, "card")
        g3 = QGridLayout(card3)
        g3.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        g3.setVerticalSpacing(tokens.SPACE)
        d1 = QLabel("저장된 로그인 세션만 지웁니다. 계정 정보는 유지")
        d2 = QLabel("자리 반납용 — .env 와 자격 증명 관리자의 비밀번호까지 삭제")
        for d in (d1, d2):
            set_class(d, "muted")
            d.setWordWrap(True)
        self.logout_btn = QPushButton("세션 삭제")
        self.logout_all_btn = QPushButton("계정 정보까지 삭제")
        set_class(self.logout_all_btn, "danger")
        g3.addWidget(d1, 0, 0)
        g3.addWidget(self.logout_btn, 0, 1)
        g3.addWidget(d2, 1, 0)
        g3.addWidget(self.logout_all_btn, 1, 1)
        g3.setColumnStretch(0, 1)
        root.addWidget(card3)
        root.addStretch(1)

        self.save_btn.clicked.connect(lambda: self.save(check=True))
        self.save_only_btn.clicked.connect(lambda: self.save(check=False))
        self.logout_btn.clicked.connect(lambda: self._logout(False))
        self.logout_all_btn.clicked.connect(lambda: self._logout(True))
        self.doctor_btn.clicked.connect(self.copy_doctor)
        self.update_check.toggled.connect(lambda on: update.set_disabled(self.config_dir, not on))
        for w, err in ((self.root_edit, self.root_err), (self.id_edit, self.id_err), (self.pw_edit, self.pw_err)):
            w.textEdited.connect(lambda _t, w=w, err=err: (set_invalid(w, False), err.hide()))

    @staticmethod
    def _err_label() -> QLabel:
        lab = QLabel()
        set_class(lab, "error")
        lab.hide()
        return lab

    # --- 상태 ---------------------------------------------------------------------
    def set_settings(self, settings: Settings | None) -> None:
        self.settings = settings
        values = config.read_env_file(self.config_dir)
        default_root = Path.home() / "Desktop" / "swea"
        fallback = values.get("SWEA_ROOT") or (str(default_root) if default_root.is_dir() else "")
        self.root_edit.setText(str(settings.root) if settings else fallback)
        self.id_edit.setText(settings.user_id if settings else (values.get("SWEA_ID") or ""))
        self.pw_edit.clear()

    def show_first_run(self) -> None:
        self.banner.show_message("info", "처음 실행 — 계정 설정이 필요합니다",
                                 "루트 폴더·ID·비밀번호를 저장하고 로그인 확인까지 하면 바로 쓸 수 있습니다. "
                                 "비밀번호는 Windows 자격 증명 관리자에만 저장됩니다.")
        self.root_edit.setFocus()

    def _browse(self) -> None:
        start = self.root_edit.text() or str(Path.home() / "Desktop")
        path = QFileDialog.getExistingDirectory(self, "풀이 저장소 폴더 선택", start)
        if path:
            self.root_edit.setText(path)
            set_invalid(self.root_edit, False)
            self.root_err.hide()

    def _timeout_changed(self, v: int) -> None:
        self.qs.setValue("check/timeout", float(v))
        self.timeout_changed.emit(float(v))

    def _set_busy(self, busy: bool) -> None:
        for w in (self.save_btn, self.save_only_btn, self.root_edit, self.id_edit, self.pw_edit, self.logout_btn, self.logout_all_btn):
            w.setEnabled(not busy)
        self.save_btn.setText("확인 중…" if busy else "저장 후 로그인 확인")
        self.busy.setVisible(busy)
        self.busy_changed.emit(busy, "로그인 확인 중…" if busy else "")

    # --- 저장 -----------------------------------------------------------------------
    def _validate(self, need_pw: bool) -> tuple[Path, str] | None:
        root = Path(self.root_edit.text().strip()).expanduser()
        user_id = self.id_edit.text().strip()
        ok = True
        if not self.root_edit.text().strip() or not root.is_dir():
            set_invalid(self.root_edit, True)
            self.root_err.setText(f"폴더가 없습니다: {self.root_edit.text().strip() or '(비어 있음)'}")
            self.root_err.show()
            ok = False
        if not user_id:
            set_invalid(self.id_edit, True)
            self.id_err.setText("SWEA 로그인 ID(이메일)를 입력하세요")
            self.id_err.show()
            ok = False
        if need_pw:
            set_invalid(self.pw_edit, True)
            self.pw_err.setText("비밀번호를 입력하세요 (처음 저장할 때 필요)")
            self.pw_err.show()
            ok = False
        if not ok:
            for w in (self.root_edit, self.id_edit, self.pw_edit):
                if w.property("state") == "invalid":
                    w.setFocus()
                    break
            return None
        return root, user_id

    def save(self, check: bool = True) -> None:
        if self._worker is not None:
            return
        password = self.pw_edit.text() or None
        self.pw_edit.clear()  # 화면에서 즉시 제거
        user_id = self.id_edit.text().strip()
        has_saved_pw = False
        if user_id and not password:
            try:
                has_saved_pw = bool(config.get_password(user_id))
            except Exception:  # noqa: BLE001 — keyring 접근 실패는 워커에서 다시 드러난다
                has_saved_pw = False
        v = self._validate(need_pw=not password and not has_saved_pw)
        if v is None:
            password = None
            return
        root, user_id = v
        self.banner.hide()
        if not check:
            try:
                if password:
                    config.save_password(user_id, password)
                password = None
                service.write_env(self.config_dir, root, user_id)
                config.strip_password_from_env_file(self.config_dir)
            except Exception as e:  # noqa: BLE001
                self.banner.show_message("error", f"저장 실패: {e}")
                return
            self.banner.show_message("success", "설정을 저장했습니다")
            self.settings_changed.emit()
            return
        self._worker = LoginWorker(self.config_dir, root, user_id, password, self)
        password = None
        self._worker.progress.connect(self.status_message)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._cleanup)
        self._set_busy(True)
        self._worker.start()

    def _cleanup(self) -> None:
        self._worker = None
        self._set_busy(False)

    def _on_done(self, msg: str) -> None:
        self.banner.show_message("success", msg)
        self.settings_changed.emit()

    def _on_failed(self, title: str, hint: str, detail: str) -> None:
        body = "입력한 설정은 저장됐습니다. ID/비밀번호를 고쳐 다시 확인하세요." + (f"\n{hint}" if hint else "")
        self.banner.show_message("error", title, body)
        self.settings_changed.emit()  # .env 는 저장됐으므로 다시 로드

    # --- 진단 (M6 §3) ---------------------------------------------------------------
    def copy_doctor(self) -> None:
        """doctor.report 를 워커에서 만들어 클립보드로 (네트워크 항목 포함이라 몇 초 걸릴 수 있음)."""
        if self._doctor_worker is not None:
            return
        self.doctor_btn.setEnabled(False)
        self.doctor_btn.setText("수집 중…")
        self._doctor_worker = FuncWorker(lambda: doctor.report(self.config_dir), self)
        self._doctor_worker.finished_ok.connect(self._on_doctor_done)
        self._doctor_worker.failed.connect(lambda t, h, d: self.banner.show_message("error", f"진단 정보 수집 실패: {t}", d))
        self._doctor_worker.finished.connect(self._doctor_cleanup)
        self._doctor_worker.start()

    def _on_doctor_done(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.status_message.emit("진단 정보를 클립보드에 복사했습니다")
        self.banner.show_message("success", "진단 정보를 클립보드에 복사했습니다 — 이슈에 붙여넣으세요", text)

    def _doctor_cleanup(self) -> None:
        self._doctor_worker = None
        self.doctor_btn.setEnabled(True)
        self.doctor_btn.setText("진단 정보 복사")

    # --- 삭제 -----------------------------------------------------------------------
    def _logout(self, all_: bool) -> None:
        if all_:
            box = QMessageBox(QMessageBox.Icon.Warning, "계정 정보 삭제",
                              ".env 와 Windows 자격 증명 관리자의 비밀번호가 삭제됩니다.\n다시 쓰려면 설정을 처음부터 입력해야 합니다.", parent=self)
            delete = box.addButton("삭제", QMessageBox.ButtonRole.DestructiveRole)
            set_class(delete, "danger")
            cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(cancel)
            box.setEscapeButton(cancel)
            box.exec()
            if box.clickedButton() is not delete:
                return
        try:
            removed = service.logout(self.config_dir, all_=all_)
        except Exception as e:  # noqa: BLE001
            self.banner.show_message("error", f"삭제 중 오류: {e}")
            return
        if all_:
            self.root_edit.clear()
            self.id_edit.clear()
            self.pw_edit.clear()
            self.banner.show_message("info", "계정 정보를 삭제했습니다. 다시 쓰려면 설정을 입력하세요", ", ".join(removed))
        else:
            self.status_message.emit("세션을 삭제했습니다")
            self.banner.show_message("success", "세션을 삭제했습니다", ", ".join(removed) if removed else "삭제할 항목 없음")
        self.settings_changed.emit()
