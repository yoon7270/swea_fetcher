"""성장 탭 위젯 (M19, 스펙 §6.7): BarChart · SparkLine (QPainter, 외부 차트 라이브러리 없음), 지표 행 · 카테고리 행. 풀이 잔디 HeatmapWidget · HeatLegend (M20, 스펙 §6.8).

- 색은 tokens.current() 만 참조한다 (하드코딩 금지). 색으로만 의미를 전달하지 않는다 — 값·변화는 옆 글자에 있고 접근성 설명에도 있다.
- 모든 위젯은 빈 값·0·None·1개짜리 시계열에서도 예외 없이 그려진다.
"""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from .. import growth, solved
from .theme import tokens
from .widgets import set_class

SPARK_W, SPARK_H = 96, 24
BAR_CHART_MIN_H = 120


def week_label(d: date) -> str:
    """차트 x 라벨: 주 월요일 "09-21"."""
    return d.strftime("%m-%d")


class BarChart(QWidget):
    """주별 값 막대 차트 (기본: 최근 8주 Pass 문제 수). 선택 주는 primary + 굵은 라벨, 나머지는 border_strong. 값 0 은 얇은 기준선만."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("BarChart")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(BAR_CHART_MIN_H)  # 스펙: 높이 120
        self.values: list[float] = []
        self.labels: list[str] = []
        self.highlight = -1
        self.set_data([], [], -1)

    def set_data(self, values: list[float], labels: list[str], highlight: int = -1, name: str = "주별 Pass 문제 수") -> None:
        n = min(len(values), len(labels)) if labels else len(values)
        self.values = [max(0.0, float(v or 0)) for v in values[:n]]
        self.labels = list(labels[:n]) + [""] * (len(self.values) - len(labels[:n]))
        self.highlight = highlight if 0 <= highlight < len(self.values) else -1
        desc = ", ".join(f"{lab}: {v:g}" for lab, v in zip(self.labels, self.values)) or "기록 없음"
        self.setAccessibleName(name)
        self.setAccessibleDescription(desc)
        self.setToolTip(f"{name}\n{desc}")
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = tokens.current()
        n = len(self.values)
        rect = QRectF(self.rect())
        label_h, top_pad = 16.0, 16.0
        base_y = rect.bottom() - label_h - 2
        plot_h = max(base_y - rect.top() - top_pad, 8.0)
        p.setPen(QPen(QColor(pal.border), 1))
        p.drawLine(QPointF(rect.left(), base_y), QPointF(rect.right(), base_y))
        if n == 0:
            p.setPen(QColor(pal.text_3))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "기록 없음")
            p.end()
            return
        slot = rect.width() / n
        bar_w = max(min(slot - tokens.SPACE, 40.0), 6.0)
        vmax = max(max(self.values), 1.0)
        font = QFont(self.font())
        font.setPointSize(tokens.FONT_SIZE_XS)
        small = QFont(font)
        bold = QFont(font)
        bold.setBold(True)
        p.setFont(small)
        fm_width = p.fontMetrics().horizontalAdvance("00-00") + tokens.SPACE
        step = 1 if slot >= fm_width else 2  # 좁으면 격 주 생략 (선택 주 라벨은 항상)
        for i, v in enumerate(self.values):
            cx = rect.left() + slot * (i + 0.5)
            hl = i == self.highlight
            h = plot_h * v / vmax
            color = QColor(pal.primary if hl else pal.border_strong)
            if v > 0:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(QRectF(cx - bar_w / 2, base_y - h, bar_w, h), tokens.RADIUS_SM, tokens.RADIUS_SM)
            else:
                p.setPen(QPen(color, 2))
                p.drawLine(QPointF(cx - bar_w / 2, base_y - 1), QPointF(cx + bar_w / 2, base_y - 1))
            p.setFont(bold if hl else small)
            p.setPen(QColor(pal.text if hl else pal.text_2))
            p.drawText(QRectF(cx - slot / 2, base_y - h - top_pad, slot, top_pad), Qt.AlignmentFlag.AlignCenter, f"{v:g}")
            if hl or i % step == (n - 1) % step:
                p.setPen(QColor(pal.text if hl else pal.text_3))
                p.drawText(QRectF(cx - slot / 2, base_y + 2, slot, label_h), Qt.AlignmentFlag.AlignCenter, self.labels[i])
        p.end()


class SparkLine(QWidget):
    """8주 추이 미니 선 (96x24). None 은 선을 끊고 점을 생략, 마지막 점만 강조. 값이 2개 미만이면 "-"."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SparkLine")
        self.setFixedSize(SPARK_W, SPARK_H)
        self.values: list[float | None] = []
        self.invert = False
        self.set_data([], False)

    def set_data(self, values: list[float | None], invert: bool = False, name: str = "추이") -> None:
        self.values = list(values)
        self.invert = invert
        real = [v for v in self.values if v is not None]
        if len(real) >= 2:
            desc = f"{name}: {real[0]:.2g} → {real[-1]:.2g}" + (" (낮을수록 좋음)" if invert else "")
        else:
            desc = f"{name}: 비교할 기록이 부족합니다"
        self.setAccessibleName(f"{name} 추이")
        self.setAccessibleDescription(desc)
        self.setToolTip(desc)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = tokens.current()
        real = [v for v in self.values if v is not None]
        if len(real) < 2:
            p.setPen(QColor(pal.text_3))
            p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, "-")
            p.end()
            return
        lo, hi = min(real), max(real)
        span = (hi - lo) or 1.0
        n = len(self.values)
        pad = 3.0
        w, h = self.width() - 2 * pad, self.height() - 2 * pad

        def pt(i: int, v: float) -> QPointF:
            x = pad + (w * i / (n - 1) if n > 1 else w / 2)
            y = pad + h - (h * (v - lo) / span if hi != lo else h / 2)
            return QPointF(x, y)

        p.setPen(QPen(QColor(pal.text_3), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        prev: QPointF | None = None
        last_i = max(i for i, v in enumerate(self.values) if v is not None)
        for i, v in enumerate(self.values):
            if v is None:
                prev = None  # 선 끊김
                continue
            cur = pt(i, v)
            if prev is not None:
                p.drawLine(prev, cur)
            prev = cur
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal.primary))
        p.drawEllipse(pt(last_i, self.values[last_i]), 3.0, 3.0)
        p.end()


