"""AI 코치 위젯 (M17, 스펙 §6.6): CoachBar(제출 결과 뒤 제안 줄), CoachTab(AI 응답 탭, M18 엔진별 EnginePane 좌우 분할), AnswerBrowser, 동의 다이얼로그.

- AnswerBrowser: 응답은 Markdown → QTextDocument.setMarkdown. 링크·외부 리소스는 열지도 읽지도 않는다 (M12 _StatementBrowser 와 같은 가드).
- 동의는 엔진(벤더)별 1회, QSettings `coach/consent/{engine}`. 코어(service)는 동의를 모른다 — 게이트는 이 계층 책임.
"""

from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSplitter, QStackedLayout, QTextBrowser, QVBoxLayout, QWidget,
)

from ..ai_engine import AI_TIMEOUT, ENGINE_LABELS, ENGINE_SHORT, install_hint
from ..ai_prompts import MAX_HINT_LEVEL
from ..service import CoachAnswer
from .theme import tokens
from .widgets import Badge, ElidedLabel, svg_icon, set_class

KIND_TITLES = {"review": "코드 평가", "hint": "힌트", "solution": "정답 풀이", "ping": "연결 테스트"}
CONSENT_PREFIX = "coach/consent/"
ENGINE_KEYS = ("codex", "claude")

# --- 동의 (D3) ---------------------------------------------------------------------------


def has_consent(qs: QSettings, engine: str) -> bool:
    return bool(qs.value(f"{CONSENT_PREFIX}{engine}", False, type=bool))


def set_consent(qs: QSettings, engine: str, on: bool = True) -> None:
    qs.setValue(f"{CONSENT_PREFIX}{engine}", on)


def reset_consents(qs: QSettings) -> None:
    for key in ENGINE_KEYS:
        qs.remove(f"{CONSENT_PREFIX}{key}")


DUAL_NOTE = "GPT 와 Claude 에 각각 1번씩 요청하고 답 2개를 나란히 보여줍니다 (각 서비스에서 쓰는 양은 한 곳만 쓸 때와 같습니다)."


def consent_text(engine_label: str | list[str], ping: bool = False, dual: bool = False) -> str:
    """engine_label: 동의가 필요한 엔진 표시 이름 (여러 개면 한 다이얼로그에 모은다). dual: 이번 요청이 두 서비스 동시 요청이면 "각각 1번씩 요청" 고지 추가."""
    names = engine_label if isinstance(engine_label, str) else ", ".join(engine_label)
    note = f"\n{DUAL_NOTE}" if dual else ""
    if ping:
        return f"{names}(이 PC 에 설치된 CLI)로 테스트 문장(`OK` 라고만 답하세요)만 보냅니다. 코드·지문은 보내지 않습니다.{note}"
    return (
        f"{names}(이 PC 에 설치된 CLI)로 다음을 보냅니다.\n"
        "· 문제 번호·제목·지문 텍스트 (그림은 제외)\n"
        "· 샘플 입출력 앞부분\n"
        "· 제출한 풀이 코드 ({num}.py)\n"
        "· SWEA 채점 결과 요약\n"
        "SWEA 아이디·비밀번호·세션과 폴더 경로는 보내지 않습니다.\n"
        "전송은 버튼을 누를 때 요청 1건씩만 이루어지며, 내용은 해당 서비스의 약관에 따라 처리됩니다 (CLI 가 자체 기록을 남길 수 있음). "
        "지문은 SWEA 의 저작물이므로 개인 학습 용도로만 쓰세요."
        f"{note}"
    )


