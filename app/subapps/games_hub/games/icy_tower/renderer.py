from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.icy_tower.game import (
    IcyTowerState, _Input,
    WORLD_W, SCREEN_H, _SPEED_BRACKETS,
)
from app.subapps.games_hub.input import KeyHandler
from app.subapps.games_hub.palette import GamePalette

_SIDE_W    = 120
_PLAT_R    = 4
_PLAYER_R  = 5

_JUMP_KEYS = {Qt.Key_Space, Qt.Key_Up, Qt.Key_W}


class IcyTowerRenderer(KeyHandler, QWidget):
    _TRACKED = {Qt.Key_Left, Qt.Key_Right, Qt.Key_A, Qt.Key_D,
                Qt.Key_Space, Qt.Key_Up, Qt.Key_W}

    def __init__(
        self,
        state:       IcyTowerState,
        input_state: _Input | None = None,
        parent:      QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._key_handler_init()
        self.state  = state
        self._input = input_state
        self.setMinimumSize(WORLD_W + _SIDE_W + 16, SCREEN_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def _sync_input(self) -> None:
        if self._input is None:
            return
        self._input.left  = Qt.Key_Left  in self._held or Qt.Key_A in self._held
        self._input.right = Qt.Key_Right in self._held or Qt.Key_D in self._held
        self._input.jump  = bool(self._held & _JUMP_KEYS)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        bw = int(WORLD_W * self._scale())
        bh = int(SCREEN_H * self._scale())
        board_x = max(0, (self.width() - bw - _SIDE_W - 8) // 2)
        board_y = max(0, (self.height() - bh) // 2)
        side_x  = board_x + bw + 8

        self._draw_board(p, board_x, board_y, bw, bh, self._scale(), pal)
        self._draw_side(p, side_x, board_y, bh, pal)

    def _scale(self) -> float:
        sx = min(1.0, (self.width() - _SIDE_W - 16) / WORLD_W)
        sy = min(1.0, self.height() / SCREEN_H)
        return min(sx, sy)

    # ------------------------------------------------------------------

    def _draw_board(self, p: QPainter, ox: int, oy: int,
                    bw: int, bh: int, scale: float, pal) -> None:
        s = self.state

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

        p.save()
        p.setClipRect(ox, oy, bw, bh)

        cam = s.camera_y

        def world_to_screen_y(wy: float) -> int:
            return oy + int((wy - cam) * scale)

        wall_w = max(4, int(6 * scale))
        wall_color = pal.piece(4)
        wall_sheen = QColor(
            min(255, wall_color.red()   + 40),
            min(255, wall_color.green() + 40),
            min(255, wall_color.blue()  + 50),
        )
        sheen_w = max(2, wall_w // 3)

        for seg in s.segments:
            if not seg.walled:
                continue
            seg_sy_top    = world_to_screen_y(seg.y_top)
            seg_sy_bottom = world_to_screen_y(seg.y_bottom)

            draw_top    = max(oy, seg_sy_top)
            draw_bottom = min(oy + bh, seg_sy_bottom)
            if draw_bottom <= draw_top:
                continue

            h = draw_bottom - draw_top
            for wx in (ox, ox + bw - wall_w):
                p.setPen(Qt.NoPen)
                p.setBrush(wall_color)
                p.drawRect(wx, draw_top, wall_w, h)
                p.setBrush(wall_sheen)
                inner_x = wx + wall_w - sheen_w if wx == ox else wx
                p.drawRect(inner_x, draw_top, sheen_w, h)

            for boundary_y in (seg_sy_top, seg_sy_bottom):
                if oy <= boundary_y <= oy + bh:
                    pen = QPen(pal.border)
                    pen.setWidth(1)
                    pen.setStyle(Qt.DashLine)
                    p.setPen(pen)
                    p.drawLine(ox, boundary_y, ox + bw, boundary_y)

        if s.on_wall != 0:
            spark_x = ox if s.on_wall == -1 else ox + bw - wall_w
            spark_color = QColor(pal.accent)
            spark_color.setAlpha(160)
            p.setPen(Qt.NoPen)
            p.setBrush(spark_color)
            py_s = oy + int((s.py - cam) * scale)
            ph_s = int(s.PLAYER_H * scale)
            p.drawRect(spark_x, py_s, wall_w, ph_s)

        plat_color    = pal.piece(4)
        crumble_color = pal.piece(1)
        sheen_normal  = QColor(
            min(255, plat_color.red()   + 40),
            min(255, plat_color.green() + 40),
            min(255, plat_color.blue()  + 50),
        )
        sheen_crumble = QColor(
            min(255, crumble_color.red()   + 40),
            min(255, crumble_color.green() + 30),
            min(255, crumble_color.blue()  + 20),
        )
        p.setPen(Qt.NoPen)
        for plat in s.platforms:
            sx = ox + int(plat.x * scale)
            sy = oy + int((plat.y - cam) * scale)
            sw = int(plat.w * scale)
            sh = max(3, int(plat.h * scale))
            if sy > oy + bh + sh or sy < oy - sh:
                continue

            color = crumble_color if plat.crumble else plat_color
            sheen = sheen_crumble if plat.crumble else sheen_normal

            p.setBrush(color)
            p.drawRoundedRect(sx, sy, sw, sh, _PLAT_R, _PLAT_R)
            sheen_h = max(2, sh // 3)
            p.setBrush(sheen)
            p.drawRoundedRect(sx + 2, sy + 1, max(4, sw - 4), sheen_h, _PLAT_R, _PLAT_R)

            if plat.crumble:
                crack_pen = QPen(QColor(max(0, crumble_color.red() - 40),
                                        max(0, crumble_color.green() - 30),
                                        max(0, crumble_color.blue() - 20)))
                crack_pen.setWidth(1)
                p.setPen(crack_pen)
                mid = sx + sw // 2
                p.drawLine(mid - sw // 6, sy + 2, mid, sy + sh - 2)
                p.drawLine(mid, sy + 2, mid + sw // 6, sy + sh - 2)
                p.setPen(Qt.NoPen)

        px_s = ox + int(s.px * scale)
        py_s = oy + int((s.py - cam) * scale)
        pw   = int(s.PLAYER_W * scale)
        ph   = int(s.PLAYER_H * scale)

        p.setBrush(pal.piece(3))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(px_s, py_s, pw, ph, _PLAYER_R, _PLAYER_R)

        eye_color = QColor(pal.board_bg)
        p.setBrush(eye_color)
        eye_r = max(2, int(pw * 0.12))
        eye_y = py_s + int(ph * 0.28)
        p.drawEllipse(px_s + int(pw * 0.25), eye_y, eye_r, eye_r)
        p.drawEllipse(px_s + int(pw * 0.60), eye_y, eye_r, eye_r)

        p.restore()

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
        s = self.state

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
        y += bar_h + 16

        walled = s.walled_at(s.py)
        zone_color = pal.piece(4) if walled else pal.piece(3)
        zone_text  = "WALLED" if walled else "OPEN"
        p.setPen(Qt.NoPen)
        p.setBrush(zone_color)
        p.drawRoundedRect(x + 10, y, bar_w, 16, 4, 4)
        p.setPen(pal.board_bg)
        p.drawText(x + 10, y, bar_w, 16, Qt.AlignCenter, zone_text)
        y += 28

        label("CONTROLS")
        y += 2
        for line in ["← → Move", "Space  Jump", "Wall+Space", "= wall jump", "Run+Jump", "= higher!"]:
            p.setPen(pal.text_muted)
            p.drawText(x + 10, y, line)
            y += 15
