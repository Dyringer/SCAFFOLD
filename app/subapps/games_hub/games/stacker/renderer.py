from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.stacker.game import COLS, ROWS, StackerState
from app.subapps.games_hub.input import KeyHandler
from app.subapps.games_hub.palette import GamePalette

_RADIUS = 3

# The drop input. One button — Space or Enter — plus a left-click, so it plays
# the same whether you're on the keyboard or poking at it on a bench laptop.
_DROP_KEYS = {Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Up, Qt.Key_W}


class StackerRenderer(KeyHandler, QWidget):
    # drop is one-shot on press, not a held key, so nothing is tracked-held
    _TRACKED: ClassVar[set[int]] = set()

    def __init__(
        self,
        state: StackerState,
        on_drop: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._key_handler_init()
        self.state = state
        self._on_drop = on_drop
        self.setMinimumSize(COLS * 22 + 2, ROWS * 22 + 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------------
    # input

    def _sync_input(self) -> None:
        pass

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not event.isAutoRepeat() and event.key() in _DROP_KEYS:
            if self._on_drop is not None:
                self._on_drop()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._on_drop is not None:
            self._on_drop()
            return
        super().mousePressEvent(event)

    # ------------------------------------------------------------------
    # paint

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()
        s = self.state

        cell = min(self.width() // COLS, self.height() // ROWS)
        bw = cell * COLS
        bh = cell * ROWS
        ox = (self.width() - bw) // 2
        oy = (self.height() - bh) // 2

        # Board.
        p.setPen(Qt.NoPen)
        p.setBrush(pal.board_bg)
        p.drawRoundedRect(ox, oy, bw, bh, 6, 6)

        # Subtle inner grid (matches the house flat style — columns only; the
        # horizontal levels read clearly from the blocks themselves).
        pen = QPen(pal.grid)
        pen.setWidth(1)
        p.setPen(pen)
        for c in range(1, COLS):
            p.drawLine(ox + c * cell, oy + 4, ox + c * cell, oy + bh - 4)

        # Helper: row index 0 is the bottom of the board.
        def y_of(row: int) -> int:
            return oy + bh - (row + 1) * cell

        # Placed stack, bottom → top, each level a pastel band.
        p.setPen(Qt.NoPen)
        for row, (left, width) in enumerate(s.placed):
            self._block(p, pal.piece(row), ox, y_of(row), left, width, cell)

        # The live sliding row, sitting one level above the top placed block.
        moving_row = len(s.placed)
        if moving_row < ROWS:
            colr = pal.accent
            self._block(p, colr, ox, y_of(moving_row), s.pos, s.width, cell)
            # Drop-guide: faint shadow of where it would land on the base below.
            base_left, base_width = s.placed[-1]
            gl = max(s.pos, base_left)
            gr = min(s.pos + s.width, base_left + base_width)
            if gr > gl:
                ghost = QColor(colr)
                ghost.setAlpha(60)
                self._block(p, ghost, ox, y_of(len(s.placed) - 1), gl, gr - gl, cell)

        # Score / height readout above the board.
        p.setPen(pal.text_muted)
        streak = f"   perfect x{s.perfect_streak}" if s.perfect_streak >= 2 else ""
        p.drawText(ox, oy - 4, f"Score: {s.score:,}    Height: {s.height}{streak}")

    @staticmethod
    def _block(
        p: QPainter, color, ox: int, y: int, left: int, width: int, cell: int
    ) -> None:
        pad = 1
        p.setBrush(color)
        p.drawRoundedRect(
            ox + left * cell + pad,
            y + pad,
            width * cell - pad * 2,
            cell - pad * 2,
            _RADIUS,
            _RADIUS,
        )
