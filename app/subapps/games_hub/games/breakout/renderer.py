from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.breakout.game import (
    BALL_R, BRICK_COLS, BRICK_GAP, BRICK_H, BRICK_ROWS, BRICK_TOP, BRICK_W,
    FIELD_H, FIELD_W, PADDLE_H, PADDLE_W, PADDLE_Y, BreakoutState,
)
from app.subapps.games_hub.palette import GamePalette


class BreakoutRenderer(QWidget):
    def __init__(self, state: BreakoutState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setMinimumSize(320, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        sw, sh = self.width(), self.height()
        sx = sw / FIELD_W
        sy = sh / FIELD_H

        def fx(x: float) -> int: return round(x * sx)
        def fy(y: float) -> int: return round(y * sy)

        # Background
        p.fillRect(0, 0, sw, sh, pal.board_bg)

        s = self._state

        # Bricks — one pastel color per row, cycling through palette
        p.setPen(Qt.NoPen)
        for b in s.bricks:
            if not b.alive:
                continue
            bx = fx(b.col * BRICK_W + BRICK_GAP)
            by = fy(BRICK_TOP + b.row * BRICK_H + BRICK_GAP)
            bw = fx(BRICK_W - BRICK_GAP * 2)
            bh = fy(BRICK_H - BRICK_GAP * 2)
            p.setBrush(pal.piece(b.row))
            p.drawRoundedRect(bx, by, bw, bh, 3, 3)

        # Paddle
        p.setBrush(pal.text)
        p.drawRoundedRect(fx(s.paddle_x), fy(PADDLE_Y), fx(PADDLE_W), fy(PADDLE_H), 5, 5)

        # Ball
        p.setBrush(pal.accent)
        br = max(fx(BALL_R), 4)
        p.drawEllipse(fx(s.ball_x) - br, fy(s.ball_y) - br, br * 2, br * 2)

        # HUD
        p.setPen(pal.text_muted)
        p.drawText(6, 18, f"Score: {s.score}   Lives: {'♥ ' * s.lives}")

        if not s.launched:
            p.setPen(pal.text)
            p.drawText(0, 0, sw, sh, Qt.AlignCenter, "Press W / Space to launch")
