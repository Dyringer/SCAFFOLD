from __future__ import annotations

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.core.settings_store import settings_store
from app.subapps.games_hub.games.bomberman.game_core import (
    BLAST_TICKS, COLS, Cell, FUSE_TICKS, P1, P2, ROWS,
    BombermanState, InputState,
)
from app.subapps.games_hub.input import KeyHandler
from app.subapps.games_hub.palette import GamePalette

_CELL   = 36
_RADIUS = 5

_P1_MOVE_KEYS  = {Qt.Key_W, Qt.Key_S, Qt.Key_A, Qt.Key_D}
_P2_MOVE_KEYS  = {Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right}


class BombermanRenderer(KeyHandler, QWidget):

    def __init__(
        self,
        state:      BombermanState,
        input1:     InputState | None = None,
        p1_bomb:    int = Qt.Key_Space,
        p2_label:   str = "P2",
        input2:     InputState | None = None,
        p2_bomb:    int = Qt.Key_M,
        parent:     QWidget | None = None,
    ) -> None:
        self._TRACKED = _P1_MOVE_KEYS | _P2_MOVE_KEYS | {p1_bomb, p2_bomb}
        super().__init__(parent)
        self._key_handler_init()
        self.state     = state
        self._input1   = input1
        self._input2   = input2
        self._p1_bomb  = p1_bomb
        self._p2_bomb  = p2_bomb
        self._p2_label = p2_label
        self.bot_path: list[tuple[int, int]] = []
        self.setMinimumSize(COLS * _CELL + 2, ROWS * _CELL + 30)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def _sync_input(self) -> None:
        if self._input1 is not None:
            self._input1.up    = Qt.Key_W in self._held
            self._input1.down  = Qt.Key_S in self._held
            self._input1.left  = Qt.Key_A in self._held
            self._input1.right = Qt.Key_D in self._held
            self._input1.bomb  = self._p1_bomb in self._held
        if self._input2 is not None:
            self._input2.up    = Qt.Key_Up    in self._held
            self._input2.down  = Qt.Key_Down  in self._held
            self._input2.left  = Qt.Key_Left  in self._held
            self._input2.right = Qt.Key_Right in self._held
            self._input2.bomb  = self._p2_bomb in self._held

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        cell = min(self.width() // COLS, (self.height() - 30) // ROWS)
        ox = (self.width()  - cell * COLS) // 2
        oy = (self.height() - 30 - cell * ROWS) // 2 + 30

        s = self.state

        p.setPen(Qt.NoPen)
        p.setBrush(pal.board_bg)
        p.drawRoundedRect(ox, oy, COLS * cell, ROWS * cell, 6, 6)

        for r in range(ROWS):
            for c in range(COLS):
                cell_c = s.grid[r][c]
                x, y = ox + c * cell, oy + r * cell
                if cell_c == Cell.PILLAR:
                    self._draw_pillar(p, x, y, cell, pal)
                elif cell_c == Cell.CRATE:
                    self._draw_crate(p, x, y, cell, pal)

        if settings_store.get("bomberman.debug_bot_path", False) and self.bot_path:
            self._draw_bot_path(p, ox, oy, cell, pal)

        for exp in s.explosions:
            alpha = int(255 * exp.life / BLAST_TICKS)
            for er, ec in exp.cells:
                self._draw_explosion(p, ox + ec * cell, oy + er * cell, cell, pal, alpha)

        for bomb in s.bombs:
            self._draw_bomb(p, ox + bomb.col * cell, oy + bomb.row * cell, cell, pal, bomb.fuse)

        p1 = s.players[P1]
        p2 = s.players[P2]
        if p1.alive:
            self._draw_player(p, ox + p1.col * cell, oy + p1.row * cell, cell, pal.piece(4), "1")
        if p2.alive:
            self._draw_player(p, ox + p2.col * cell, oy + p2.row * cell, cell, pal.piece(0), "2")

        self._draw_hud(p, ox, oy - 28, COLS * cell, pal, s)

    # ------------------------------------------------------------------

    def _draw_pillar(self, p: QPainter, x: int, y: int, cell: int, pal) -> None:
        pad = 1
        p.setPen(Qt.NoPen)
        p.setBrush(pal.border)
        p.drawRoundedRect(x + pad, y + pad, cell - pad*2, cell - pad*2, 3, 3)

    def _draw_crate(self, p: QPainter, x: int, y: int, cell: int, pal) -> None:
        pad = 2
        p.setPen(Qt.NoPen)
        p.setBrush(pal.piece(1))
        p.drawRoundedRect(x + pad, y + pad, cell - pad*2, cell - pad*2, _RADIUS, _RADIUS)
        c1 = pal.piece(1)
        pen = QPen(QColor(c1.red() - 40, c1.green() - 30, c1.blue() - 20))
        pen.setWidth(2)
        p.setPen(pen)
        inner = pad + 4
        p.drawLine(x + inner, y + inner, x + cell - inner, y + cell - inner)
        p.drawLine(x + cell - inner, y + inner, x + inner, y + cell - inner)

    def _draw_bomb(self, p: QPainter, x: int, y: int, cell: int, pal, fuse: int) -> None:
        pad = 5
        r   = (cell - pad * 2) // 2
        cx, cy = x + cell // 2, y + cell // 2
        t   = fuse / FUSE_TICKS
        r2  = max(int(r * (0.75 + 0.25 * t)), 4)
        p.setPen(Qt.NoPen)
        p.setBrush(pal.text if fuse > FUSE_TICKS // 3 else pal.danger)
        p.drawEllipse(QPointF(cx, cy), r2, r2)
        pen = QPen(pal.piece(2))
        pen.setWidth(2)
        p.setPen(pen)
        p.drawLine(cx, cy - r2, cx + 4, cy - r2 - 6)

    def _draw_explosion(self, p: QPainter, x: int, y: int, cell: int, pal, alpha: int) -> None:
        color = QColor(pal.danger)
        color.setAlpha(alpha)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        pad = 3
        p.drawRoundedRect(x + pad, y + pad, cell - pad*2, cell - pad*2, 4, 4)

    def _draw_player(self, p: QPainter, x: int, y: int, cell: int, color: QColor,
                     label: str) -> None:
        pad = 4
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(x + pad, y + pad, cell - pad*2, cell - pad*2)
        p.setPen(QColor(255, 255, 255, 200))
        font = QFont("Segoe UI", max(cell // 3, 8))
        font.setBold(True)
        p.setFont(font)
        p.drawText(x, y, cell, cell, Qt.AlignCenter, label)

    def _draw_bot_path(self, p: QPainter, ox: int, oy: int, cell: int, pal) -> None:
        r = max(cell // 7, 3)
        p.setPen(Qt.NoPen)
        for row, col in self.bot_path[1:-1]:
            cx = ox + col * cell + cell // 2
            cy = oy + row * cell + cell // 2
            if self.state.grid[row][col] == Cell.CRATE:
                color = QColor(pal.danger)
                color.setAlpha(200)
            else:
                color = QColor(pal.accent)
                color.setAlpha(160)
            p.setBrush(color)
            p.drawEllipse(QPointF(cx, cy), r, r)

    def _draw_hud(self, p: QPainter, x: int, y: int, w: int, pal,
                  s: BombermanState) -> None:
        p1 = s.players[P1]
        p2 = s.players[P2]
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        p.setFont(font)
        p.setPen(pal.piece(4))
        p.drawText(x, y, w // 2, 24, Qt.AlignLeft | Qt.AlignVCenter,
                   "P1  ●" if p1.alive else "P1  ✕")
        p.setPen(pal.piece(0))
        status2 = f"{'●  ' if p2.alive else '✕  '}{self._p2_label}"
        p.drawText(x + w // 2, y, w // 2, 24, Qt.AlignRight | Qt.AlignVCenter, status2)
