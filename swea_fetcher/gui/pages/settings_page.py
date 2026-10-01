"""설정 페이지 (스펙 §6.4): 계정(루트·ID·비밀번호) / 검증 타임아웃 / GitHub 연동(M7) / 진단·업데이트(M6) / 세션·계정 삭제. QScrollArea 안."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QRadioButton,
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

from ... import ai_engine, config, content_cache, doctor, gitops, service, solved, update
from ...config import Settings
from ...errors import AiError
from ..coach_widgets import ask_consent, has_consent, reset_consents
from ..theme import tokens
from ..widgets import Banner, Button, ThemeChip, Toggle, make_busy_bar, set_class, set_invalid
from ..workers import CoachWorker, FuncWorker, LoginWorker



def _swatch_qss(color: str, on: bool, pal) -> str:
    """원형 색 칩 (24px). 선택이면 굵은 테두리. QSS 의 min/max 크기는 테두리 안쪽 — 전역 버튼 최소 높이(30)를 덮어 원형 유지."""
    bw = 3 if on else 1
    inner = 24 - 2 * bw
    return (
        f"QPushButton {{ background: {color}; border: {bw}px solid {pal.text if on else pal.border}; border-radius: 12px; "
        f"min-width: {inner}px; max-width: {inner}px; min-height: {inner}px; max-height: {inner}px; padding: 0px; }}"
    )

class SettingsPage(QWidget):
    busy_changed = Signal(bool, str)
    settings_changed = Signal()  # 저장/삭제 후 MainWindow 가 load_settings 를 다시 시도
    status_message = Signal(str)
    timeout_changed = Signal(float)
    cache_settings_changed = Signal()  # 지문 캐시 사용 토글 (문제 탭 안내문 갱신용)
    heat_color_changed = Signal()  # 풀이 잔디 색 변경 (M20) — 성장 탭이 즉시 다시 칠한다
    theme_changed = Signal(str)  # 화면 테마(색 조합) 변경 (M21) — 메인이 QSS 를 다시 적용한다. 인자 = 테마 key
    coach_settings_changed = Signal()  # AI 코치 설정·기록 변경 (엔진·오답 기준·복습일·기록 지우기) — 메인이 설정 객체·배지를 갱신

    def __init__(self, qsettings: QSettings, config_dir: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.qs = qsettings
        self.config_dir = Path(config_dir) if config_dir is not None else config.CONFIG_DIR
        self.settings: Settings | None = None
        self._worker: LoginWorker | None = None
        self._doctor_worker: FuncWorker | None = None
        self._git_worker: FuncWorker | None = None
        self._ai_detect_worker: FuncWorker | None = None
        self._ai_ping_worker: CoachWorker | None = None
        self._loading_ai = False
        self._last_ai_status = None  # 마지막 감지 결과 (엔진 콤보가 바뀌면 보조 문구만 다시 그린다)
        self._ai_status_stale = True
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
        browse = Button("찾아보기")
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
        self.save_btn = Button("저장 후 로그인 확인")
        set_class(self.save_btn, "primary")
        self.save_only_btn = Button("저장만")
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

        # --- GitHub 연동 (M7)
        sec5 = QLabel("GitHub 연동")
        set_class(sec5, "section")
        root.addWidget(sec5)
        card5 = QFrame()
        set_class(card5, "card")
        g5 = QGridLayout(card5)
        g5.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        g5.setVerticalSpacing(tokens.SPACE)
        g5.setColumnMinimumWidth(0, 96)
        l_repo = QLabel("저장소")
        set_class(l_repo, "muted")
        l_repo.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.git_status = QLabel("확인 중…")
        self.git_status.setWordWrap(True)
        self.git_status.setOpenExternalLinks(True)
        self.git_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        l_tpl = QLabel("커밋 메시지")
        set_class(l_tpl, "muted")
        l_tpl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.commit_template = QLineEdit()
        self.commit_template.setPlaceholderText(gitops.DEFAULT_COMMIT_TEMPLATE)
        self.commit_template.setAccessibleName("커밋 메시지 템플릿")
        l_tpl.setBuddy(self.commit_template)
        tpl_hint = QLabel("변수: {num} {title} {topic} {date} — 비우면 기본값. 입력 후 Enter 또는 포커스 이동으로 저장")
        set_class(tpl_hint, "hint")
        tpl_hint.setWordWrap(True)
        self.auto_push = Toggle("GitHub 자동 동기화 켜기")
        auto_hint = QLabel("선택한 시점마다 확인 없이 GitHub 에 올라갑니다. 공용 PC 에선 자리 반납 시 logout --all 과 git 자격증명 정리를 잊지 마세요")
        set_class(auto_hint, "hint")
        auto_hint.setWordWrap(True)
        # 범위
        self.scope_problem = QRadioButton("문제 폴더만")
        self.scope_root = QRadioButton("루트 전체 (swea 폴더의 모든 변경, .gitignore 제외)")
        self.scope_group = QButtonGroup(self)
        self.scope_group.addButton(self.scope_problem)
        self.scope_group.addButton(self.scope_root)
        self.scope_problem.setChecked(True)
        scope_row = QHBoxLayout()
        scope_row.addWidget(self.scope_problem)
        scope_row.addWidget(self.scope_root)
        scope_row.addStretch(1)
        scope_wrap = QWidget()
        scope_wrap.setLayout(scope_row)
        # 시점
        self.on_pass = QCheckBox("SWEA 제출 Pass")
        self.on_check = QCheckBox("로컬 검증 통과")
        self.on_save = QCheckBox("저장 직후")
        self.on_watch = QCheckBox("변경 감지 — 앱이 켜져 있는 동안 파일이 바뀌면 90초 뒤 자동 (버튼 불필요)")
        self.on_pass.setChecked(True)
        when_box = QVBoxLayout()
        when_row = QHBoxLayout()
        for w in (self.on_pass, self.on_check, self.on_save):
            when_row.addWidget(w)
        when_row.addStretch(1)
        when_box.addLayout(when_row)
        when_box.addWidget(self.on_watch)
        when_wrap = QWidget()
        when_wrap.setLayout(when_box)
        self.sync_on_close = QCheckBox("앱 종료 시 남은 변경 동기화")
        self.sync_now_btn = Button("지금 동기화")
        l_scope = QLabel("범위")
        l_when = QLabel("시점")
        for lb in (l_scope, l_when):
            set_class(lb, "muted")
            lb.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        g5.addWidget(l_repo, 0, 0)
        g5.addWidget(self.git_status, 0, 1)
        g5.addWidget(self.sync_now_btn, 0, 2)
        g5.addWidget(l_tpl, 1, 0)
        g5.addWidget(self.commit_template, 1, 1, 1, 2)
        g5.addWidget(tpl_hint, 2, 1, 1, 2)
        g5.addWidget(self.auto_push, 3, 1, 1, 2)
        g5.addWidget(auto_hint, 4, 1, 1, 2)
        g5.addWidget(l_scope, 5, 0)
        g5.addWidget(scope_wrap, 5, 1, 1, 2)
        g5.addWidget(l_when, 6, 0)
        g5.addWidget(when_wrap, 6, 1, 1, 2)
        g5.addWidget(self.sync_on_close, 7, 1, 1, 2)
        g5.setColumnStretch(1, 1)
        root.addWidget(card5)

        # --- 문제 지문 (M12)
        sec6 = QLabel("문제 지문")
        set_class(sec6, "section")
        root.addWidget(sec6)
        card6 = QFrame()
        set_class(card6, "card")
        g6 = QGridLayout(card6)
        g6.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        g6.setVerticalSpacing(tokens.SPACE)
        self.auto_open_problem = QCheckBox("저장 후 문제 탭으로 이동")
        self.auto_open_problem.setChecked(self.qs.value("fetch/auto_open_problem", True, type=bool))
        self.cache_enabled = QCheckBox("지문 캐시 사용 (최근 50건을 다시 볼 수 있게 이 PC 에 보관)")
        self.cache_enabled.setChecked(self.qs.value("problem/cache_enabled", True, type=bool))
        cache_hint = QLabel("지문은 풀이 폴더에 저장되지 않으며 GitHub 로 올라가지 않습니다. 캐시는 설정 폴더(~/.swea-fetch/cache)에만 있습니다")
        set_class(cache_hint, "hint")
        cache_hint.setWordWrap(True)
        self.cache_clear_btn = Button("캐시 지우기")
        g6.addWidget(self.auto_open_problem, 0, 0, 1, 2)
        g6.addWidget(self.cache_enabled, 1, 0)
        g6.addWidget(self.cache_clear_btn, 1, 1)
        g6.addWidget(cache_hint, 2, 0, 1, 2)
        g6.setColumnStretch(0, 1)
        root.addWidget(card6)

        # --- AI 코치 (M17)
        sec7 = QLabel("AI 코치")
        set_class(sec7, "section")
        root.addWidget(sec7)
        card7 = QFrame()
        set_class(card7, "card")
        g7 = QGridLayout(card7)
        g7.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        g7.setVerticalSpacing(tokens.SPACE)
        g7.setHorizontalSpacing(tokens.SPACE)
        g7.setColumnMinimumWidth(0, 96)

        def _label(text: str, buddy=None) -> QLabel:
            lab = QLabel(text)
            set_class(lab, "muted")
            lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if buddy is not None:
                lab.setBuddy(buddy)
            return lab

        self.ai_engine = QComboBox()
        self.ai_engine.setObjectName("AiEngineCombo")
        for value, text in (
            ("auto", "자동 (Codex 우선)"),
            ("codex", ai_engine.ENGINE_LABELS["codex"]),
            ("claude", ai_engine.ENGINE_LABELS["claude"]),
            ("both", "GPT & Claude (둘 다)"),
        ):
            self.ai_engine.addItem(text, value)
        self.ai_both_hint = QLabel("GPT 와 Claude 에 각각 1번씩 요청하고 답 2개를 나란히 보여줍니다 (각 서비스에서 쓰는 양은 한 곳만 쓸 때와 같습니다).")  # 둘 다 모드에서만
        self.ai_both_hint.setObjectName("AiBothHint")
        set_class(self.ai_both_hint, "hint")
        self.ai_both_hint.setWordWrap(True)
        self.ai_both_hint.hide()
        self.ai_engine.setAccessibleName("AI 엔진")
        self.ai_engine.setMinimumWidth(180)
        self.ai_status = QLabel("확인 중…")
        self.ai_status.setWordWrap(True)
        self.ai_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.ai_detect_btn = Button("다시 감지")
        self.ai_test_btn = Button("연결 테스트")
        self.ai_test_btn.setToolTip("테스트 문장만 보내 엔진이 응답하는지 확인합니다 (코드·지문은 보내지 않음)")
        self.ai_note = QLabel()  # 환경변수 API 키 경고 / 설치 안내
        set_class(self.ai_note, "hint")
        self.ai_note.setWordWrap(True)
        self.ai_note.hide()
        self.ai_threshold = QSpinBox()
        self.ai_threshold.setObjectName("AiThresholdSpin")
        self.ai_threshold.setRange(*config.AI_WRONG_THRESHOLD_RANGE)
        self.ai_threshold.setSuffix(" 회")
        self.ai_threshold.setFixedWidth(96)
        self.ai_threshold.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.review_days = QSpinBox()
        self.review_days.setObjectName("ReviewDaysSpin")
        self.review_days.setRange(*config.REVIEW_DAYS_RANGE)
        self.review_days.setSuffix(" 일")
        self.review_days.setFixedWidth(96)
        self.review_days.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.ai_consent_reset_btn = Button("AI 전송 동의 초기화")
        self.ai_clear_btn = Button("AI 기록 지우기")
        self.ai_clear_btn.setToolTip("응답 캐시·오답 횟수·복습 일정·성장 기록을 지웁니다")
        th_hint = QLabel("이 횟수 이상 틀리면 정답 풀이를 제안합니다")
        rv_hint = QLabel("정답 풀이를 본 뒤 다시 풀기를 권유할 때까지의 일수")
        for h in (th_hint, rv_hint):
            set_class(h, "hint")
            h.setWordWrap(True)
        ai_hint = QLabel("버튼을 누를 때만 지문·코드가 AI 로 전송됩니다. 기록은 ~/.swea-fetch/coach 에만 있고 GitHub 로 올라가지 않습니다.")
        set_class(ai_hint, "hint")
        ai_hint.setWordWrap(True)
        g7.addWidget(_label("엔진", self.ai_engine), 0, 0)
        engine_box = QVBoxLayout()
        engine_box.setSpacing(tokens.SPACE // 2)
        engine_box.addWidget(self.ai_engine, 0, Qt.AlignmentFlag.AlignLeft)
        engine_box.addWidget(self.ai_both_hint)
        g7.addLayout(engine_box, 0, 1, 1, 2)
        g7.addWidget(_label("감지 상태"), 1, 0)
        g7.addWidget(self.ai_status, 1, 1)
        g7.addWidget(self.ai_detect_btn, 1, 2)
        g7.addWidget(self.ai_note, 2, 1, 1, 2)
        g7.addWidget(_label("연결"), 3, 0)
        g7.addWidget(self.ai_test_btn, 3, 1, 1, 2, Qt.AlignmentFlag.AlignLeft)
        g7.addWidget(_label("오답 기준", self.ai_threshold), 4, 0)
        g7.addWidget(self.ai_threshold, 4, 1, Qt.AlignmentFlag.AlignLeft)
        g7.addWidget(th_hint, 4, 2)
        g7.addWidget(_label("복습", self.review_days), 5, 0)
        g7.addWidget(self.review_days, 5, 1, Qt.AlignmentFlag.AlignLeft)
        g7.addWidget(rv_hint, 5, 2)
        ai_btns = QHBoxLayout()
        ai_btns.addWidget(self.ai_consent_reset_btn)
        ai_btns.addWidget(self.ai_clear_btn)
        ai_btns.addStretch(1)
        g7.addLayout(ai_btns, 6, 1, 1, 2)
        g7.addWidget(ai_hint, 7, 1, 1, 2)
        g7.setColumnStretch(1, 1)
        root.addWidget(card7)

        # --- 성장 기록 (M19)
        sec8 = QLabel("성장 기록")
        set_class(sec8, "section")
        root.addWidget(sec8)
        card8 = QFrame()
        set_class(card8, "card")
        g8 = QVBoxLayout(card8)
        g8.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        g8.setSpacing(tokens.SPACE // 2)
        self.growth_enabled = Toggle("성장 기록 사용")
        self.growth_enabled.setObjectName("GrowthEnabledCheck")
        gh1 = QLabel("AI 코치 응답에서 분류 태그만 저장합니다(코드·지문 저장 안 함). 끄면 태그 요청과 기록을 모두 멈춥니다.")
        self.growth_comment = Toggle("주간 AI 코멘트 자동 생성")
        self.growth_comment.setObjectName("GrowthCommentCheck")
        gh2 = QLabel("주 1회, 집계 숫자와 분류 이름만 AI 로 보냅니다. 코드·지문·문제 번호는 보내지 않습니다.")
        gh3 = QLabel("기록은 ~/.swea-fetch/coach/profile 에만 있고 GitHub 로 올라가지 않습니다. 풀이 잔디(하루에 푼 문제)도 여기에 저장됩니다.")
        gh4 = QLabel("성장 탭 맨 위 풀이 잔디의 색입니다. 고른 색을 기준으로 4단계 농도가 만들어집니다.")
        for h in (gh1, gh2, gh3, gh4):
            set_class(h, "hint")
            h.setWordWrap(True)
        self.growth_clear_btn = Button("성장 기록 지우기")
        self.growth_clear_btn.setToolTip("분류 기록·주간 리포트·풀이 잔디를 지웁니다 (AI 응답 캐시·복습 일정은 그대로)")
        heat_row = QHBoxLayout()
        heat_row.setSpacing(tokens.SPACE)
        heat_row.addWidget(QLabel("풀이 잔디 색"))
        self.heat_group = QButtonGroup(self)
        self.heat_group.setExclusive(True)
        self.heat_buttons: dict[str, QPushButton] = {}
        for name, hexv in solved.HEAT_PRESETS:
            b = QPushButton()
            b.setObjectName(f"HeatPreset_{hexv[1:]}")
            b.setCheckable(True)
            b.setFixedSize(24, 24)
            b.setToolTip(name)
            b.setAccessibleName(f"풀이 잔디 색: {name}")
            b.clicked.connect(lambda _c=False, v=hexv: self._set_heat_color(v))
            self.heat_group.addButton(b)
            self.heat_buttons[hexv] = b
            heat_row.addWidget(b)
        # 직접 고른 색: 프리셋과 같은 원형 칩으로 보여 준다 (프리셋이 아닌 색일 때만). 누르면 다시 고르기
        self.heat_custom_swatch = QPushButton()
        self.heat_custom_swatch.setObjectName("HeatCustomSwatch")
        self.heat_custom_swatch.setFixedSize(24, 24)
        self.heat_custom_swatch.setAccessibleName("풀이 잔디 색: 직접 고른 색")
        self.heat_custom_swatch.hide()
        heat_row.addWidget(self.heat_custom_swatch)
        self.heat_custom_btn = Button("직접 고르기")
        self.heat_custom_btn.setObjectName("HeatCustomButton")
        self.heat_custom_btn.setToolTip("원하는 색을 직접 고릅니다")
        heat_row.addWidget(self.heat_custom_btn)
        heat_row.addStretch(1)
        self.heat_color = solved.parse_hex(str(self.qs.value("growth/heat_color", solved.DEFAULT_HEAT_COLOR) or ""))
        g8.addWidget(self.growth_enabled)
        g8.addWidget(gh1)
        g8.addSpacing(tokens.SPACE)
        g8.addWidget(self.growth_comment)
        g8.addWidget(gh2)
        g8.addSpacing(tokens.SPACE)
        g8.addLayout(heat_row)
        g8.addWidget(gh4)
        g8.addSpacing(tokens.SPACE)
        g8.addWidget(self.growth_clear_btn, 0, Qt.AlignmentFlag.AlignLeft)
        g8.addWidget(gh3)
        root.addWidget(card8)

        # --- 화면 (M21): 테마(색 조합). 선택 즉시 전체 QSS 재적용, QSettings ui/theme 에 저장
        sec9 = QLabel("화면")
        set_class(sec9, "section")
        root.addWidget(sec9)
        card9 = QFrame()
        set_class(card9, "card")
        g9 = QVBoxLayout(card9)
        g9.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        g9.setSpacing(tokens.SPACE)
        theme_label = QLabel("테마 색")
        set_class(theme_label, "section")
        g9.addWidget(theme_label)
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_chips: dict[str, ThemeChip] = {}
        saved_theme = tokens.get_theme(str(self.qs.value(tokens.THEME_SETTING_KEY, tokens.DEFAULT_THEME) or tokens.DEFAULT_THEME)).key
        theme_grid = QGridLayout()
        theme_grid.setHorizontalSpacing(tokens.SPACE)
        theme_grid.setVerticalSpacing(tokens.SPACE)
        for i, t in enumerate(tokens.THEMES):
            chip = ThemeChip(t.key, t.label, t.palette)
            chip.setChecked(t.key == saved_theme)
            chip.clicked.connect(lambda _c=False, k=t.key: self._set_theme(k))
            self.theme_group.addButton(chip)
            self.theme_chips[t.key] = chip
            theme_grid.addWidget(chip, i // 3, i % 3)
        theme_grid.setColumnStretch(3, 1)
        g9.addLayout(theme_grid)
        theme_hint = QLabel("버튼·선택 표시의 색 조합입니다. 고르면 바로 바뀌고 다음 실행에도 유지됩니다. 풀이 잔디 색은 위 성장 기록에서 따로 고릅니다.")
        set_class(theme_hint, "hint")
        theme_hint.setWordWrap(True)
        g9.addWidget(theme_hint)
        root.addWidget(card9)

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
        self.doctor_btn = Button("진단 정보 복사")
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
        self.logout_btn = Button("세션 삭제")
        self.logout_all_btn = Button("계정 정보까지 삭제")
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
        self.auto_open_problem.toggled.connect(lambda on: self.qs.setValue("fetch/auto_open_problem", on))
        self.cache_enabled.toggled.connect(self._cache_toggled)
        self.cache_clear_btn.clicked.connect(self._clear_cache)
        self.update_check.toggled.connect(lambda on: update.set_disabled(self.config_dir, not on))
        self.ai_engine.currentIndexChanged.connect(self._ai_engine_changed)
        self.ai_threshold.editingFinished.connect(lambda: self._ai_number_saved("SWEA_AI_WRONG_THRESHOLD", self.ai_threshold.value(), "ai_wrong_threshold"))
        self.review_days.editingFinished.connect(lambda: self._ai_number_saved("SWEA_REVIEW_DAYS", self.review_days.value(), "review_days"))
        self.ai_detect_btn.clicked.connect(self._detect_ai)
        self.ai_test_btn.clicked.connect(self._ai_ping)
        self.ai_consent_reset_btn.clicked.connect(self._reset_ai_consent)
        self.ai_clear_btn.clicked.connect(self._clear_ai_records)
        self.growth_enabled.toggled.connect(lambda on: self._growth_toggled("SWEA_GROWTH", on))
        self.growth_comment.toggled.connect(lambda on: self._growth_toggled("SWEA_GROWTH_COMMENT", on))
        self.growth_clear_btn.clicked.connect(self._clear_growth)
        self.heat_custom_btn.clicked.connect(self._pick_heat_color)
        self.heat_custom_swatch.clicked.connect(self._pick_heat_color)
        self._paint_heat_buttons()
        self.commit_template.editingFinished.connect(self._save_template)
        self.auto_push.clicked.connect(self._auto_push_clicked)
        self.scope_root.toggled.connect(self._scope_root_toggled)
        for w in (self.on_pass, self.on_check, self.on_save, self.on_watch):
            w.toggled.connect(lambda _c: self._save_autosync())
        self.scope_problem.toggled.connect(lambda _c: self._save_autosync())
        self.sync_on_close.toggled.connect(lambda on: self.qs.setValue("autosync/sync_on_close", on))
        self.sync_now_btn.clicked.connect(self._sync_now_clicked)
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
        # GitHub 연동 (M7)
        tpl = settings.commit_template if settings else (values.get("SWEA_COMMIT_TEMPLATE") or "")
        self.commit_template.setText("" if tpl == gitops.DEFAULT_COMMIT_TEMPLATE else tpl)
        self._loading_autosync = True
        self.auto_push.setChecked(bool(settings.auto_push) if settings else config._truthy(values.get("SWEA_AUTO_PUSH")))
        scope = settings.auto_push_scope if settings else (values.get("SWEA_AUTO_PUSH_SCOPE") or "problem")
        self.scope_root.setChecked(scope == "root")
        self.scope_problem.setChecked(scope != "root")
        on = set(settings.auto_push_on) if settings else {m.strip() for m in (values.get("SWEA_AUTO_PUSH_ON") or "pass").split(",")}
        self.on_pass.setChecked("pass" in on)
        self.on_check.setChecked("check" in on)
        self.on_save.setChecked("save" in on)
        self.on_watch.setChecked("watch" in on)
        self.sync_on_close.setChecked(self.qs.value("autosync/sync_on_close", True, type=bool))
        self.sync_on_close.setVisible(self.on_watch.isChecked())
        self._loading_autosync = False
        # AI 코치 (M17): 입력값 채우기 (저장 시그널이 돌지 않게 막고)
        self._loading_ai = True
        engine = settings.ai_engine if settings else (values.get("SWEA_AI_ENGINE") or "auto")
        self.ai_engine.setCurrentIndex(max(0, self.ai_engine.findData(engine)))
        self.ai_threshold.setValue(settings.ai_wrong_threshold if settings else 3)
        self.review_days.setValue(settings.review_days if settings else 3)
        self.growth_enabled.setChecked(settings.growth if settings else config._truthy(values.get("SWEA_GROWTH") or "1"))
        self.growth_comment.setChecked(settings.growth_comment if settings else config._truthy(values.get("SWEA_GROWTH_COMMENT") or "1"))
        self.growth_comment.setEnabled(self.growth_enabled.isChecked())
        self._loading_ai = False
        self._ai_status_stale = True
        if self.isVisible():
            self._detect_ai()
        self._git_root = settings.root if settings else None
        self._git_status_stale = True
        if self.isVisible():
            self.refresh_git_status(self._git_root)
        else:
            self.git_status.setText("확인 중…" if self._git_root else "루트 폴더를 먼저 저장하세요")

    def showEvent(self, e) -> None:  # noqa: N802
        """저장소 상태는 페이지가 보일 때만 읽는다 (git 호출 수 절약, 테스트에서 불필요한 워커 방지)."""
        super().showEvent(e)
        if getattr(self, "_git_status_stale", False):
            self.refresh_git_status(getattr(self, "_git_root", None))
        if self._ai_status_stale:
            self._detect_ai()

    def wait_workers(self, ms: int = 5000) -> None:
        """창 닫힐 때 워커가 살아 있으면 기다린다 (QThread 가 실행 중 파괴되면 abort)."""
        if self._ai_ping_worker is not None and self._ai_ping_worker.isRunning():
            self._ai_ping_worker.cancel()  # 최대 5분 대기 금지 — 프로세스 트리를 먼저 종료
        for w in (self._git_worker, self._doctor_worker, self._worker, self._ai_detect_worker, self._ai_ping_worker):
            if w is not None and w.isRunning():
                w.wait(ms)

    README_GIT_URL = "https://github.com/yoon7270/swea_fetcher#github-연동"

    def refresh_git_status(self, root: Path | None) -> None:
        """루트의 저장소 상태를 워커에서 읽어 표시 (git 호출 여러 번이라 UI 스레드에서 하지 않는다)."""
        if root is None:
            self.git_status.setText("루트 폴더를 먼저 저장하세요")
            return
        if self._git_worker is not None:
            return
        self._git_status_stale = False
        self.git_status.setText("확인 중…")
        self._git_worker = FuncWorker(lambda: (gitops.git_version(), gitops.find_repo(root)), self)
        self._git_worker.finished_ok.connect(self._show_git_status)
        self._git_worker.failed.connect(lambda t, h, d: self.git_status.setText(f"확인 실패: {t}"))
        self._git_worker.finished.connect(self._git_status_cleanup)
        self._git_worker.start()

    def _git_status_cleanup(self) -> None:
        self._git_worker = None

    def _show_git_status(self, info) -> None:
        version, repo = info
        link = f'<a href="{self.README_GIT_URL}">README \'GitHub 연동\'</a>'
        if version is None:
            self.git_status.setText(f"git 이 설치되어 있지 않습니다 — 커밋+푸시를 쓰려면 Git for Windows 설치 ({link})")
            return
        if repo is None:
            self.git_status.setText(f"저장소 아님 — 루트 폴더에서 git init 과 원격 설정이 필요합니다 ({link})")
            return
        branch = repo.branch or "(detached HEAD)"
        target = f" → {repo.upstream}" if repo.upstream else (" (upstream 없음 — 첫 푸시 때 설정)" if repo.remote else " (원격 없음)")
        self.git_status.setText(f"{repo.toplevel}<br>{branch}{target}")
        self.git_status.setToolTip(repo.remote or "")

    def _save_template(self) -> None:
        tpl = self.commit_template.text().strip()
        current = self.settings.commit_template if self.settings else gitops.DEFAULT_COMMIT_TEMPLATE
        if (tpl or gitops.DEFAULT_COMMIT_TEMPLATE) == current:
            return
        service.set_env_values(self.config_dir, SWEA_COMMIT_TEMPLATE=tpl or None)
        self.status_message.emit("커밋 메시지 템플릿을 저장했습니다")
        self.settings_changed.emit()

    def _auto_push_clicked(self, on: bool) -> None:
        """켤 때 경고 1회 (사용자 클릭에만 반응)."""
        if on:
            box = QMessageBox(QMessageBox.Icon.Warning, "GitHub 자동 동기화",
                              "선택한 시점마다 확인 없이 GitHub 에 올라갑니다.\n루트 전체를 고르면 풀이 외 파일도 포함됩니다.\n공용 PC 에선 자리 반납 시 logout --all 과 git 자격증명 정리를 잊지 마세요.\n\n켤까요?",
                              parent=self)
            ok = box.addButton("켜기", QMessageBox.ButtonRole.AcceptRole)
            cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(cancel)
            box.setEscapeButton(cancel)
            box.exec()
            if box.clickedButton() is not ok:
                self.auto_push.setChecked(False)
                return
        self._save_autosync()
        self.status_message.emit("GitHub 자동 동기화를 " + ("켰습니다" if on else "껐습니다"))

    def _scope_root_toggled(self, on: bool) -> None:
        """루트 전체를 처음 고르면 올라갈 파일 수·예시를 보여주고 확인 (§5)."""
        if getattr(self, "_loading_autosync", False):
            return
        if on and self.settings is not None:
            files = self._root_pending_files()
            if files:
                sample = ", ".join(files[:5])
                box = QMessageBox(QMessageBox.Icon.Warning, "루트 전체 동기화",
                                  f"지금 루트에 미커밋 파일 {len(files)}개가 있습니다 — 예: {sample}\n\n루트 전체를 켜면 이 파일들도 GitHub 에 올라갑니다. .gitignore 로 제외를 권장합니다. 계속할까요?",
                                  parent=self)
                ok = box.addButton("루트 전체 사용", QMessageBox.ButtonRole.AcceptRole)
                cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
                box.setDefaultButton(cancel)
                box.setEscapeButton(cancel)
                box.exec()
                if box.clickedButton() is not ok:
                    self.scope_problem.setChecked(True)
                    return
        self._save_autosync()

    def _root_pending_files(self) -> list[str]:
        try:
            repo = gitops.find_repo(self.settings.root)
            if repo is None:
                return []
            out = gitops._ok(["status", "--porcelain", "--untracked-files=all"], repo.toplevel) or ""
            return [ln[3:].strip().strip('"') for ln in out.splitlines() if ln.strip()]
        except Exception:  # noqa: BLE001
            return []

    def _save_autosync(self) -> None:
        if getattr(self, "_loading_autosync", False):
            return
        on = {m for m, w in (("pass", self.on_pass), ("check", self.on_check), ("save", self.on_save), ("watch", self.on_watch)) if w.isChecked()}
        if not on:
            on = {"pass"}
        self.sync_on_close.setVisible(self.on_watch.isChecked())
        service.set_env_values(
            self.config_dir,
            SWEA_AUTO_PUSH="1" if self.auto_push.isChecked() else "0",
            SWEA_AUTO_PUSH_SCOPE="root" if self.scope_root.isChecked() else "problem",
            SWEA_AUTO_PUSH_ON=",".join(sorted(on)),
        )
        self.settings_changed.emit()

    def _sync_now_clicked(self) -> None:
        if self.settings is None or self._git_worker is not None:
            return
        self.sync_now_btn.setEnabled(False)
        self.sync_now_btn.setText("동기화 중…")
        self._git_worker = FuncWorker(lambda: service.sync_now(self.settings, reason="manual"), self)
        self._git_worker.finished_ok.connect(self._on_sync_now)
        self._git_worker.failed.connect(lambda t, h, d: self.banner.show_message("error", f"동기화 실패: {t}", h))
        self._git_worker.finished.connect(self._sync_now_cleanup)
        self._git_worker.start()

    def _on_sync_now(self, result) -> None:
        if result is None:
            self.banner.show_message("info", "동기화할 수 없습니다", "git 저장소·origin 을 확인하세요 (README 'GitHub 자동 동기화')")
        else:
            state = "error" if result.failed else "success"
            self.banner.show_message(state, f"동기화: {result.note}", result.output[-400:] if result.output else "")

    def _sync_now_cleanup(self) -> None:
        self._git_worker = None
        self.sync_now_btn.setEnabled(True)
        self.sync_now_btn.setText("지금 동기화")

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

    # --- AI 코치 (M17) --------------------------------------------------------------------
    def _ai_engine_changed(self, _idx: int) -> None:
        self._sync_ai_both_ui()
        if self._loading_ai:
            return
        value = str(self.ai_engine.currentData() or "auto")
        service.set_env_values(self.config_dir, SWEA_AI_ENGINE=value)
        self.status_message.emit("AI 엔진 설정을 저장했습니다")
        self.coach_settings_changed.emit()

    def _sync_ai_both_ui(self) -> None:
        """둘 다 모드일 때만 "각각 1번씩 요청" 힌트를 보이고, 감지 상태 보조 문구를 다시 만든다."""
        self.ai_both_hint.setVisible(self.ai_engine.currentData() == "both")
        if self._last_ai_status is not None:
            self._show_ai_status(self._last_ai_status)

    def _ai_number_saved(self, key: str, value: int, attr: str) -> None:
        """오답 기준·복습일 저장 (editingFinished). 바뀌지 않았으면 쓰지 않는다."""
        if self._loading_ai or (self.settings is not None and getattr(self.settings, attr) == value):
            return
        service.set_env_values(self.config_dir, **{key: str(value)})
        self.status_message.emit("AI 코치 설정을 저장했습니다")
        self.coach_settings_changed.emit()

    def _detect_ai(self) -> None:
        """설치된 엔진과 버전 감지 (--version 실행이라 워커에서)."""
        if self._ai_detect_worker is not None:
            return
        self._ai_status_stale = False
        self.ai_status.setText("감지 중…")
        self.ai_detect_btn.setEnabled(False)
        w = FuncWorker(lambda: service.detect_engines(self.settings), self)
        w.finished_ok.connect(self._show_ai_status)
        w.failed.connect(lambda t, _h, _d: self.ai_status.setText(f"감지 실패: {t}"))
        w.finished.connect(self._ai_detect_cleanup)
        self._ai_detect_worker = w
        w.start()

    def _ai_detect_cleanup(self) -> None:
        self._ai_detect_worker = None
        self.ai_detect_btn.setEnabled(True)

    def _show_ai_status(self, status) -> None:
        self._last_ai_status = status
        parts = []
        for e in status.engines:
            if not e.found:
                parts.append(f"{e.label} 없음")
            elif e.ok:
                parts.append(f"{e.label} {e.version} 감지됨 ({e.path})")
            else:
                parts.append(f"{e.label} 실행 실패 ({e.path})")
        self.ai_status.setText(" · ".join(parts))
        notes = []
        if status.api_keys:
            notes.append(f"환경변수 {', '.join(status.api_keys)} 가 설정되어 있습니다 — CLI 가 구독 대신 API 과금으로 동작할 수 있습니다 (앱은 지우지 않습니다)")
        if not any(e.found for e in status.engines):
            notes.append(ai_engine.install_hint())
        elif self.ai_engine.currentData() == "both" and not all(e.found for e in status.engines):
            notes.append("둘 다 모드는 설치된 쪽만 실행합니다")
        self.ai_note.setText("\n".join(notes))
        self.ai_note.setVisible(bool(notes))

    def _ai_ping(self) -> None:
        """[연결 테스트]: 고정 문장 1건. 실패하면 실행 명령줄(프롬프트 제외)과 stderr 끝부분을 그대로 보여준다."""
        if self._ai_ping_worker is not None:
            return
        if self.settings is None:
            self.banner.show_message("warning", "설정을 먼저 저장하세요", "루트 폴더·SWEA ID·비밀번호를 저장한 뒤 테스트할 수 있습니다")
            return
        try:
            sel = service.resolve_engines(self.settings)
        except AiError as e:
            self.banner.show_message("warning", "AI 엔진을 찾지 못했습니다", e.hint or str(e))
            return
        need = [e for e in sel.engines if not has_consent(self.qs, e.name)]  # 미동의 엔진을 한 다이얼로그에 모은다
        if need and not ask_consent(self, [e.label for e in need], ping=True, dual=len(sel.engines) >= 2):
            return  # 테스트 문장만 보내는 동의라 엔진 동의로는 저장하지 않는다 (코드 전송 동의는 첫 코치 사용 때)
        w = CoachWorker(self.settings, "ping", parent=self)
        w.finished_ok.connect(self._on_ping_done)
        w.ai_failed.connect(lambda _c, title, hint: self.banner.show_message("error", title, hint))
        w.failed.connect(lambda title, hint, detail: self.banner.show_message("error", title, hint or detail[-400:]))
        w.finished.connect(self._ping_cleanup)
        self._ai_ping_worker = w
        self.ai_test_btn.setEnabled(False)
        self.ai_test_btn.setText("테스트 중…")
        self.busy.setVisible(True)
        self.banner.hide()
        w.start()

    def _ping_cleanup(self) -> None:
        self._ai_ping_worker = None
        self.ai_test_btn.setEnabled(True)
        self.ai_test_btn.setText("연결 테스트")
        self.busy.setVisible(False)

    def _on_ping_done(self, result) -> None:
        """연결 테스트 결과 배너. 단일 모드는 기존 형식, 둘 다 모드는 엔진별 성공/실패를 나열한다 (전부 성공 success · 일부 실패 warning · 전부 실패 error)."""
        if result.cancelled:
            self.banner.show_message("info", "연결 테스트를 취소했습니다")
            return
        oks = [f"{o.label} 연결됨 ({o.answer.elapsed:.1f}초)" for o in result.succeeded]
        fails = [o for o in result.outcomes if o.answer is None]
        details = []
        for o in fails:
            f = o.failure
            hint = f.hint or ""
            if f.stderr and f.stderr not in hint:
                hint = f"{hint}\n\n{f.stderr[-ai_engine.STDERR_TAIL:]}".strip()
            details.append(f"{o.label}: {f.title}" + (f"\n{hint}" if hint else ""))
        single = len(result.outcomes) == 1
        if not fails:
            body = f"응답: {result.outcomes[0].answer.markdown[:80]}" if single else ""
            self.banner.show_message("success", " · ".join(oks), body)
        elif not oks:
            if single:
                self.banner.show_message("error", fails[0].failure.title, fails[0].failure.hint)
            else:
                self.banner.show_message("error", "두 엔진 모두 연결하지 못했습니다", "\n\n".join(details))
        else:
            self.banner.show_message("warning", " · ".join(oks + [f"{o.label} 실패" for o in fails]), "\n\n".join(details))

    def _reset_ai_consent(self) -> None:
        reset_consents(self.qs)
        self.banner.show_message("success", "AI 전송 동의를 초기화했습니다", "다음에 AI 코치를 쓸 때 다시 확인합니다")

    def _growth_toggled(self, key: str, on: bool) -> None:
        """성장 기록 / 주간 코멘트 체크박스: 저장 즉시 .env (SWEA_GROWTH, SWEA_GROWTH_COMMENT). 성장 기록이 꺼지면 코멘트 옵션은 비활성."""
        if key == "SWEA_GROWTH":
            self.growth_comment.setEnabled(on)
        if self._loading_ai:
            return
        service.set_env_values(self.config_dir, **{key: "1" if on else "0"})
        self.status_message.emit("성장 기록 설정을 저장했습니다")
        self.coach_settings_changed.emit()

    def _set_heat_color(self, value: str) -> None:
        """풀이 잔디 색 저장 (QSettings growth/heat_color) + 즉시 반영."""
        self.heat_color = solved.parse_hex(value)
        self.qs.setValue("growth/heat_color", self.heat_color)
        self._paint_heat_buttons()
        self.heat_color_changed.emit()

    def _set_theme(self, key: str) -> None:
        """테마 칩 선택: 저장하고 메인에 알린다 (QSS 재적용은 MainWindow.apply_theme)."""
        theme = tokens.get_theme(key)
        self.qs.setValue(tokens.THEME_SETTING_KEY, theme.key)
        self.theme_changed.emit(theme.key)
        self.status_message.emit(f"테마를 바꿨습니다 — {theme.label}")

    def _pick_heat_color(self) -> None:
        c = QColorDialog.getColor(QColor(self.heat_color), self, "풀이 잔디 색")
        if c.isValid():
            self._set_heat_color(c.name())

    def _paint_heat_buttons(self) -> None:
        """프리셋 버튼을 색 칩으로 칠한다. 현재 색과 같은 칩은 굵은 테두리 — 프리셋이 아니면 [직접 고르기] 앞에 그 색의 칩이 선택 상태로 나온다."""
        pal = tokens.current()
        self.heat_group.setExclusive(False)  # 프리셋이 아닌 색이면 모두 해제해야 한다 (배타 그룹은 마지막 하나를 못 끈다)
        for hexv, b in self.heat_buttons.items():
            on = hexv == self.heat_color
            b.setChecked(on)
            b.setStyleSheet(_swatch_qss(hexv, on, pal))
        self.heat_group.setExclusive(True)
        custom = self.heat_color not in self.heat_buttons
        self.heat_custom_swatch.setVisible(custom)
        if custom:
            self.heat_custom_swatch.setStyleSheet(_swatch_qss(self.heat_color, True, pal))
            self.heat_custom_swatch.setToolTip(f"직접 고른 색 {self.heat_color} — 누르면 다시 고릅니다")

    def _clear_growth(self) -> None:
        box = QMessageBox(QMessageBox.Icon.Warning, "성장 기록 지우기", "성장 리포트·분류 기록·풀이 잔디가 삭제됩니다.\nAI 응답 캐시·복습 일정과 풀이 파일은 건드리지 않습니다.", parent=self)
        delete = box.addButton("지우기", QMessageBox.ButtonRole.DestructiveRole)
        set_class(delete, "danger")
        cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() is not delete:
            return
        n = service.clear_growth(self.config_dir)
        self.banner.show_message("success", "성장 기록을 지웠습니다", f"{n}개 파일 삭제" if n else "지울 항목 없음")
        self.coach_settings_changed.emit()

    def _clear_ai_records(self) -> None:
        box = QMessageBox(QMessageBox.Icon.Warning, "AI 기록 지우기", "AI 응답 캐시·오답 횟수·복습 일정·성장 기록(분류·리포트·풀이 잔디 포함)이 모두 지워집니다.\n풀이 파일은 건드리지 않습니다.", parent=self)
        delete = box.addButton("지우기", QMessageBox.ButtonRole.DestructiveRole)
        set_class(delete, "danger")
        cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() is not delete:
            return
        n = service.clear_coach(self.config_dir)
        self.banner.show_message("success", "AI 기록을 지웠습니다", f"{n}개 파일 삭제" if n else "지울 항목 없음")
        self.coach_settings_changed.emit()

    # --- 삭제 -----------------------------------------------------------------------
    def _cache_toggled(self, on: bool) -> None:
        self.qs.setValue("problem/cache_enabled", on)
        self.cache_settings_changed.emit()

    def _clear_cache(self) -> None:
        """앱 캐시(config_dir/cache/statements)의 지문을 모두 지운다. 풀이 폴더는 건드리지 않는다."""
        n = content_cache.clear(self.config_dir / config.CACHE_DIR_NAME)
        self.banner.show_message("success", "지문 캐시를 지웠습니다", f"{n}건 삭제" if n else "지울 항목 없음")
        self.status_message.emit("지문 캐시를 지웠습니다")

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
