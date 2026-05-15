from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.snake.game import COLS, ROWS, SnakeState
from app.subapps.games_hub.input import KeyHandler
from app.subapps.games_hub.palette import GamePalette

_CELL   = 24
_RADIUS = 4

_DIR_KEYS = {
    Qt.Key_W: (-1, 0), Qt.Key_Up:    (-1, 0),
    Qt.Key_S: ( 1, 0), Qt.Key_Down:  ( 1, 0),
    Qt.Key_A: ( 0,-1), Qt.Key_Left:  ( 0,-1),
    Qt.Key_D: ( 0, 1), Qt.Key_Right: ( 0, 1),
}


class SnakeRenderer(KeyHandler, QWidget):
    _TRACKED = set(_DIR_KEYS.keys())

    def __init__(
        self,
        state:    SnakeState,
        on_dir:   Callable[[int, int], None] | None = None,
        parent:   QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._key_handler_init()
        self.state   = state
        self._on_dir = on_dir
        self.setMinimumSize(COLS * _CELL + 2, ROWS * _CELL + 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def _sync_input(self) -> None:
        # Direction is one-shot on press, not held — handled in keyPressEvent override
        pass

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not event.isAutoRepeat():
            dr_dc = _DIR_KEYS.get(event.key())
            if dr_dc is not None and self._on_dir is not None:
                self._on_dir(*dr_dc)
                return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        cell = min(self.width() // COLS, self.height() // ROWS)
        ox = (self.width()  - cell * COLS) // 2
        oy = (self.height() - cell * ROWS) // 2

        head_c  = pal.piece(3)
        apple_c = pal.piece(0)

        p.setPen(Qt.NoPen)
        p.setBrush(pal.board_bg)
        p.drawRoundedRect(ox, oy, COLS * cell, ROWS * cell, 6, 6)

        pen = QPen(pal.grid)
        pen.setWidth(1)
        p.setPen(pen)
        for c in range(1, COLS):
            p.drawLine(ox + c * cell, oy + 4, ox + c * cell, oy + ROWS * cell - 4)
        for r in range(1, ROWS):
            p.drawLine(ox + 4, oy + r * cell, ox + COLS * cell - 4, oy + r * cell)

        p.setPen(Qt.NoPen)
        body = list(self.state.body)
        n = len(body)
        for i, (r, c) in enumerate(body):
            t = i / max(n - 1, 1)
            fade = QColor(
                int(head_c.red()   * (1 - t * 0.45)),
                int(head_c.green() * (1 - t * 0.40)),
                int(head_c.blue()  * (1 - t * 0.35)),
            )
            pad = 2
            p.setBrush(fade)
            p.drawRoundedRect(ox + c * cell + pad, oy + r * cell + pad,
                              cell - pad * 2, cell - pad * 2, _RADIUS, _RADIUS)

        ar, ac = self.state.apple
        pad = 3
        p.setBrush(apple_c)
        p.drawEllipse(ox + ac * cell + pad, oy + ar * cell + pad,
                      cell - pad * 2, cell - pad * 2)

        p.setPen(pal.text_muted)
        p.drawText(ox, oy - 4, f"Score: {self.state.score}")
