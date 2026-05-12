from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.snake.game import COLS, ROWS, SnakeState
from app.subapps.games_hub.palette import GamePalette

_CELL = 24
_RADIUS = 4


class SnakeRenderer(QWidget):
    def __init__(self, state: SnakeState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setMinimumSize(COLS * _CELL + 2, ROWS * _CELL + 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        cell = min(self.width() // COLS, self.height() // ROWS)
        ox = (self.width()  - cell * COLS) // 2
        oy = (self.height() - cell * ROWS) // 2

        head_c  = pal.piece(3)   # mint green
        apple_c = pal.piece(0)   # pink-red

        # Board background — rounded rect
        p.setPen(Qt.NoPen)
        p.setBrush(pal.board_bg)
        p.drawRoundedRect(ox, oy, COLS * cell, ROWS * cell, 6, 6)

        # Subtle grid — inner lines only
        from PySide6.QtGui import QPen
        pen = QPen(pal.grid)
        pen.setWidth(1)
        p.setPen(pen)
        for c in range(1, COLS):
            p.drawLine(ox + c * cell, oy + 4, ox + c * cell, oy + ROWS * cell - 4)
        for r in range(1, ROWS):
            p.drawLine(ox + 4, oy + r * cell, ox + COLS * cell - 4, oy + r * cell)

        # Snake
        p.setPen(Qt.NoPen)
        body = list(self._state.body)
        n = len(body)
        for i, (r, c) in enumerate(body):
            t = i / max(n - 1, 1)
            # Fade from mint (head) toward a slightly darker shade at the tail
            fade = QColor(
                int(head_c.red()   * (1 - t * 0.45)),
                int(head_c.green() * (1 - t * 0.40)),
                int(head_c.blue()  * (1 - t * 0.35)),
            )
            pad = 2
            p.setBrush(fade)
            p.drawRoundedRect(ox + c * cell + pad, oy + r * cell + pad,
                              cell - pad * 2, cell - pad * 2, _RADIUS, _RADIUS)

        # Apple — circle in pastel red
        ar, ac = self._state.apple
        pad = 3
        p.setBrush(apple_c)
        p.drawEllipse(ox + ac * cell + pad, oy + ar * cell + pad,
                      cell - pad * 2, cell - pad * 2)

        # Score
        p.setPen(pal.text_muted)
        p.drawText(ox, oy - 4, f"Score: {self._state.score}")