class RateBar(QWidget):
    """가로 막대 (0~max_value). 길이는 참고용이고 값은 옆 글자에 병기한다."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.fraction = 0.0

    def set_fraction(self, f: float) -> None:
        self.fraction = max(0.0, min(1.0, float(f or 0)))
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = tokens.current()
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal.surface_alt))
        p.drawRoundedRect(r, 4, 4)
        if self.fraction > 0:
            p.setBrush(QColor(pal.primary))
            p.drawRoundedRect(QRectF(r.left(), r.top(), max(r.width() * self.fraction, 8.0), r.height()), 4, 4)
        p.end()


def _label(text: str = "", cls: str = "muted", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    set_class(lab, cls)
    lab.setWordWrap(wrap)
    return lab


class MetricRowWidget(QWidget):
    """지표 1행: 이름 · 값 · 변화 글자 · 스파크라인."""

    def __init__(self, row: growth.MetricRow, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName(f"MetricRow_{row.key}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, tokens.SPACE // 2, 0, tokens.SPACE // 2)
        lay.setSpacing(tokens.SPACE)
        self.name = _label(row.label, wrap=True)
        self.name.setFixedWidth(132)
        self.value = _label(row.value, "section", wrap=True)  # 줄바꿈 허용: 긴 값("힌트 2 · 정답 풀이 0")이 페이지를 가로로 넓히지 않게
        self.value.setFixedWidth(112)
        self.change = _label(row.change, "hint", wrap=True)
        self.change.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.spark = SparkLine()
        self.spark.set_data(row.series, row.invert, row.label)
        lay.addWidget(self.name)
        lay.addWidget(self.value)
        lay.addWidget(self.change, 1)
        lay.addWidget(self.spark)
        self.setAccessibleName(row.label)
        self.setAccessibleDescription(f"{row.value}. {row.change}")


class CategoryRowWidget(QWidget):
    """강점·약점 1행: 카테고리 이름 · 막대 + 점수 글자 · 변화 글자 · 스파크라인."""

    MAX_STRENGTH = 3.0  # 응답당 평균 강도의 최대 (막대 길이 기준)

    def __init__(self, row: growth.CategoryRow, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName(f"CategoryRow_{row.cid}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, tokens.SPACE // 2, 0, tokens.SPACE // 2)
        lay.setSpacing(tokens.SPACE)
        self.name = _label(row.name, "muted", wrap=True)
        self.name.setFixedWidth(132)
        mid = QVBoxLayout()
        mid.setSpacing(2)
        self.bar = RateBar()
        self.bar.set_fraction((row.rate or 0.0) / self.MAX_STRENGTH)
        self.value = _label(row.value, "hint", wrap=True)
        mid.addWidget(self.bar)
        mid.addWidget(self.value)
        self.change = _label(row.change, "hint", wrap=True)
        self.change.setFixedWidth(150)
        self.spark = SparkLine()
        self.spark.set_data(row.series, False, row.name)
        lay.addWidget(self.name)
        lay.addLayout(mid, 1)
        lay.addWidget(self.change)
        lay.addWidget(self.spark)
        self.setAccessibleName(row.name)
        self.setAccessibleDescription(f"{row.value}. {row.change}")


# --- 풀이 잔디 (M20) --------------------------------------------------------------------------

WEEKDAY_KO = "월화수목금토일"  # date.weekday() 순서
HEAT_WEEKS = 53
HEAT_GAP = 3
HEAT_CELL_MIN, HEAT_CELL_MAX = 8, 13
HEAT_LEFT_PAD = 26  # 요일 라벨 폭
HEAT_TOP_PAD = 18  # 월 라벨 높이


def day_text(d: date) -> str:
    """"2026-09-30 (수)"."""
    return f"{d.isoformat()} ({WEEKDAY_KO[d.weekday()]})"


def heat_palette() -> tuple[str, str]:
    """(0칸 색, 농도 색을 섞을 배경). 다크 팔레트가 생기면 그쪽을 쓴다."""
    pal = tokens.current()
    return pal.surface_alt, pal.surface


class HeatmapWidget(QWidget):
    """GitHub 식 풀이 잔디: 53주 x 7일 (열=주, 행=요일, 일요일 시작). 월 라벨은 위, 월·수·금 라벨은 왼쪽.

    - 칸 크기는 폭에 맞춰 8~13px 로 줄이고, 그래도 안 들어가면 최신 주가 보이도록 오른쪽 정렬로 앞(오래된 주)을 자른다 (가로 스크롤 없음).
    - 오늘 칸은 글자색 테두리, 선택한 칸은 primary 테두리. hover 툴팁 "2026-09-30 (수) · 3문제", 클릭 → day_clicked(date).
    - 색으로만 의미를 전달하지 않는다: 문제 수는 툴팁·접근성 설명에 있고 선택한 날은 아래 목록이 글자로 보여준다.
    """

    day_clicked = Signal(object)  # date

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Heatmap")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(HEAT_LEFT_PAD + 6 * (HEAT_CELL_MIN + HEAT_GAP))  # 아무리 좁아도 최소 6주는 보인다
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.counts: dict[date, int] = {}
        self.today = date.today()
        self.base = solved.DEFAULT_HEAT_COLOR
        self.selected: date | None = None
        self.set_data({}, self.today, self.base)

    # --- 데이터 ---
    def set_data(self, counts: dict[date, int], today: date, base: str | None = None) -> None:
        self.counts = dict(counts)
        self.today = today
        if base is not None:
            self.base = solved.parse_hex(base)
        start = solved.grid_start(today, HEAT_WEEKS)
        total = sum(n for d, n in self.counts.items() if start <= d <= today)
        self.setAccessibleName("풀이 잔디")
        self.setAccessibleDescription(f"지난 1년간 {total}문제 해결. 칸을 누르면 그날 푼 문제를 볼 수 있습니다")
        self._fit_height()
        self.update()

    def set_base(self, base: str) -> None:
        self.base = solved.parse_hex(base)
        self.update()

    def select(self, d: date | None) -> None:
        self.selected = d
        self.update()

    # --- 기하 ---
    def _layout(self) -> tuple[int, int, int]:
        """(칸 크기, 보이는 주 수, 첫 보이는 주의 격자 열 번호)."""
        avail = max(self.width() - HEAT_LEFT_PAD, 1)
        cell = max(HEAT_CELL_MIN, min(HEAT_CELL_MAX, avail // HEAT_WEEKS - HEAT_GAP))
        cols = max(1, min(HEAT_WEEKS, avail // (cell + HEAT_GAP)))
        return cell, cols, HEAT_WEEKS - cols

    def _fit_height(self) -> None:
        cell = self._layout()[0]
        h = HEAT_TOP_PAD + 7 * (cell + HEAT_GAP)
        if self.height() != h:
            self.setFixedHeight(h)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._fit_height()

    def visible_weeks(self) -> int:
        return self._layout()[1]

    def first_day(self) -> date:
        """보이는 첫 열(일요일)."""
        offset = self._layout()[2]
        return solved.grid_start(self.today, HEAT_WEEKS) + timedelta(weeks=offset)

    def cell_rect(self, d: date) -> QRectF | None:
        """그 날 칸의 사각형. 안 보이는 날(잘렸거나 미래)이면 None."""
        cell, cols, _o = self._layout()
        delta = (d - self.first_day()).days
        if d > self.today or delta < 0 or delta // 7 >= cols:
            return None
        col, row = divmod(delta, 7)
        return QRectF(HEAT_LEFT_PAD + col * (cell + HEAT_GAP), HEAT_TOP_PAD + row * (cell + HEAT_GAP), cell, cell)

    def cell_at(self, pos) -> date | None:
        cell, cols, _o = self._layout()
        pitch = cell + HEAT_GAP
        x, y = pos.x() - HEAT_LEFT_PAD, pos.y() - HEAT_TOP_PAD
        if x < 0 or y < 0:
            return None
        col, row = int(x // pitch), int(y // pitch)
        if col >= cols or row >= 7 or x % pitch >= cell or y % pitch >= cell:
            return None  # 칸 사이 틈·바깥
        d = self.first_day() + timedelta(days=col * 7 + row)
        return d if d <= self.today else None

    def tooltip_for(self, d: date) -> str:
        return f"{day_text(d)} · {self.counts.get(d, 0)}문제"

    # --- 입력 ---
    def event(self, e) -> bool:
        if e.type() == QEvent.Type.ToolTip:
            d = self.cell_at(e.pos())
            if d is None:
                QToolTip.hideText()
                e.ignore()
            else:
                QToolTip.showText(e.globalPos(), self.tooltip_for(d), self)
            return True
        return super().event(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        over = self.cell_at(e.position().toPoint()) is not None
        self.setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            d = self.cell_at(e.position().toPoint())
            if d is not None:
                self.selected = d
                self.update()
                self.day_clicked.emit(d)
        super().mouseReleaseEvent(e)

    # --- 그리기 ---
    def level_colors(self) -> list[str]:
        """0~4단계 색 5개."""
        empty, bg = heat_palette()
        return [empty, *solved.heat_colors(self.base, bg)]

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = tokens.current()
        colors = [QColor(c) for c in self.level_colors()]
        cell, cols, _o = self._layout()
        first = self.first_day()
        pitch = cell + HEAT_GAP
        font = QFont(self.font())
        font.setPointSize(tokens.FONT_SIZE_XS)
        p.setFont(font)
        p.setPen(QColor(pal.text_3))
        for row, name in ((1, "월"), (3, "수"), (5, "금")):
            p.drawText(QRectF(0, HEAT_TOP_PAD + row * pitch - 2, HEAT_LEFT_PAD - 4, pitch + 2), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, name)
        label_w = p.fontMetrics().horizontalAdvance("00월") + 4
        last_x = -label_w
        prev_month = None
        for col in range(cols):
            sunday = first + timedelta(weeks=col)
            if prev_month is not None and sunday.month != prev_month:
                x = HEAT_LEFT_PAD + col * pitch
                if x - last_x >= label_w:  # 라벨끼리 겹치면 건너뛴다
                    p.drawText(QRectF(x, 0, label_w + 8, HEAT_TOP_PAD - 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{sunday.month}월")
                    last_x = x
            prev_month = sunday.month
        p.setPen(Qt.PenStyle.NoPen)
        for col in range(cols):
            for row in range(7):
                d = first + timedelta(days=col * 7 + row)
                if d > self.today:
                    continue
                p.setBrush(colors[solved.level(self.counts.get(d, 0))])
                p.drawRoundedRect(QRectF(HEAT_LEFT_PAD + col * pitch, HEAT_TOP_PAD + row * pitch, cell, cell), 2, 2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for d, color, w, inset in ((self.today, pal.text, 1.5, 0.0), (self.selected, pal.primary, 2.0, 1.0)):
            r = self.cell_rect(d) if d is not None else None
            if r is not None:
                p.setPen(QPen(QColor(color), w))
                p.drawRoundedRect(r.adjusted(inset, inset, -inset, -inset), 2, 2)
        p.end()


class HeatLegend(QWidget):
    """"적게 ▢▢▢▢▢ 많이" 범례 — 칸 색은 HeatmapWidget 과 같은 방식으로 계산한다."""

    SWATCH = 11

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HeatLegend")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(HEAT_GAP + 1)
        lay.addStretch(1)
        lay.addWidget(_label("적게", "hint"))
        self.swatches: list[QLabel] = []
        for _ in range(5):
            sw = QLabel()
            sw.setFixedSize(self.SWATCH, self.SWATCH)
            self.swatches.append(sw)
            lay.addWidget(sw)
        lay.addWidget(_label("많이", "hint"))
        self.colors: list[str] = []
        self.setAccessibleName("범례: 적게에서 많이")
        self.set_base(solved.DEFAULT_HEAT_COLOR)

    def set_base(self, base: str) -> None:
        empty, bg = heat_palette()
        self.colors = [empty, *solved.heat_colors(base, bg)]
        for sw, c in zip(self.swatches, self.colors):
            sw.setStyleSheet(f"background: {c}; border-radius: 2px;")
