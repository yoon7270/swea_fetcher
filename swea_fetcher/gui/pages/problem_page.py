"""문제 페이지 (M12): 가져온 문제의 제한사항·지문을 읽는다. 지문은 파일로 저장하지 않는다 (메모리 + 앱 캐시).

- `_StatementBrowser`(QTextBrowser): 링크·외부 리소스를 열지 않는다. 이미지는 `swea-img:N` 토큰으로만 주입한다.
- 내용은 service.FetchOutcome.content 또는 content_cache.CachedStatement 에서 온다 (이미 sanitize 된 HTML).
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage, QKeySequence, QShortcut, QTextDocument
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QStackedLayout, QTextBrowser, QVBoxLayout, QWidget

from ...config import Settings
from ...content_cache import CachedStatement
from ...models import ProblemContent
from ...service import FetchOutcome
from ..theme import tokens
from ..widgets import Badge, Banner, ElidedLabel, EmptyState, editor_tooltip, open_in_editor, open_in_explorer, set_class

ZOOM_MIN, ZOOM_MAX = -3, 8
_IMG_RE = re.compile(r'<img\b[^>]*?\bsrc="(swea-img:\d+)"[^>]*>')
_RESIZE_DEBOUNCE_MS = 100
_VIEWPORT_MARGIN = 32  # 문서 여백 + 스크롤바 여유


class _StatementBrowser(QTextBrowser):
    """지문 표시 전용. 링크 열기 없음, loadResource 는 항상 None (file/http/qrc 접근 차단)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StatementBrowser")
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)
        self._content: ProblemContent | None = None
        self._qimages: dict[str, QImage] = {}
        self._failures: dict[str, str] = {}  # 토큰 → 자리표시 사유
        self._last_avail = 0
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(_RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self._rerender_if_needed)
        self.apply_palette(tokens.LIGHT)

    # 다크 팔레트 도입 시 build_qss 와 함께 다시 호출한다
    def apply_palette(self, palette: tokens.Palette) -> None:
        self.document().setDefaultStyleSheet(tokens.build_statement_css(palette))
        if self._content is not None:
            self._render()

    def loadResource(self, _type, _url):  # noqa: N802
        """이미지는 addResource 로 미리 넣어 둔다. 그 외 어떤 리소스(file/http/qrc …)도 읽지 않는다."""
        return None

    def set_statement(self, content: ProblemContent | None) -> None:
        self._content = content
        self._qimages.clear()
        self._failures.clear()
        if content is None:
            self.clear()
            return
        for token, ref in content.images.items():
            if ref.data is None:
                self._failures[token] = ref.error or "데이터 없음"
                continue
            img = QImage()
            if not img.loadFromData(ref.data) or img.isNull():
                self._failures[token] = "이미지 디코드 실패"
                continue
            self._qimages[token] = img
        self._render()
        self.verticalScrollBar().setValue(0)

    def failure_count(self) -> int:
        return len(self._failures)

    def failure_reasons(self) -> list[str]:
        return sorted(set(self._failures.values()))

    # --- 렌더링 ---------------------------------------------------------------------
    def _avail_width(self) -> int:
        return max(160, self.viewport().width() - _VIEWPORT_MARGIN)

    def _fit_images(self, htm: str, avail: int) -> str:
        """이미지에 width 를 부여(원본보다 크면 뷰포트 폭으로 축소)하고, 실패 이미지는 자리표시 텍스트로 바꾼다."""

        def sub(m: re.Match) -> str:
            token = m.group(1)
            if token in self._failures:
                return f'<span class="imgfail">[이미지 불러오기 실패: {html.escape(self._failures[token])}]</span>'
            img = self._qimages.get(token)
            if img is None:
                return ""
            w = min(img.width(), avail)
            return f'<img src="{token}" width="{w}"/>'

        return _IMG_RE.sub(sub, htm)

    def _render(self) -> None:
        c = self._content
        if c is None:
            return
        doc = self.document()
        avail = self._avail_width()
        self._last_avail = avail
        parts = []
        if c.limits_html:
            parts.append(f'<div class="limits">{c.limits_html}</div><hr/>')
        parts.append(c.body_html)
        htm = self._fit_images("".join(parts), avail)
        self.setHtml(htm)
        # setHtml 이 리소스를 비울 수 있으므로 문서 생성 뒤에 등록하고 레이아웃을 갱신한다
        for token, img in self._qimages.items():
            doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(token), img)
        if self._qimages:
            doc.markContentsDirty(0, doc.characterCount())

    def _rerender_if_needed(self) -> None:
        if self._content is None or not self._qimages or self._avail_width() == self._last_avail:
            return
        pos = self.verticalScrollBar().value()
        self._render()
        self.verticalScrollBar().setValue(pos)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self._qimages:
            self._resize_timer.start()


