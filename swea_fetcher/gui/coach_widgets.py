"""AI 코치 위젯 (M17, 스펙 §6.6): CoachBar(제출 결과 뒤 제안 줄), CoachTab(AI 응답 탭), AnswerBrowser, 동의 다이얼로그.

- AnswerBrowser: 응답은 Markdown → QTextDocument.setMarkdown. 링크·외부 리소스는 열지도 읽지도 않는다 (M12 _StatementBrowser 와 같은 가드).
- 동의는 엔진(벤더)별 1회, QSettings `coach/consent/{engine}`. 코어(service)는 동의를 모른다 — 게이트는 이 계층 책임.
"""

from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QStackedLayout, QTextBrowser, QVBoxLayout, QWidget

from ..ai_engine import AI_TIMEOUT
from ..ai_prompts import MAX_HINT_LEVEL
from ..service import CoachAnswer
from .theme import tokens
from .widgets import Badge, svg_icon, set_class

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


def consent_text(engine_label: str, ping: bool = False) -> str:
    if ping:
        return f"{engine_label}(이 PC 에 설치된 CLI)로 테스트 문장(`OK` 라고만 답하세요)만 보냅니다. 코드·지문은 보내지 않습니다."
    return (
        f"{engine_label}(이 PC 에 설치된 CLI)으로 다음을 보냅니다.\n"
        "· 문제 번호·제목·지문 텍스트 (그림은 제외)\n"
        "· 샘플 입출력 앞부분\n"
        "· 제출한 풀이 코드 ({num}.py)\n"
        "· SWEA 채점 결과 요약\n"
        "SWEA 아이디·비밀번호·세션과 폴더 경로는 보내지 않습니다.\n"
        "전송은 버튼을 누를 때 요청 1건씩만 이루어지며, 내용은 해당 서비스의 약관에 따라 처리됩니다 (CLI 가 자체 기록을 남길 수 있음). "
        "지문은 SWEA 의 저작물이므로 개인 학습 용도로만 쓰세요."
    )


def ask_consent(parent: QWidget | None, engine_label: str, ping: bool = False) -> bool:
    """동의 다이얼로그. 기본 포커스·Esc 는 [취소]. 동의하면 True (저장은 호출자가 set_consent)."""
    box = QMessageBox(QMessageBox.Icon.Question, "AI 에게 코드를 보냅니다", consent_text(engine_label, ping), parent=parent)
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
        self.review_btn.clicked.connect(self.review_clicked)
        self.hint_btn.clicked.connect(self.hint_clicked)
        self.solution_btn.clicked.connect(self.solution_clicked)
        self.later_btn.clicked.connect(self.later_clicked)
        self.hide()

    # --- 상태 ---
    def show_pass(self) -> None:
        self.text.setText("Pass! 풀이를 AI 에게 평가받을 수 있어요")
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
        self.text.setText(text)
        self._hint_done = max(0, min(MAX_HINT_LEVEL, hint_done))
        self._set_visible(hint=True, solution=wrong_count >= threshold, later=offer)  # 기준 미만이면 정답 풀이 버튼 숨김
        self._show()

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
        self.hint_btn.setToolTip("이 코드에 대한 힌트를 받습니다 (정답 코드는 보여주지 않아요)")
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


class CoachTab(QWidget):
    """검증 탭의 결과 탭 "AI 코치": 로딩(경과 시간 + [취소]) ↔ 응답(헤더·본문·푸터·[다시 받기]·[코드 복사])."""

    cancel_clicked = Signal()
    retry_clicked = Signal()
    copy_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CoachTab")
        self.stack = QStackedLayout(self)
        # 로딩
        loading = QWidget()
        ll = QVBoxLayout(loading)
        ll.setContentsMargins(tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2, tokens.SPACE * 2)
        self.loading_label = QLabel()
        set_class(self.loading_label, "muted")
        self.loading_label.setWordWrap(True)
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setToolTip("AI 요청을 중단합니다")
        ll.addWidget(self.loading_label)
        ll.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignLeft)
        ll.addStretch(1)
        # 응답
        answer = QWidget()
        al = QVBoxLayout(answer)
        al.setContentsMargins(0, tokens.SPACE, 0, 0)
        al.setSpacing(tokens.SPACE)
        head = QHBoxLayout()
        self.header = QLabel()
        set_class(self.header, "muted")
        self.cache_badge = Badge("캐시", "idle")
        self.cache_badge.hide()
        self.retry_btn = QPushButton("다시 받기")
        self.retry_btn.setToolTip("캐시를 쓰지 않고 AI 에게 다시 묻습니다 (힌트는 마지막 단계만)")
        self.copy_btn = QPushButton("코드 복사")
        self.copy_btn.setToolTip("정답 코드를 클립보드로 복사합니다 (파일로 저장하지 않습니다)")
        self.copy_btn.hide()
        head.addWidget(self.header)
        head.addWidget(self.cache_badge)
        head.addStretch(1)
        head.addWidget(self.copy_btn)
        head.addWidget(self.retry_btn)
        al.addLayout(head)
        self.info = QLabel()  # notes + 복습 예정
        set_class(self.info, "hint")
        self.info.setWordWrap(True)
        self.info.hide()
        al.addWidget(self.info)
        self.browser = AnswerBrowser()
        self.browser.setAccessibleName("AI 코치 응답")
        al.addWidget(self.browser, 1)
        self.footer = QLabel()
        set_class(self.footer, "hint")
        self.footer.setWordWrap(True)
        al.addWidget(self.footer)
        self.stack.addWidget(loading)
        self.stack.addWidget(answer)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._t0 = 0.0
        self._engine = ""
        self.cancel_btn.clicked.connect(self.cancel_clicked)
        self.retry_btn.clicked.connect(self.retry_clicked)
        self.copy_btn.clicked.connect(self.copy_clicked)

    def show_loading(self, engine_label: str) -> None:
        self._engine = engine_label
        self._t0 = time.monotonic()
        self.cancel_btn.setEnabled(True)
        self._tick()
        self._timer.start()
        self.stack.setCurrentIndex(0)

    def _tick(self) -> None:
        secs = int(time.monotonic() - self._t0)
        self.loading_label.setText(f"{self._engine} 에게 묻는 중… {secs // 60}:{secs % 60:02d} · 최대 {int(AI_TIMEOUT) // 60}분")

    def stop(self) -> None:
        self._timer.stop()

    def show_answer(self, answer: CoachAnswer, num: int) -> None:
        self.stop()
        when = datetime.now().strftime("%H:%M")
        self.header.setText(f"{KIND_TITLES.get(answer.kind, answer.kind)} · {answer.engine} · {when}")
        self.cache_badge.setVisible(answer.from_cache)
        self.browser.set_markdown(answer.markdown)
        lines = list(answer.notes)
        if answer.review_due is not None:
            lines.append(f"복습 예정: {answer.review_due.isoformat()}")
        self.info.setText(" · ".join(lines))
        self.info.setVisible(bool(lines))
        self.copy_btn.setVisible(answer.kind == "solution" and bool(answer.code))
        self.retry_btn.setEnabled(True)
        self.footer.setText("AI 응답은 틀릴 수 있습니다." + (f" 정답 풀이는 {num}.py 에 저장되지 않습니다." if answer.kind == "solution" else ""))
        self.stack.setCurrentIndex(1)

    def set_busy(self, busy: bool) -> None:
        """요청 중에는 [다시 받기] 비활성 (동시 요청 방지)."""
        self.retry_btn.setEnabled(not busy)
