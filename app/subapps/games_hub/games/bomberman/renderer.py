from __future__ import annotations

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.core.settings_store import settings_store

from app.subapps.games_hub.games.bomberman.game import (
    BLAST_TICKS, COLS, Cell, FUSE_TICKS, PlayerSlot, ROWS, BombermanState,
)
from app.subapps.games_hub.palette import GamePalette

_CELL = 36
_RADIUS = 5


class BombermanRenderer(QWidget):
    def __init__(self, state: BombermanState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.bot_path: list[tuple[int, int]] = []
        self.setMinimumSize(COLS * _CELL + 2, ROWS * _CELL + 30)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        cell = min(self.width() // COLS, (self.height() - 30) // ROWS)
        ox = (self.width()  - cell * COLS) // 2
        oy = (self.height() - 30 - cell * ROWS) // 2 + 30

        s = self._state

        # Board background
        p.setPen(Qt.NoPen)
        p.setBrush(pal.board_bg)
        p.drawRoundedRect(ox, oy, COLS * cell, ROWS * cell, 6, 6)

        # Grid cells
        for r in range(ROWS):
            for c in range(COLS):
                cell_c = s.grid[r][c]
                x, y = ox + c * cell, oy + r * cell
                if cell_c == Cell.PILLAR:
                    self._draw_pillar(p, x, y, cell, pal)
                elif cell_c == Cell.CRATE:
                    self._draw_crate(p, x, y, cell, pal)

        # Bot debug path
        if settings_store.get("bomberman.debug_bot_path", False) and self.bot_path:
            self._draw_bot_path(p, ox, oy, cell, pal)

        # Explosions
        for exp in s.explosions:
            alpha = int(255 * exp.life / BLAST_TICKS)
            for er, ec in exp.cells:
                self._draw_explosion(p, ox + ec * cell, oy + er * cell, cell, pal, alpha)

        # Bombs
        for bomb in s.bombs:
            self._draw_bomb(p, ox + bomb.col * cell, oy + bomb.row * cell, cell, pal, bomb.fuse)

        # Players
        p1 = s.players[PlayerSlot.P1]
        p2 = s.players[PlayerSlot.P2]
        if p1.alive:
            self._draw_player(p, ox + p1.col * cell, oy + p1.row * cell, cell, pal.piece(4), "1")
        if p2.alive:
            self._draw_player(p, ox + p2.col * cell, oy + p2.row * cell, cell, pal.piece(0), "2")

        # HUD
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
        p.setBrush(pal.piece(1))   # peach
        p.drawRoundedRect(x + pad, y + pad, cell - pad*2, cell - pad*2, _RADIUS, _RADIUS)
        # X cross on crate
        pen = QPen(QColor(pal.piece(1).red() - 40, pal.piece(1).green() - 30, pal.piece(1).blue() - 20))
        pen.setWidth(2)
        p.setPen(pen)
        inner = pad + 4
        p.drawLine(x + inner, y + inner, x + cell - inner, y + cell - inner)
        p.drawLine(x + cell - inner, y + inner, x + inner, y + cell - inner)

    def _draw_bomb(self, p: QPainter, x: int, y: int, cell: int, pal, fuse: int) -> None:
        pad = 5
        r = (cell - pad * 2) // 2
        cx, cy = x + cell // 2, y + cell // 2

        # Pulse: shrink slightly as fuse runs out
        t = fuse / FUSE_TICKS
        scale = 0.75 + 0.25 * t
        r2 = max(int(r * scale), 4)

        p.setPen(Qt.NoPen)
        p.setBrush(pal.text if fuse > FUSE_TICKS // 3 else pal.danger)
        p.drawEllipse(QPointF(cx, cy), r2, r2)

        # Fuse
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

    def _draw_player(self, p: QPainter, x: int, y: int, cell: int, color: QColor, label: str) -> None:
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
        """Draw the bot's planned Dijkstra path as small dots.
        Empty-cell hops use the accent colour; crate hops use danger colour
        (the bot will need to bomb those).  Start and end (players) are skipped."""
        r = max(cell // 7, 3)
        p.setPen(Qt.NoPen)
        for row, col in self.bot_path[1:-1]:   # skip bot and P1 cells
            cx = ox + col * cell + cell // 2
            cy = oy + row * cell + cell // 2
            if self._state.grid[row][col] == Cell.CRATE:
                color = QColor(pal.danger)
                color.setAlpha(200)
            else:
                color = QColor(pal.accent)
                color.setAlpha(160)
            p.setBrush(color)
            p.drawEllipse(QPointF(cx, cy), r, r)

    def _draw_hud(self, p: QPainter, x: int, y: int, w: int, pal, s: BombermanState) -> None:
        p1 = s.players[PlayerSlot.P1]
        p2 = s.players[PlayerSlot.P2]

        font = QFont("Segoe UI", 10)
        font.setBold(True)
        p.setFont(font)

        # P1 label left
        p.setPen(pal.piece(4))
        status1 = "P1  ●" if p1.alive else "P1  ✕"
        p.drawText(x, y, w // 2, 24, Qt.AlignLeft | Qt.AlignVCenter, status1)

        # P2 label right
        p.setPen(pal.piece(0))
        label2 = ("CPU" if s.mode.value == "single" else "P2")
        status2 = f"{'●  ' if p2.alive else '✕  '}{label2}"
        p.drawText(x + w // 2, y, w // 2, 24, Qt.AlignRight | Qt.AlignVCenter, status2)
