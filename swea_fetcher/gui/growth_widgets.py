"""성장 탭 위젯 (M19, 스펙 §6.7): BarChart · SparkLine (QPainter, 외부 차트 라이브러리 없음), 지표 행 · 카테고리 행.

- 색은 tokens.LIGHT 만 참조한다 (하드코딩 금지). 색으로만 의미를 전달하지 않는다 — 값·변화는 옆 글자에 있고 접근성 설명에도 있다.
- 모든 위젯은 빈 값·0·None·1개짜리 시계열에서도 예외 없이 그려진다.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .. import growth
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
        pal = tokens.LIGHT
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
        pal = tokens.LIGHT
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
        pal = tokens.LIGHT
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
