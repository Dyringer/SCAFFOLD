from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.icy_tower.game import (
    IcyTowerState,
    WORLD_W,
    SCREEN_H,
    _SPEED_BRACKETS,
)
from app.subapps.games_hub.palette import GamePalette

_SIDE_W    = 120
_PLAT_R    = 4
_PLAYER_R  = 5


class IcyTowerRenderer(QWidget):
    def __init__(self, state: IcyTowerState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setMinimumSize(WORLD_W + _SIDE_W + 16, SCREEN_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        # ------------------------------------------------------------------
        # Layout: board on the left, side panel on the right, both centred.
        total_w = WORLD_W + _SIDE_W + 8
        board_x = max(0, (self.width() - total_w) // 2)
        board_y = max(0, (self.height() - SCREEN_H) // 2)
        scale_x = min(1.0, (self.width() - _SIDE_W - 16) / WORLD_W)
        scale_y = min(1.0, self.height() / SCREEN_H)
        scale   = min(scale_x, scale_y)

        bw = int(WORLD_W * scale)
        bh = int(SCREEN_H * scale)
        board_x = max(0, (self.width() - bw - _SIDE_W - 8) // 2)
        board_y = max(0, (self.height() - bh) // 2)
        side_x  = board_x + bw + 8

        self._draw_board(p, board_x, board_y, bw, bh, scale, pal)
        self._draw_side(p, side_x, board_y, bh, pal)

    # ------------------------------------------------------------------

    def _draw_board(self, p: QPainter, ox: int, oy: int,
                    bw: int, bh: int, scale: float, pal) -> None:
        s = self._state

        # Sky gradient background
        grad = QLinearGradient(ox, oy, ox, oy + bh)
        if pal.dark:
            grad.setColorAt(0.0, QColor(10, 14, 30))
            grad.setColorAt(1.0, QColor(18, 18, 28))
        else:
            grad.setColorAt(0.0, QColor(185, 210, 240))
            grad.setColorAt(1.0, QColor(215, 228, 248))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(ox, oy, bw, bh, 6, 6)

        # Clip painting to board area
        p.save()
        p.setClipRect(ox, oy, bw, bh)

        cam = s.camera_y

        def world_to_screen(wx: float, wy: float):
            sx = ox + int(wx * scale)
            sy = oy + int((wy - cam) * scale)
            return sx, sy

        # Platforms
        plat_color  = pal.piece(4)  # sky blue
        sheen_color = QColor(
            min(255, plat_color.red()   + 40),
            min(255, plat_color.green() + 40),
            min(255, plat_color.blue()  + 50),
        )

        p.setPen(Qt.NoPen)
        for plat in s.platforms:
            sx, sy = world_to_screen(plat.x, plat.y)
            sw = int(plat.w * scale)
            sh = int(plat.h * scale)
            if sy > oy + bh + sh or sy < oy - sh:
                continue

            # Main body
            p.setBrush(plat_color)
            p.drawRoundedRect(sx, sy, sw, sh, _PLAT_R, _PLAT_R)

            # Icy sheen — lighter top third
            sheen_h = max(2, sh // 3)
            p.setBrush(sheen_color)
            p.drawRoundedRect(sx + 2, sy + 1, max(4, sw - 4), sheen_h, _PLAT_R, _PLAT_R)

        # Player
        px_s, py_s = world_to_screen(s.px, s.py)
        pw = int(s.PLAYER_W * scale)
        ph = int(s.PLAYER_H * scale)

        player_color = pal.piece(3)  # mint
        p.setBrush(player_color)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(px_s, py_s, pw, ph, _PLAYER_R, _PLAYER_R)

        # Simple face — two dots for eyes
        eye_color = QColor(pal.board_bg)
        p.setBrush(eye_color)
        eye_r = max(2, int(pw * 0.12))
        eye_y = py_s + int(ph * 0.28)
        p.drawEllipse(px_s + int(pw * 0.25), eye_y, eye_r, eye_r)
        p.drawEllipse(px_s + int(pw * 0.60), eye_y, eye_r, eye_r)

        p.restore()

        # Danger flash bar at bottom when scroll is fast
        max_spd = _SPEED_BRACKETS[-1][1]
        if s.scroll_speed >= 1.3 and max_spd > 0:
            intensity = (s.scroll_speed - 1.3) / (max_spd - 1.3)
            alpha = int(intensity * 90)
            danger = QColor(pal.danger)
            danger.setAlpha(alpha)
            p.setPen(Qt.NoPen)
            p.setBrush(danger)
            p.drawRect(ox, oy + bh - 6, bw, 6)

    def _draw_side(self, p: QPainter, x: int, oy: int, bh: int, pal) -> None:
        s = self._state

        p.setPen(Qt.NoPen)
        p.setBrush(pal.surface)
        p.drawRoundedRect(x, oy, _SIDE_W - 4, bh, 6, 6)

        y = oy + 18

        def label(text: str) -> None:
            nonlocal y
            p.setPen(pal.text_muted)
            p.drawText(x + 10, y, text)
            y += 16

        def value(text: str) -> None:
            nonlocal y
            p.setPen(pal.text)
            p.drawText(x + 10, y, text)
            y += 24

        label("FLOOR")
        value(str(s.floor))

        label("SCORE")
        value(f"{s.score:,}")

        y += 8
        label("SPEED")
        # Speed bar
        bar_w = _SIDE_W - 28
        bar_h = 8
        max_spd = _SPEED_BRACKETS[-1][1]
        fill = int(bar_w * min(1.0, s.scroll_speed / max_spd)) if max_spd > 0 else 0
        p.setPen(Qt.NoPen)
        p.setBrush(pal.grid)
        p.drawRoundedRect(x + 10, y, bar_w, bar_h, 3, 3)
        if fill > 0:
            bar_color = pal.success if s.scroll_speed < 1.3 else pal.danger
            p.setBrush(bar_color)
            p.drawRoundedRect(x + 10, y, fill, bar_h, 3, 3)
        y += bar_h + 20

        label("CONTROLS")
        y += 2
        for line in ["← → Move", "Space  Jump", "Run+Jump", "= higher!"]:
            p.setPen(pal.text_muted)
            p.setFont(p.font())
            p.drawText(x + 10, y, line)
            y += 15
