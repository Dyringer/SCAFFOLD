from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class SparklineWidget(QWidget):
    """Tiny inline line chart for time-series values (typically RTT in ms).

    Auto-scales y to [0, max(values)]. No axes, no labels — pure glance widget.
    """

    def __init__(
        self,
        color: str = "#5a8dee",
        height: int = 16,
        width: int = 80,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._values: list[float] = []
        self.setFixedSize(width, height)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_values(self, values: Iterable[float]) -> None:
        self._values = [float(v) for v in values]
        self.update()

    def paintEvent(self, _evt) -> None:  # noqa: N802
        if len(self._values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mx = max(self._values) or 1.0
        n = len(self._values)
        step = w / max(n - 1, 1)
        pts = []
        for i, v in enumerate(self._values):
            x = i * step
            y = h - 1 - (v / mx) * (h - 2)
            pts.append((x, y))
        pen = QPen(self._color)
        pen.setWidth(1)
        p.setPen(pen)
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
