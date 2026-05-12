from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.tetris.game import COLS, ROWS, TetrisState, _PIECES
from app.subapps.games_hub.palette import GamePalette

_CELL = 28
_PREVIEW_CELL = 18
_SIDE_W = 116
_RADIUS = 4   # rounded corner radius for cells


class TetrisRenderer(QWidget):
    def __init__(self, state: TetrisState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setMinimumSize(COLS * _CELL + _SIDE_W + 24, ROWS * _CELL + 24)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        board_x = (self.width()  - (COLS * _CELL + _SIDE_W)) // 2
        board_y = (self.height() - ROWS * _CELL) // 2

        self._draw_board(p, board_x, board_y, pal)
        self._draw_ghost(p, board_x, board_y, pal)
        self._draw_piece(p, board_x, board_y, self._state.piece, self._state.piece_type, pal)
        self._draw_side(p, board_x + COLS * _CELL + 12, board_y, pal)

    def _draw_board(self, p: QPainter, ox: int, oy: int, pal) -> None:
        bw, bh = COLS * _CELL, ROWS * _CELL

        # Board background — rounded rect
        p.setPen(Qt.NoPen)
        p.setBrush(pal.board_bg)
        p.drawRoundedRect(ox, oy, bw, bh, 6, 6)

        # Subtle grid
        pen = QPen(pal.grid)
        pen.setWidth(1)
        p.setPen(pen)
        for c in range(1, COLS):
            x = ox + c * _CELL
            p.drawLine(x, oy + 4, x, oy + bh - 4)
        for r in range(1, ROWS):
            y = oy + r * _CELL
            p.drawLine(ox + 4, y, ox + bw - 4, y)

        # Locked cells
        p.setPen(Qt.NoPen)
        for r, row in enumerate(self._state.board):
            for c, val in enumerate(row):
                if val:
                    self._draw_cell(p, ox + c * _CELL, oy + r * _CELL, pal.piece(val - 1))

    def _draw_piece(self, p: QPainter, ox: int, oy: int,
                    cells: list[tuple[int, int]], ptype: int, pal, alpha: int = 255) -> None:
        color = QColor(pal.piece(ptype))
        color.setAlpha(alpha)
        p.setPen(Qt.NoPen)
        for r, c in cells:
            self._draw_cell(p, ox + c * _CELL, oy + r * _CELL, color)

    def _draw_ghost(self, p: QPainter, ox: int, oy: int, pal) -> None:
        from app.subapps.games_hub.games.tetris.game import _valid
        ghost = list(self._state.piece)
        while True:
            candidate = [(r + 1, c) for r, c in ghost]
            if _valid(self._state.board, candidate):
                ghost = candidate
            else:
                break
        if ghost != self._state.piece:
            self._draw_piece(p, ox, oy, ghost, self._state.piece_type, pal, alpha=45)

    def _draw_side(self, p: QPainter, x: int, oy: int, pal) -> None:
        # Panel background
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

        # NEXT preview
        label("NEXT")
        preview_cells = [(r + 1, c + 1) for r, c in _PIECES[self._state.next_type]]
        p.setPen(Qt.NoPen)
        for r, c in preview_cells:
            self._draw_cell(p, x + 10 + c * _PREVIEW_CELL, y + r * _PREVIEW_CELL,
                            pal.piece(self._state.next_type), size=_PREVIEW_CELL)
        y += 5 * _PREVIEW_CELL + 14

        label("SCORE");  value(f"{self._state.score:,}")
        label("LEVEL");  value(str(self._state.level))
        label("LINES");  value(str(self._state.lines))

    @staticmethod
    def _draw_cell(p: QPainter, x: int, y: int, color: QColor, size: int = _CELL) -> None:
        pad = 2
        p.setBrush(color)
        p.drawRoundedRect(x + pad, y + pad, size - pad * 2, size - pad * 2, _RADIUS, _RADIUS)
