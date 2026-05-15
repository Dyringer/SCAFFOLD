from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.tetris.game import COLS, ROWS, TetrisState, _PIECES
from app.subapps.games_hub.input import KeyHandler
from app.subapps.games_hub.palette import GamePalette

if TYPE_CHECKING:
    from app.subapps.games_hub.games.tetris.game import TetrisGame

_CELL         = 28
_PREVIEW_CELL = 18
_SIDE_W       = 116
_RADIUS       = 4


class TetrisRenderer(KeyHandler, QWidget):
    _TRACKED = {
        Qt.Key_Left, Qt.Key_Right,
        Qt.Key_Up, Qt.Key_Down, Qt.Key_Space,
        Qt.Key_A, Qt.Key_D, Qt.Key_W, Qt.Key_S,
    }

    def __init__(
        self,
        state:  TetrisState,
        game:   "TetrisGame | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._key_handler_init()
        self.state  = state
        self._game  = game
        self.setMinimumSize(COLS * _CELL + _SIDE_W + 24, ROWS * _CELL + 24)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def _sync_input(self) -> None:
        pass  # DAS/ARR handled via press/release overrides below

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._game is None or event.isAutoRepeat():
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key_Left, Qt.Key_A):
            self._game.on_shift_start(-1)
        elif key in (Qt.Key_Right, Qt.Key_D):
            self._game.on_shift_start(1)
        elif key in (Qt.Key_Up, Qt.Key_W):
            self._game.on_rotate()
        elif key in (Qt.Key_Down, Qt.Key_S):
            self._game.on_soft_drop()
        elif key == Qt.Key_Space:
            self._game.on_hard_drop()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if self._game is None or event.isAutoRepeat():
            super().keyReleaseEvent(event)
            return
        key = event.key()
        if key in (Qt.Key_Left, Qt.Key_A):
            self._game.on_shift_end(-1)
        elif key in (Qt.Key_Right, Qt.Key_D):
            self._game.on_shift_end(1)
        else:
            super().keyReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        board_x = (self.width()  - (COLS * _CELL + _SIDE_W)) // 2
        board_y = (self.height() - ROWS * _CELL) // 2

        self._draw_board(p, board_x, board_y, pal)
        self._draw_ghost(p, board_x, board_y, pal)
        self._draw_piece(p, board_x, board_y, self.state.piece, self.state.piece_type, pal)
        self._draw_side(p, board_x + COLS * _CELL + 12, board_y, pal)

    def _draw_board(self, p: QPainter, ox: int, oy: int, pal) -> None:
        bw, bh = COLS * _CELL, ROWS * _CELL
        p.setPen(Qt.NoPen)
        p.setBrush(pal.board_bg)
        p.drawRoundedRect(ox, oy, bw, bh, 6, 6)
        pen = QPen(pal.grid)
        pen.setWidth(1)
        p.setPen(pen)
        for c in range(1, COLS):
            x = ox + c * _CELL
            p.drawLine(x, oy + 4, x, oy + bh - 4)
        for r in range(1, ROWS):
            y = oy + r * _CELL
            p.drawLine(ox + 4, y, ox + bw - 4, y)
        p.setPen(Qt.NoPen)
        for r, row in enumerate(self.state.board):
            for c, val in enumerate(row):
                if val:
                    self._draw_cell(p, ox + c * _CELL, oy + r * _CELL, pal.piece(val - 1))

    def _draw_piece(self, p: QPainter, ox: int, oy: int,
                    cells: list[tuple[int, int]], ptype: int, pal,
                    alpha: int = 255) -> None:
        color = QColor(pal.piece(ptype))
        color.setAlpha(alpha)
        p.setPen(Qt.NoPen)
        for r, c in cells:
            self._draw_cell(p, ox + c * _CELL, oy + r * _CELL, color)

    def _draw_ghost(self, p: QPainter, ox: int, oy: int, pal) -> None:
        from app.subapps.games_hub.games.tetris.game import _valid
        ghost = list(self.state.piece)
        while True:
            candidate = [(r + 1, c) for r, c in ghost]
            if _valid(self.state.board, candidate):
                ghost = candidate
            else:
                break
        if ghost != self.state.piece:
            self._draw_piece(p, ox, oy, ghost, self.state.piece_type, pal, alpha=45)

    def _draw_side(self, p: QPainter, x: int, oy: int, pal) -> None:
        panel_h = ROWS * _CELL
        p.setPen(Qt.NoPen)
        p.setBrush(pal.surface)
        p.drawRoundedRect(x, oy, _SIDE_W - 4, panel_h, 6, 6)
        y = oy + 16

        def label(text: str) -> None:
            nonlocal y
            p.setPen(pal.text_muted)
            p.drawText(x + 10, y, text)
            y += 15

        def value(text: str) -> None:
            nonlocal y
            p.setPen(pal.text)
            p.drawText(x + 10, y, text)
            y += 22

        label("NEXT")
        preview_cells = [(r + 1, c + 1) for r, c in _PIECES[self.state.next_type]]
        p.setPen(Qt.NoPen)
        for r, c in preview_cells:
            self._draw_cell(p, x + 10 + c * _PREVIEW_CELL, y + r * _PREVIEW_CELL,
                            pal.piece(self.state.next_type), size=_PREVIEW_CELL)
        y += 5 * _PREVIEW_CELL + 14

        label("SCORE"); value(f"{self.state.score:,}")
        label("LEVEL"); value(str(self.state.level))
        label("LINES"); value(str(self.state.lines))

    @staticmethod
    def _draw_cell(p: QPainter, x: int, y: int, color: QColor, size: int = _CELL) -> None:
        pad = 2
        p.setBrush(color)
        p.drawRoundedRect(x + pad, y + pad, size - pad * 2, size - pad * 2, _RADIUS, _RADIUS)
