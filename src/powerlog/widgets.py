from __future__ import annotations

import bisect
import math
from datetime import date, datetime

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QSizePolicy, QToolTip, QWidget

from powerlog.storage import DayTotal, day_bounds

INK = "#1D1B18"
MUTED = "#9B958D"
ACCENT = "#C2805A"
LINE = "#EDEAE5"
STONE = "#E8E5DF"
PAPER = "#FFFFFF"
TERTIARY = "#C5BFB7"
SURFACE = "#F9F8F5"


def font(size: int, family: str = "", weight=QFont.Weight.Normal) -> QFont:
    result = QFont(family) if family else QFont(QApplication.font())
    result.setPixelSize(size)
    result.setWeight(weight)
    return result


def draw_icon(p: QPainter, kind: str, color: str, rect: QRectF):
    p.save()
    p.translate(rect.topLeft())
    p.scale(rect.width() / 24, rect.height() / 24)
    pen = QPen(
        QColor(color),
        1.6,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "power":
        p.drawArc(QRectF(3.5, 3.5, 17, 17), 125 * 16, 290 * 16)
        p.drawLine(QPointF(12, 2), QPointF(12, 11))
    elif kind == "overview":
        for x, y in ((5, 14), (12, 5), (19, 10)):
            p.drawLine(QPointF(x, y), QPointF(x, 21))
    elif kind == "history":
        p.drawEllipse(QRectF(3, 3, 18, 18))
        p.drawLine(QPointF(12, 7), QPointF(12, 12))
        p.drawLine(QPointF(12, 12), QPointF(16, 14))
    elif kind == "settings":
        for y, x in ((6, 8), (12, 16), (18, 10)):
            p.drawLine(QPointF(3, y), QPointF(x - 2, y))
            p.drawLine(QPointF(x + 2, y), QPointF(21, y))
            p.drawEllipse(QPointF(x, y), 2, 2)
    elif kind == "pulse":
        path = QPainterPath(QPointF(2, 13))
        for x, y in ((7, 13), (10, 5), (14, 20), (17, 11), (22, 11)):
            path.lineTo(x, y)
        p.drawPath(path)
    elif kind == "coin":
        p.drawEllipse(QRectF(4, 3, 16, 6))
        p.drawArc(QRectF(4, 8, 16, 6), 180 * 16, 180 * 16)
        p.drawArc(QRectF(4, 13, 16, 6), 180 * 16, 180 * 16)
        p.drawLine(QPointF(4, 6), QPointF(4, 16))
        p.drawLine(QPointF(20, 6), QPointF(20, 16))
    p.restore()


def icon(kind: str, color: str = MUTED, size: int = 24) -> QIcon:
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(p, kind, color, QRectF(1, 1, size - 2, size - 2))
    p.end()
    return QIcon(pixmap)


class PowerChart(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(280, 190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAccessibleName("功率变化图，单位瓦")
        self.day = date.today()
        self.points: list[tuple[float, float]] = []
        self.spans: set[tuple[float, float]] = set()
        self.hover_index: int | None = None

    def set_data(self, day: date, points, spans):
        self.day, self.points, self.spans = day, points, set(spans)
        self.hover_index = None
        self.update()

    def plot_rect(self):
        return QRectF(44, 20, max(1, self.width() - 62), max(1, self.height() - 52))

    def time_bounds(self):
        lower, upper = day_bounds(self.day)
        if not self.points:
            return lower, upper
        first = datetime.fromtimestamp(self.points[0][0])
        last = datetime.fromtimestamp(self.points[-1][0])
        start = first.replace(hour=first.hour // 2 * 2, minute=0, second=0, microsecond=0)
        end_hour = min(24, (last.hour // 2 + 1) * 2)
        end = (
            upper
            if end_hour == 24
            else last.replace(hour=end_hour, minute=0, second=0, microsecond=0).timestamp()
        )
        start = max(lower, min(start.timestamp(), end - 6 * 3600))
        return start, min(upper, max(end, start + 6 * 3600))

    def _line_path(self, points: list[QPointF]) -> QPainterPath:
        path = QPainterPath(points[0])
        # Match the piecewise linear interpolation used by energy integration.
        for point in points[1:]:
            path.lineTo(point)
        return path

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(font(11))
        area = self.plot_rect()
        peak = max((w for _, w in self.points), default=200)
        step = 10 ** math.floor(math.log10(max(peak, 10)))
        top = max(step, math.ceil(peak * 1.18 / step) * step)
        p.setPen(QColor(TERTIARY))
        p.drawText(QRectF(0, 0, 40, 16), Qt.AlignmentFlag.AlignRight, "W")
        for i in range(4):
            y = area.bottom() - i * area.height() / 3
            p.setPen(QPen(QColor(LINE), 0.5))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(QColor(TERTIARY))
            p.drawText(QRectF(0, y - 8, 35, 16), Qt.AlignmentFlag.AlignRight, f"{top * i / 3:.0f}")
        lower, upper = self.time_bounds()
        count = 6
        for index in range(count + 1):
            stamp = lower + (upper - lower) * index / count
            x = area.left() + (stamp - lower) / (upper - lower) * area.width()
            p.drawText(
                QRectF(x - 22, area.bottom() + 12, 44, 20),
                Qt.AlignmentFlag.AlignCenter,
                "24:00"
                if stamp == day_bounds(self.day)[1]
                else datetime.fromtimestamp(stamp).strftime("%H:%M"),
            )
        if not self.points:
            p.fillRect(area.adjusted(0, 0, 0, -1), QColor(PAPER))
            p.setFont(font(14))
            p.setPen(QColor(TERTIARY))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, "等待第一条功率记录")
            return

        def position(ts, watts):
            return QPointF(
                area.left() + (ts - lower) / (upper - lower) * area.width(),
                area.bottom() - watts / top * area.height(),
            )

        groups: list[list[QPointF]] = []
        for i, (ts, watts) in enumerate(self.points):
            if i == 0 or (self.points[i - 1][0], ts) not in self.spans:
                groups.append([])
            groups[-1].append(position(ts, watts))
        p.save()
        p.setClipRect(area.adjusted(-3, -3, 3, 3))
        gradient = QLinearGradient(area.topLeft(), area.bottomLeft())
        gradient.setColorAt(0, QColor(194, 128, 90, 20))
        gradient.setColorAt(1, QColor(194, 128, 90, 0))
        for group in groups:
            path = self._line_path(group)
            if len(group) > 1:
                fill = QPainterPath(path)
                fill.lineTo(group[-1].x(), area.bottom())
                fill.lineTo(group[0].x(), area.bottom())
                fill.closeSubpath()
                p.fillPath(fill, gradient)
            p.setPen(
                QPen(
                    QColor(ACCENT),
                    1.8,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            p.drawPath(path)
            if len(group) == 1:
                p.drawPoint(group[0])
        p.restore()
        index = self.hover_index if self.hover_index is not None else len(self.points) - 1
        ts, watts = self.points[index]
        point = position(ts, watts)
        p.setPen(QPen(QColor(PAPER), 1.5))
        p.setBrush(QColor(ACCENT))
        p.drawEllipse(point, 3.5, 3.5)
        p.setFont(font(11))
        text = f"{datetime.fromtimestamp(ts):%H:%M}   {watts:g} W"
        width = p.fontMetrics().horizontalAdvance(text) + 20
        bubble = QRectF(
            min(max(point.x() - width / 2, area.left()), area.right() - width),
            max(0, point.y() - 36),
            width,
            25,
        )
        p.setPen(QPen(QColor(LINE), 0.8))
        p.setBrush(QColor(PAPER))
        p.drawRoundedRect(bubble, 8, 8)
        p.setPen(QColor(INK))
        p.drawText(bubble, Qt.AlignmentFlag.AlignCenter, text)

    def mouseMoveEvent(self, event):
        if not self.points:
            return
        area = self.plot_rect()
        lower, upper = self.time_bounds()
        target = lower + (event.position().x() - area.left()) / area.width() * (upper - lower)
        index = bisect.bisect_left(self.points, (target,))
        choices = [i for i in (index - 1, index) if 0 <= i < len(self.points)]
        self.hover_index = min(choices, key=lambda i: abs(self.points[i][0] - target))
        self.update()

    def leaveEvent(self, event):
        self.hover_index = None
        self.update()


class DailyBars(QWidget):
    day_clicked = Signal(object)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 135)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("每日耗电柱状图，点击查看当天详情")
        self.days: list[DayTotal] = []
        self.today = date.today()

    def set_data(self, days: list[DayTotal], today: date):
        self.days, self.today = days, today
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(font(11))
        if not self.days:
            return
        area = QRectF(4, 24, self.width() - 8, self.height() - 50)
        maximum = max(max(day.kwh for day in self.days) * 1.15, 0.01)
        slot = area.width() / len(self.days)
        width = min(64, slot * 0.69)
        p.setPen(QPen(QColor(LINE), 0.5))
        p.drawLine(area.bottomLeft(), area.bottomRight())
        for i, day in enumerate(self.days):
            x = area.left() + (i + 0.5) * slot
            height = max(2, day.kwh / maximum * area.height())
            bar = QRectF(x - width / 2, area.bottom() - height, width, height)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ACCENT if day.day == self.today else STONE))
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            path.addRoundedRect(bar, min(10, width / 3), min(10, height / 2))
            path.addRect(QRectF(bar.left(), bar.center().y(), width, height / 2))
            if day.recorded_seconds:
                p.drawPath(path.simplified())
            else:
                p.fillRect(QRectF(bar.left(), area.bottom() - 1, width, 1), QColor(LINE))
            if len(self.days) <= 7:
                p.setPen(QColor(ACCENT if day.day == self.today else MUTED))
                value = f"{day.kwh:.2f}" if day.recorded_seconds else "—"
                p.drawText(
                    QRectF(x - 28, area.bottom() - height - 23, 56, 20),
                    Qt.AlignmentFlag.AlignCenter,
                    value,
                )
            p.setPen(QColor(INK if day.day == self.today else TERTIARY))
            if len(self.days) <= 7 or i % 5 == 0 or i == len(self.days) - 1:
                text = "今天" if day.day == self.today else str(day.day.day)
                p.drawText(
                    QRectF(x - 20, area.bottom() + 8, 40, 20), Qt.AlignmentFlag.AlignCenter, text
                )

    def index_at(self, x: float):
        if not self.days:
            return None
        return max(0, min(len(self.days) - 1, int((x - 4) / (self.width() - 8) * len(self.days))))

    def mouseMoveEvent(self, event):
        index = self.index_at(event.position().x())
        if index is None:
            return
        day = self.days[index]
        value = f"{day.kwh:.3f} kWh · 已记录 {day.recorded_seconds / 3600:.1f} 小时"
        if not day.recorded_seconds:
            value = "暂无有效累计区间"
        QToolTip.showText(event.globalPosition().toPoint(), f"{day.day:%Y-%m-%d}\n{value}", self)

    def mousePressEvent(self, event):
        index = self.index_at(event.position().x())
        if index is not None and event.button() == Qt.MouseButton.LeftButton:
            self.day_clicked.emit(self.days[index].day)