def ask_consent(parent: QWidget | None, engine_label: str | list[str], ping: bool = False, dual: bool = False) -> bool:
    """동의 다이얼로그 (엔진 여러 개를 한 번에). 기본 포커스·Esc 는 [취소]. 동의하면 True (저장은 호출자가 set_consent)."""
    box = QMessageBox(QMessageBox.Icon.Question, "AI 에게 코드를 보냅니다", consent_text(engine_label, ping, dual), parent=parent)
    ok = box.addButton("동의하고 보내기", QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is ok


# --- 코치 바 (§6.6) ------------------------------------------------------------------------


class CoachBar(QFrame):
    """제출/검증 결과 직후 표시되는 제안 줄. 문장 + 버튼 (secondary). 요청 중에는 모든 버튼 비활성."""

    review_clicked = Signal()
    hint_clicked = Signal()
    solution_clicked = Signal()
    later_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        set_class(self, "card")
        self.setObjectName("CoachBar")
        lay = QVBoxLayout(self)
        m = tokens.SPACE * 2
        lay.setContentsMargins(m, tokens.SPACE * 3 // 2, m, tokens.SPACE * 3 // 2)
        lay.setSpacing(tokens.SPACE)
        self.text = QLabel()
        set_class(self.text, "muted")
        self.text.setWordWrap(True)
        lay.addWidget(self.text)
        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE)
        self.review_btn = QPushButton("코드 평가 받기")
        self.review_btn.setToolTip("풀이 코드를 AI 에게 보내 복잡도·가독성 평가를 받습니다")
        self.hint_btn = QPushButton("힌트")
        self.hint_btn.setIcon(svg_icon("coach-hint", None, 16))
        self.hint_btn.setToolTip("이 코드에 대한 힌트를 받습니다 (정답 코드는 보여주지 않아요)")
        self.hint_btn.setAccessibleName("힌트 받기")
        self.solution_btn = QPushButton("정답 풀이 보기")
        self.solution_btn.setToolTip("설명과 정답 코드를 화면에 표시합니다 (파일로 저장하지 않습니다)")
        self.later_btn = QPushButton("다음에")
        set_class(self.later_btn, "link")
        self._buttons = (self.review_btn, self.hint_btn, self.solution_btn, self.later_btn)
        for b in self._buttons:
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self._requesting = False
        self._hint_done = 0
        self._base_text = ""
        self._dual: list[str] | None = None  # 동시 요청 대상의 짧은 이름 (둘 다 모드)
        self._base_tips = (self.review_btn.toolTip(), self.solution_btn.toolTip())
        self.review_btn.clicked.connect(self.review_clicked)
        self.hint_btn.clicked.connect(self.hint_clicked)
        self.solution_btn.clicked.connect(self.solution_clicked)
        self.later_btn.clicked.connect(self.later_clicked)
        self.hide()

    # --- 상태 ---
    def show_pass(self) -> None:
        self._set_text("Pass! 풀이를 AI 에게 평가받을 수 있어요")
        self._set_visible(review=True)
        self._show()

    def show_wrong(
        self,
        wrong_count: int,
        threshold: int,
        review_days: int,
        offer_dismissed: bool,
        hint_done: int = 0,
        local: bool = False,
        solution_viewed: bool = False,
    ) -> None:
        """오답(또는 로컬 검증 실패, local=True) 뒤. wrong_count 는 SWEA 채점 오답 누적."""
        offer = wrong_count >= threshold and not offer_dismissed
        if offer:
            text = f"이 문제를 {wrong_count}번 틀렸어요. 정답 풀이(설명 + 코드)를 볼까요? 보면 {review_days}일 뒤 다시 풀기를 권해드려요."
        elif local:
            text = "로컬 검증에 실패했어요" + (f" (SWEA 오답 {wrong_count}회)" if wrong_count else "")
        elif wrong_count == 0 and solution_viewed:  # 정답 풀이를 본 직후 (누적 리셋)
            text = "정답 풀이를 확인했어요. 고쳐서 다시 제출해 보세요"
        elif wrong_count == 0:  # 기록이 없거나 저장에 실패한 경우 — 풀이를 봤다고 단정하지 않는다
            text = "오답이에요. 힌트를 받아 보세요"
        else:
            text = f"이 문제 오답 {wrong_count}회"
        self._set_text(text)
        self._hint_done = max(0, min(MAX_HINT_LEVEL, hint_done))
        self._set_visible(hint=True, solution=wrong_count >= threshold, later=offer)  # 기준 미만이면 정답 풀이 버튼 숨김
        self._show()

    def _set_text(self, text: str) -> None:
        self._base_text = text
        self._render_dual()

    def set_dual(self, labels: list[str] | None) -> None:
        """대상 엔진이 2개면 (둘 다 모드) 안내 문장과 버튼 툴팁에 "각각 1번씩 요청" 고지를 붙인다. None 이면 제거."""
        self._dual = list(labels) if labels and len(labels) >= 2 else None
        self._render_dual()
        self._refresh_hint_button()

    def _dual_tip(self) -> str:
        return "\n" + DUAL_NOTE.replace("답이 2개 표시됩니다", "두 서비스에 동시에 요청합니다") if self._dual else ""

    def _render_dual(self) -> None:
        suffix = f" · {' · '.join(self._dual)} 에 각각 1번씩 요청" if self._dual else ""
        self.text.setText(self._base_text + suffix)
        self.review_btn.setToolTip(self._base_tips[0] + self._dual_tip())
        self.solution_btn.setToolTip(self._base_tips[1] + self._dual_tip())

    def set_hint_done(self, done: int) -> None:
        self._hint_done = max(0, min(MAX_HINT_LEVEL, done))
        self._refresh_hint_button()

    def set_requesting(self, on: bool) -> None:
        self._requesting = on
        for b in self._buttons:
            b.setEnabled(not on)
        if not on:
            self._refresh_hint_button()

    def _set_visible(self, review: bool = False, hint: bool = False, solution: bool = False, later: bool = False) -> None:
        self.review_btn.setVisible(review)
        self.hint_btn.setVisible(hint)
        self.solution_btn.setVisible(solution)
        self.later_btn.setVisible(later)
        self._refresh_hint_button()

    def _refresh_hint_button(self) -> None:
        done = self._hint_done
        if done >= MAX_HINT_LEVEL:
            self.hint_btn.setText(f"힌트 ({MAX_HINT_LEVEL}/{MAX_HINT_LEVEL})")
            self.hint_btn.setEnabled(False)
            self.hint_btn.setToolTip("힌트는 3단계까지입니다. 3단계를 다시 받으려면 AI 코치 탭의 [다시 받기]")
            return
        self.hint_btn.setText("힌트" if done == 0 else f"다음 힌트 ({done + 1}/{MAX_HINT_LEVEL})")
        self.hint_btn.setToolTip("이 코드에 대한 힌트를 받습니다 (정답 코드는 보여주지 않아요)" + self._dual_tip())
        self.hint_btn.setEnabled(not self._requesting)

    def _show(self) -> None:
        for b in self._buttons:
            if b is not self.hint_btn:
                b.setEnabled(not self._requesting)
        self.show()


# --- 응답 표시 ----------------------------------------------------------------------------


class AnswerBrowser(QTextBrowser):
    """AI 응답(Markdown) 표시 전용. 링크 열기 없음, loadResource 는 항상 None (file/http/qrc 접근 차단)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AnswerBrowser")
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)
        self.document().setDefaultStyleSheet(tokens.build_statement_css(tokens.LIGHT))

    def loadResource(self, _type, _url):  # noqa: N802
        return None

    def set_markdown(self, text: str) -> None:
        """MarkdownNoHTML: 응답 안의 raw HTML(<img>·<br> 등)을 해석하지 않고 글자로 보인다.
        (기본 모드는 raw HTML 태그 뒤의 본문을 통째로 버리는 것을 실측 — 내용 유실 방지 겸 렌더링 차단)"""
        feats = QTextDocument.MarkdownFeature.MarkdownDialectGitHub | QTextDocument.MarkdownFeature.MarkdownNoHTML
        self.document().setMarkdown(text, feats)
        # 새 답은 항상 맨 위(총평)부터. 패널이 보이며 폭이 바뀌면 재배치 뒤 커서 쪽으로 밀리므로 커서도 처음으로, 한 번 더 늦게 올린다
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(0))


class EnginePane(QFrame):
    """엔진 1개의 답 패널 (M18, 스펙 §6.6): 헤더(엔진명·시간·캐시·[다시 받기]) + 상태별 본문 + 패널 푸터(notes·[코드 복사]).

    상태: loading | done | error | missing | cancelled. 색만으로 구분하지 않고 글자를 병기한다.
    """

    retry_clicked = Signal(str, bool)  # 엔진 키, force_new (done 의 [다시 받기]=True, error 의 [다시 시도]=False)
    copy_clicked = Signal(str)
    settings_requested = Signal()

    def __init__(self, key: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.label = ENGINE_LABELS[key]
        self.short = ENGINE_SHORT[key]
        self.state = ""
        self._t0 = 0.0
        self._busy = False
        set_class(self, "card")
        self.setObjectName(f"CoachPane_{key}")
        self.setMinimumHeight(140)  # 위아래 배치에서도 본문이 읽히도록
        lay = QVBoxLayout(self)
        m = tokens.SPACE * 3 // 2
        lay.setContentsMargins(m, m, m, m)
        lay.setSpacing(tokens.SPACE)
        head = QHBoxLayout()
        head.setSpacing(tokens.SPACE)
        self.title = QLabel(self.label)
        self.title.setObjectName("CoachPaneTitle")
        set_class(self.title, "section")
        self.meta = ElidedLabel()  # 좁은 좌우 배치에서 가로 스크롤을 만들지 않게 줄여 쓴다 (툴팁 = 전문)
        set_class(self.meta, "muted")
        self.cache_badge = Badge("캐시", "idle")
        self.cache_badge.hide()
        self.retry_btn = QPushButton("다시 받기")
        self.retry_btn.setObjectName("CoachPaneRetry")
        self.retry_btn.setAccessibleName(f"{self.short} 다시 받기")
        head.addWidget(self.title)
        head.addWidget(self.meta, 1)
        head.addWidget(self.cache_badge)
        head.addWidget(self.retry_btn)
        lay.addLayout(head)
        # 본문 스택: 0 로딩 · 1 답 · 2 오류 · 3 미설치 · 4 취소
        self.body = QWidget()
        self.body.setObjectName("CoachPaneBody")
        self.stack = QStackedLayout(self.body)
        self.loading_label = QLabel()
        set_class(self.loading_label, "muted")
        self.loading_label.setWordWrap(True)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.browser = AnswerBrowser()
        self.browser.setAccessibleName(f"{self.label} 답변")
        err = QWidget()
        el = QVBoxLayout(err)
        el.setContentsMargins(0, 0, 0, 0)
        self.error_title = QLabel()
        set_class(self.error_title, "error")
        self.error_hint = QLabel()  # hint + stderr 끝부분: 선택·복사 가능
        set_class(self.error_hint, "muted")
        for w in (self.error_title, self.error_hint):
            w.setWordWrap(True)
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            el.addWidget(w)
        el.addStretch(1)
        miss = QWidget()
        ml = QVBoxLayout(miss)
        ml.setContentsMargins(0, 0, 0, 0)
        self.missing_title = QLabel()
        set_class(self.missing_title, "error")
        self.missing_hint = QLabel()
        set_class(self.missing_hint, "muted")
        for w in (self.missing_title, self.missing_hint):
            w.setWordWrap(True)
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            ml.addWidget(w)
        self.settings_btn = QPushButton("설정으로 이동")
        ml.addWidget(self.settings_btn, 0, Qt.AlignmentFlag.AlignLeft)
        ml.addStretch(1)
        self.cancelled_label = QLabel("취소했습니다")
        set_class(self.cancelled_label, "muted")
        self.cancelled_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        for w in (self.loading_label, self.browser, err, miss, self.cancelled_label):
            self.stack.addWidget(w)
        lay.addWidget(self.body, 1)
        foot = QHBoxLayout()
        self.notes = QLabel()
        set_class(self.notes, "hint")
        self.notes.setWordWrap(True)
        self.notes.hide()
        self.copy_btn = QPushButton("코드 복사")
        self.copy_btn.setToolTip("정답 코드를 클립보드로 복사합니다 (파일로 저장하지 않습니다)")
        self.copy_btn.setAccessibleName(f"{self.short} 코드 복사")
        self.copy_btn.hide()
        foot.addWidget(self.notes, 1)
        foot.addWidget(self.copy_btn)
        lay.addLayout(foot)
        self.retry_btn.clicked.connect(lambda: self.retry_clicked.emit(self.key, self.state != "error"))
        self.copy_btn.clicked.connect(lambda: self.copy_clicked.emit(self.key))
        self.settings_btn.clicked.connect(self.settings_requested)
        self.settings_btn.setAccessibleName(f"{self.short} 설치 안내: 설정으로 이동")
        self.retry_btn.setEnabled(False)

    def _enter(self, state: str, index: int) -> None:
        self.state = state
        self.stack.setCurrentIndex(index)
        self.cache_badge.hide()
        self.notes.hide()
        self.copy_btn.hide()
        self.retry_btn.setText("다시 시도" if state == "error" else "다시 받기")
        self.retry_btn.setVisible(state != "missing")
        self.retry_btn.setEnabled(not self._busy and state in ("done", "error", "cancelled"))

    def set_loading(self, kind_title: str = "") -> None:
        self._t0 = time.monotonic()
        self.meta.setText(kind_title)
        self._enter("loading", 0)
        self.tick()

    def tick(self) -> None:
        if self.state == "loading":
            secs = int(time.monotonic() - self._t0)
            self.loading_label.setText(f"{self.label} 에게 묻는 중… {secs // 60}:{secs % 60:02d} · 최대 {int(AI_TIMEOUT) // 60}분")

    def set_done(self, answer: CoachAnswer, kind_title: str) -> None:
        when = datetime.now().strftime("%H:%M")
        took = "" if answer.from_cache or not answer.elapsed else f" · {answer.elapsed:.1f}초"
        self.meta.setText(f"{kind_title} · {when}{took}")
        self.browser.set_markdown(answer.markdown)
        self._enter("done", 1)
        self.cache_badge.setVisible(answer.from_cache)
        self.notes.setText(" · ".join(answer.notes))
        self.notes.setVisible(bool(answer.notes))
        self.copy_btn.setVisible(answer.kind == "solution" and bool(answer.code))

    def set_error(self, failure) -> None:
        """failure: service.CoachFailure. 제목 앞에 "오류" 를 글자로 병기한다 (색 단독 전달 금지)."""
        self.error_title.setText(f"오류 · {failure.title}")
        tail = f"\n\n{failure.stderr}" if failure.stderr and failure.stderr not in (failure.hint or "") else ""
        self.error_hint.setText(f"{failure.hint}{tail}".strip())
        self.error_hint.setVisible(bool(self.error_hint.text()))
        self._enter("error", 2)

    def set_missing(self, failure=None) -> None:
        self.missing_title.setText(f"오류 · {self.label} 를 찾지 못했습니다")
        self.missing_hint.setText(failure.hint if failure else install_hint((self.key,)))
        self._enter("missing", 3)

    def set_cancelled(self) -> None:
        self._enter("cancelled", 4)

    def set_busy(self, busy: bool) -> None:
        """요청 중에는 [다시 받기] 비활성 (한 번에 요청 1건 — 프로세스는 최대 2개)."""
        self._busy = busy
        self.retry_btn.setEnabled(not busy and self.state in ("done", "error", "cancelled"))


class CoachTab(QWidget):
    """검증 탭의 결과 탭 "AI 코치" (M18): 엔진별 EnginePane 을 QSplitter 로 나란히 (좁으면 위아래).

    단일 모드는 패널 1개가 전폭. 패널은 먼저 끝난 순서대로 채워진다 (apply_outcome).
    """

    cancel_clicked = Signal()
    retry_clicked = Signal(str, bool)  # 엔진 키, force_new
    copy_clicked = Signal(str)
    settings_requested = Signal()

    NARROW_WIDTH = 560  # 이 폭 미만이면 위아래 배치 (기본 창 880px 에서도 좌우 — 위아래는 답이 두세 줄밖에 안 보임)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CoachTab")
        self._kind = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, tokens.SPACE, 0, 0)
        lay.setSpacing(tokens.SPACE)
        top = QHBoxLayout()
        self.title = QLabel()
        set_class(self.title, "muted")
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setToolTip("AI 요청을 중단합니다 (이미 도착한 답은 남습니다)")
        self.cancel_btn.hide()
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(self.cancel_btn)
        lay.addLayout(top)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.panes: dict[str, EnginePane] = {}
        for key in ENGINE_KEYS:
            pane = EnginePane(key)
            pane.hide()
            pane.retry_clicked.connect(self.retry_clicked)
            pane.copy_clicked.connect(self.copy_clicked)
            pane.settings_requested.connect(self.settings_requested)
            self.panes[key] = pane
            self.splitter.addWidget(pane)
        scroll = QScrollArea()  # 720x480 처럼 좁고 낮은 창에서 위아래 배치가 잘리지 않게 바깥 스크롤 허용
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.splitter)
        lay.addWidget(scroll, 1)
        self.info = QLabel()  # 복습 예정
        set_class(self.info, "hint")
        self.info.setWordWrap(True)
        self.info.hide()
        lay.addWidget(self.info)
        self.footer = QLabel()
        set_class(self.footer, "hint")
        self.footer.setWordWrap(True)
        lay.addWidget(self.footer)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self.cancel_btn.clicked.connect(self.cancel_clicked)
        self._update_orientation()

    # --- 배치 ---
    def _update_orientation(self) -> None:
        want = Qt.Orientation.Horizontal if self.width() >= self.NARROW_WIDTH else Qt.Orientation.Vertical
        if self.splitter.orientation() != want:
            self.splitter.setOrientation(want)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_orientation()

    # --- 요청 흐름 ---
    def pane(self, key: str) -> EnginePane:
        return self.panes[key]

    def visible_keys(self) -> list[str]:
        return [k for k in ENGINE_KEYS if not self.panes[k].isHidden()]

    def begin(self, engines, missing=(), only: str | None = None, kind: str = "", num: int = 0) -> None:
        """새 요청 시작. 전체 요청이면 대상(설치+미설치) 패널만 남기고 초기화, only 면 그 패널만 로딩(다른 패널은 유지)."""
        self._kind = kind
        title = KIND_TITLES.get(kind, kind)
        self.title.setText(title)
        run = [e.name for e in engines]
        if only is None:
            for key in ENGINE_KEYS:
                pane = self.panes[key]
                pane.setVisible(key in run or key in missing)
                pane.state = ""
                if key in missing:
                    pane.set_missing()
                elif key in run:
                    pane.set_loading(title)
            self.info.hide()
            self.footer.setText("AI 응답은 틀릴 수 있습니다." + (f" 정답 풀이는 {num}.py 에 저장되지 않습니다." if kind == "solution" else ""))
        elif only in run:
            self.panes[only].setVisible(True)
            self.panes[only].set_loading(title)
        self._sync_timer()

    def _sync_timer(self) -> None:
        loading = any(p.state == "loading" for p in self.panes.values())
        self.cancel_btn.setVisible(loading)
        if loading:
            self.cancel_btn.setEnabled(True)
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        for p in self.panes.values():
            p.tick()

    def stop(self) -> None:
        self._timer.stop()
        self.cancel_btn.hide()

    def apply_outcome(self, outcome, num: int = 0) -> None:
        """엔진 하나의 결과를 해당 패널에 반영한다 (먼저 끝난 쪽부터)."""
        pane = self.panes.get(outcome.engine)
        if pane is None:
            return
        pane.setVisible(True)
        if outcome.cancelled:
            pane.set_cancelled()
        elif outcome.answer is not None:
            pane.set_done(outcome.answer, KIND_TITLES.get(outcome.answer.kind, outcome.answer.kind))
        elif outcome.failure is not None and outcome.failure.code == "missing":
            pane.set_missing(outcome.failure)
        elif outcome.failure is not None:
            pane.set_error(outcome.failure)
        pane.set_busy(pane._busy)
        self._sync_timer()

    def show_review_due(self, due) -> None:
        self.info.setText(f"복습 예정: {due.isoformat()}" if due is not None else "")
        self.info.setVisible(due is not None)

    def has_answers(self) -> bool:
        return any(p.state == "done" for p in self.panes.values())

    def cancel_loading(self) -> None:
        """요청이 취소로 끝났을 때: 아직 로딩 중이던 패널만 "취소했습니다" (이미 표시된 답은 유지)."""
        for p in self.panes.values():
            if p.state == "loading":
                p.set_cancelled()
        self.stop()

    def fail_loading(self, failure) -> None:
        """요청 전체가 시작하지 못했을 때 (개별 재요청 중): 로딩 패널에 오류를 인라인으로 표시."""
        for p in self.panes.values():
            if p.state == "loading":
                p.set_error(failure)
        self.stop()

    def set_busy(self, busy: bool) -> None:
        """요청 중에는 모든 패널의 [다시 받기] 비활성 (동시 요청 방지)."""
        for p in self.panes.values():
            p.set_busy(busy)