class ProblemPage(QWidget):
    status_message = Signal(str)
    goto_requested = Signal(str)

    def __init__(self, qsettings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.qs = qsettings
        self.settings: Settings | None = None
        self._outcome: FetchOutcome | None = None
        self._problem_dir: Path | None = None  # [폴더 열기]·[에디터에서 열기] 대상 (없으면 버튼 숨김)
        self._zoom = 0
        self._build()
        z = int(self.qs.value("problem/zoom", 0, type=int))
        self._set_zoom(max(ZOOM_MIN, min(ZOOM_MAX, z)), save=False)

    # --- UI -----------------------------------------------------------------------
    def _build(self) -> None:
        self.stack = QStackedLayout(self)
        self.empty = EmptyState("아직 가져온 문제가 없습니다", "저장 탭에서 문제를 가져오면 지문이 여기에 표시됩니다", "저장 탭으로")
        if self.empty.button:
            self.empty.button.clicked.connect(lambda: self.goto_requested.emit("fetch"))
        holder = QWidget()
        root = QVBoxLayout(holder)
        m = tokens.SPACE * 3
        root.setContentsMargins(m, m, m, m)
        root.setSpacing(tokens.SPACE * 2)

        head = QHBoxLayout()
        self.title = QLabel()
        set_class(self.title, "title")
        self.title.setWordWrap(True)
        self.badge = Badge("저장됨", "success")
        head.addWidget(self.title, 1)
        head.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)
        self.meta = ElidedLabel()
        set_class(self.meta, "hint")
        root.addWidget(self.meta)
        self.banner = Banner()
        root.addWidget(self.banner)

        bar = QHBoxLayout()
        self.open_dir_btn = QPushButton("폴더 열기")
        self.open_py_btn = QPushButton("에디터에서 열기")
        self.zoom_out_btn = QPushButton("글자 −")
        self.zoom_in_btn = QPushButton("글자 +")
        self.zoom_out_btn.setToolTip("글자 작게 (Ctrl+−)")
        self.zoom_in_btn.setToolTip("글자 크게 (Ctrl++)")
        bar.addWidget(self.open_dir_btn)
        bar.addWidget(self.open_py_btn)
        bar.addStretch(1)
        bar.addWidget(self.zoom_out_btn)
        bar.addWidget(self.zoom_in_btn)
        root.addLayout(bar)

        card = QFrame()
        set_class(card, "card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        self.browser = _StatementBrowser()
        self.browser.setFrameShape(QFrame.Shape.NoFrame)
        self.browser.setAccessibleName("문제 지문")
        cl.addWidget(self.browser)
        root.addWidget(card, 1)  # 스크롤은 브라우저 자체 (이중 스크롤 방지)

        self.footer = QLabel()
        set_class(self.footer, "hint")
        self.footer.setWordWrap(True)
        root.addWidget(self.footer)

        self.stack.addWidget(self.empty)
        self.stack.addWidget(holder)
        self.stack.setCurrentIndex(0)

        self.open_dir_btn.clicked.connect(self._open_dir)
        self.open_py_btn.clicked.connect(self._open_py)
        self.zoom_out_btn.clicked.connect(lambda: self._set_zoom(self._zoom - 1))
        self.zoom_in_btn.clicked.connect(lambda: self._set_zoom(self._zoom + 1))
        for seq in ("Ctrl++", "Ctrl+="):
            QShortcut(QKeySequence(seq), self, activated=lambda: self._set_zoom(self._zoom + 1))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self._set_zoom(self._zoom - 1))
        self.banner.action_clicked.connect(lambda key: self.goto_requested.emit("fetch") if key == "fetch" else None)
        self._refresh_footer()

    # --- 상태 -----------------------------------------------------------------------
    def set_settings(self, settings: Settings | None) -> None:
        self.settings = settings
        self.open_py_btn.setToolTip(editor_tooltip(settings.editor if settings else "auto"))

    def has_content(self) -> bool:
        return self.stack.currentIndex() == 1

    def refresh_footer(self) -> None:
        self._refresh_footer()

    def _refresh_footer(self) -> None:
        cache_on = bool(self.qs.value("problem/cache_enabled", True, type=bool))
        text = "지문은 파일로 저장되지 않습니다"
        if cache_on:
            text += " (앱 캐시 사용 시 ~/.swea-fetch/cache 에 보관되며 설정에서 끄거나 지울 수 있습니다)"
        self.footer.setText(text)

    def _set_zoom(self, value: int, save: bool = True) -> None:
        value = max(ZOOM_MIN, min(ZOOM_MAX, value))
        delta = value - self._zoom
        if delta > 0:
            self.browser.zoomIn(delta)
        elif delta < 0:
            self.browser.zoomOut(-delta)
        self._zoom = value
        if save:
            self.qs.setValue("problem/zoom", value)
        self.zoom_out_btn.setEnabled(value > ZOOM_MIN)
        self.zoom_in_btn.setEnabled(value < ZOOM_MAX)

    # --- 표시 -----------------------------------------------------------------------
    def show_outcome(self, outcome: FetchOutcome) -> None:
        """fetch 결과 표시. 저장됨(result) / 미리보기(preview) 를 배지로 구분한다."""
        self._outcome = outcome
        info = outcome.info
        saved = outcome.result is not None
        self.badge.set_state("저장됨" if saved else "미리보기 — 저장 안 됨", "success" if saved else "idle")
        where = str(outcome.result.problem_dir) if saved else str((outcome.preview or {}).get("problem_dir", ""))
        self._show(f"{info.num}. {info.title}", outcome.topic, where, outcome.content)
        self._set_problem_dir(outcome.result.problem_dir if saved else None)

    def show_cached(self, cached: CachedStatement, problem_dir: Path | None = None, badge: str = "캐시") -> None:
        """캐시(또는 최근 탭에서 방금 가져온) 지문 표시. problem_dir 가 있으면 폴더/에디터 열기를 켠다."""
        self._outcome = None
        self.badge.set_state(badge, "idle")
        where = str(problem_dir) if problem_dir is not None else f"캐시 · {cached.fetched_at}"
        self._show(f"{cached.num}. {cached.title}", cached.topic, where, cached.content)
        self._set_problem_dir(problem_dir)

    def _set_problem_dir(self, d: Path | None) -> None:
        self._problem_dir = d if d is not None and d.is_dir() else None
        self.open_dir_btn.setVisible(self._problem_dir is not None)
        self.open_py_btn.setVisible(self._problem_dir is not None and (self._problem_dir / f"{self._problem_dir.name}.py").exists())

    def _show(self, title: str, topic: str, where: str, content: ProblemContent | None) -> None:
        self.title.setText(title)
        self.meta.setText(" · ".join(x for x in (topic, where) if x))
        self.banner.hide()
        self.browser.set_statement(content)
        if content is None:
            self.banner.show_message("warning", "지문 영역을 찾지 못했습니다", "사이트 구조가 바뀌었을 수 있습니다. 저장 결과에는 영향이 없습니다", [("fetch", "저장 탭으로")])
        elif self.browser.failure_count():
            n = self.browser.failure_count()
            self.banner.show_message("info", f"이미지 {n}개를 불러오지 못했습니다", " · ".join(self.browser.failure_reasons()))
        self._refresh_footer()
        self.stack.setCurrentIndex(1)

    def focus_browser(self) -> None:
        self.browser.setFocus()

    # --- 동작 -----------------------------------------------------------------------
    def _open_dir(self) -> None:
        if self._problem_dir is not None and open_in_explorer(self._problem_dir):
            self.status_message.emit("폴더를 열었습니다")

    def _open_py(self) -> None:
        d = self._problem_dir
        if d is not None:
            py = d / f"{d.name}.py"
            if py.exists():
                res = open_in_editor(d, py, self.settings.editor if self.settings else "auto")
                if res.ok:
                    self.status_message.emit(res.note or f"{py.name} 을 열었습니다")
