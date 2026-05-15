from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.space_invaders.game import (
    BULLET_H, BULLET_W, FIELD_H, FIELD_W,
    PLAYER_H, PLAYER_W, PLAYER_Y,
    SpaceInvadersState, _Input, _invader_rect,
)
from app.subapps.games_hub.input import KeyHandler
from app.subapps.games_hub.palette import GamePalette


class SpaceInvadersRenderer(KeyHandler, QWidget):
    _TRACKED = {Qt.Key_Left, Qt.Key_Right, Qt.Key_A, Qt.Key_D, Qt.Key_Space}

    def __init__(
        self,
        state:       SpaceInvadersState,
        input_state: _Input | None = None,
        parent:      QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._key_handler_init()
        self.state  = state
        self._input = input_state
        self._tick  = 0
        self.setMinimumSize(320, 360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def _sync_input(self) -> None:
        if self._input is None:
            return
        self._input.left  = Qt.Key_Left  in self._held or Qt.Key_A     in self._held
        self._input.right = Qt.Key_Right in self._held or Qt.Key_D     in self._held
        self._input.fire  = Qt.Key_Space in self._held

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

        player_c = pal.piece(3)
        bullet_c = pal.piece(2)
        bomb_c   = pal.piece(0)

        p.fillRect(0, 0, sw, sh, pal.board_bg)
        s = self.state

        p.setPen(player_c)
        p.drawLine(0, fy(PLAYER_Y + PLAYER_H + 4), sw, fy(PLAYER_Y + PLAYER_H + 4))

        anim = (self._tick // 8) % 2
        p.setPen(Qt.NoPen)
        for inv in s.invaders:
            if not inv.alive:
                continue
            ix, iy, iw, ih = _invader_rect(inv, s.offset_x, s.offset_y)
            p.setBrush(pal.piece(inv.row))
            self._draw_invader(p, fx(ix), fy(iy) + (2 if anim else 0), fx(iw), fy(ih), inv.row)

        p.setBrush(player_c)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(fx(s.player_x + 6), fy(PLAYER_Y + 6), fx(PLAYER_W - 12), fy(PLAYER_H - 6), 2, 2)
        p.drawRoundedRect(fx(s.player_x + PLAYER_W // 2 - 2), fy(PLAYER_Y), fx(4), fy(8), 1, 1)
        p.drawRoundedRect(fx(s.player_x), fy(PLAYER_Y + 8), fx(PLAYER_W), fy(PLAYER_H - 8), 3, 3)

        p.setPen(Qt.NoPen)
        for b in s.bullets:
            p.setBrush(bullet_c if b.vy < 0 else bomb_c)
            p.drawRoundedRect(fx(b.x), fy(b.y), max(fx(BULLET_W), 2), max(fy(BULLET_H), 4), 1, 1)

        p.setPen(pal.text_muted)
        p.drawText(6, 18, f"Score: {s.score}   Wave: {s.wave}")

    def _draw_invader(self, p: QPainter, x: int, y: int, w: int, h: int, row: int) -> None:
        if row == 0:
            p.drawRoundedRect(x + w//4, y, w//2, h//3, 2, 2)
            p.drawRoundedRect(x, y + h//3, w, h//3, 2, 2)
            p.drawRoundedRect(x + w//4, y + 2*h//3, w//2, h//3, 2, 2)
            p.drawRoundedRect(x, y + h//2, w//6, h//4, 1, 1)
            p.drawRoundedRect(x + 5*w//6, y + h//2, w//6, h//4, 1, 1)
        elif row == 1:
            p.drawEllipse(x + w//4, y, w//2, h//2)
            p.drawRoundedRect(x, y + h//3, w, h//2, 3, 3)
            p.drawRoundedRect(x + w//6, y + 5*h//6, w//6, h//6, 1, 1)
            p.drawRoundedRect(x + 4*w//6, y + 5*h//6, w//6, h//6, 1, 1)
        else:
            p.drawRoundedRect(x + w//6, y, 2*w//3, h//3, 2, 2)
            p.drawRoundedRect(x, y + h//3, w, h//3, 2, 2)
            p.drawRoundedRect(x + w//6, y + 2*h//3, w//6, h//3, 1, 1)
            p.drawRoundedRect(x + 4*w//6, y + 2*h//3, w//6, h//3, 1, 1)
