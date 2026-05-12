from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.space_invaders.game import (
    BULLET_H, BULLET_W, FIELD_H, FIELD_W,
    PLAYER_H, PLAYER_W, PLAYER_Y,
    SpaceInvadersState, _invader_rect,
)
from app.subapps.games_hub.palette import GamePalette


class SpaceInvadersRenderer(QWidget):
    def __init__(self, state: SpaceInvadersState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._tick = 0
        self.setMinimumSize(320, 360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        self._tick += 1
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        sw, sh = self.width(), self.height()
        sx = sw / FIELD_W
        sy = sh / FIELD_H

        def fx(x: float) -> int: return round(x * sx)
        def fy(y: float) -> int: return round(y * sy)

        player_c = pal.piece(3)    # mint
        bullet_c = pal.piece(2)    # lemon
        bomb_c   = pal.piece(0)    # pink-red

        p.fillRect(0, 0, sw, sh, pal.board_bg)
        s = self._state

        # Ground line
        p.setPen(player_c)
        p.drawLine(0, fy(PLAYER_Y + PLAYER_H + 4), sw, fy(PLAYER_Y + PLAYER_H + 4))

        # Invaders — pastel color by row, slight bounce animation
        anim = (self._tick // 8) % 2
        p.setPen(Qt.NoPen)
        for inv in s.invaders:
            if not inv.alive:
                continue
            ix, iy, iw, ih = _invader_rect(inv, s.offset_x, s.offset_y)
            color = pal.piece(inv.row)
            p.setBrush(color)
            body_y = fy(iy) + (2 if anim else 0)
            self._draw_invader(p, fx(ix), body_y, fx(iw), fy(ih), inv.row)

        # Player cannon — mint colored geometric shape
        p.setBrush(player_c)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(fx(s.player_x + 6), fy(PLAYER_Y + 6), fx(PLAYER_W - 12), fy(PLAYER_H - 6), 2, 2)
        p.drawRoundedRect(fx(s.player_x + PLAYER_W // 2 - 2), fy(PLAYER_Y), fx(4), fy(8), 1, 1)
        p.drawRoundedRect(fx(s.player_x), fy(PLAYER_Y + 8), fx(PLAYER_W), fy(PLAYER_H - 8), 3, 3)

        # Bullets
        p.setPen(Qt.NoPen)
        for b in s.bullets:
            p.setBrush(bullet_c if b.vy < 0 else bomb_c)
            p.drawRoundedRect(fx(b.x), fy(b.y), max(fx(BULLET_W), 2), max(fy(BULLET_H), 4), 1, 1)

        # HUD
        p.setPen(pal.text_muted)
        p.drawText(6, 18, f"Score: {s.score}   Wave: {s.wave}")

    def _draw_invader(self, p: QPainter, x: int, y: int, w: int, h: int, row: int) -> None:
        if row == 0:
            # Crab shape
            p.drawRoundedRect(x + w//4, y, w//2, h//3, 2, 2)
            p.drawRoundedRect(x, y + h//3, w, h//3, 2, 2)
            p.drawRoundedRect(x + w//4, y + 2*h//3, w//2, h//3, 2, 2)
            p.drawRoundedRect(x, y + h//2, w//6, h//4, 1, 1)
            p.drawRoundedRect(x + 5*w//6, y + h//2, w//6, h//4, 1, 1)
        elif row == 1:
            # Squid
            p.drawEllipse(x + w//4, y, w//2, h//2)
            p.drawRoundedRect(x, y + h//3, w, h//2, 3, 3)
            p.drawRoundedRect(x + w//6, y + 5*h//6, w//6, h//6, 1, 1)
            p.drawRoundedRect(x + 4*w//6, y + 5*h//6, w//6, h//6, 1, 1)
        else:
            # Generic alien block
            p.drawRoundedRect(x + w//6, y, 2*w//3, h//3, 2, 2)
            p.drawRoundedRect(x, y + h//3, w, h//3, 2, 2)
            p.drawRoundedRect(x + w//6, y + 2*h//3, w//6, h//3, 1, 1)
            p.drawRoundedRect(x + 4*w//6, y + 2*h//3, w//6, h//3, 1, 1)
