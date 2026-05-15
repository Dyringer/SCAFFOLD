from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.asteroidsbomber.game import (
    ASTEROID_SIZES, BOMB_BLAST_R, BOMB_FUSE_TICKS,
    FIELD_H, FIELD_W, ABState, _Input,
)
from app.subapps.games_hub.input import KeyHandler
from app.subapps.games_hub.palette import GamePalette

_SHIP_POINTS = [
    QPointF(0,   -14),
    QPointF(-8,    8),
    QPointF(0,     4),
    QPointF(8,     8),
]
_THRUSTER_POINTS = [
    QPointF(-4,  4),
    QPointF(0,  14),
    QPointF(4,   4),
]

_SHIP_COLORS = [3, 0, 4, 5, 6]

# P1: WASD + S-bomb;  P2: arrows + ↓-bomb
_P1_KEYS = {Qt.Key_A, Qt.Key_D, Qt.Key_W, Qt.Key_S}
_P2_KEYS = {Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down}


def _rotated(points: list[QPointF], angle_deg: float) -> QPolygonF:
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return QPolygonF([
        QPointF(p.x() * cos_a - p.y() * sin_a,
                p.x() * sin_a + p.y() * cos_a)
        for p in points
    ])


def _asteroid_shape(r: int, seed: float) -> list[QPointF]:
    n = 10
    pts = []
    for i in range(n):
        angle = 360 * i / n + seed
        jitter = r * (0.75 + 0.25 * math.sin(seed * i * 1.7))
        rad = math.radians(angle)
        pts.append(QPointF(math.cos(rad) * jitter, math.sin(rad) * jitter))
    return pts


class ABRenderer(KeyHandler, QWidget):
    _TRACKED = _P1_KEYS | _P2_KEYS

    def __init__(
        self,
        state:  ABState,
        inputs: list[_Input],
        pvp:    bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._key_handler_init()
        self.state   = state
        self._inputs = inputs
        self._pvp    = pvp
        self._tick   = 0
        self.setMinimumSize(420, 350)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)

    def _sync_input(self) -> None:
        p1 = self._inputs[0]
        p1.left   = Qt.Key_A in self._held
        p1.right  = Qt.Key_D in self._held
        p1.thrust = Qt.Key_W in self._held
        p1.bomb   = Qt.Key_S in self._held

        if self._pvp and len(self._inputs) > 1:
            p2 = self._inputs[1]
            p2.left   = Qt.Key_Left  in self._held
            p2.right  = Qt.Key_Right in self._held
            p2.thrust = Qt.Key_Up    in self._held
            p2.bomb   = Qt.Key_Down  in self._held

    def _ship_label(self, i: int) -> str:
        if i == 0:
            return "P1"
        if self._pvp and i == 1:
            return "P2"
        return f"B{i}"

    def paintEvent(self, event) -> None:  # noqa: N802
        self._tick += 1
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = GamePalette.get()

        sw, sh = self.width(), self.height()
        sx = sw / FIELD_W
        sy = sh / FIELD_H

        p.fillRect(0, 0, sw, sh, pal.board_bg)

        s = self.state

        p.save()
        p.scale(sx, sy)

        # ── Explosions ────────────────────────────────────────────────────
        for exp in s.explosions:
            alpha = int(220 * exp.life / BOMB_BLAST_R)
            alpha = max(0, min(255, alpha))
            grad = QRadialGradient(exp.x, exp.y, exp.radius)
            grad.setColorAt(0.0, QColor(255, 200, 80, alpha))
            grad.setColorAt(0.5, QColor(255, 100, 20, alpha // 2))
            grad.setColorAt(1.0, QColor(255, 60,  0,  0))
            p.setBrush(grad)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(exp.x, exp.y), exp.radius, exp.radius)

        # ── Asteroids ─────────────────────────────────────────────────────
        ast_fill = pal.piece(1)
        ast_edge = pal.piece(2)
        for ast in s.asteroids:
            r = ASTEROID_SIZES[ast.size]
            poly = _rotated(_asteroid_shape(r, id(ast) % 360), ast.angle)
            poly.translate(ast.x, ast.y)
            p.setBrush(ast_fill)
            pen = QPen(ast_edge)
            pen.setWidthF(1.5 / sx)
            p.setPen(pen)
            p.drawPolygon(poly)

        # ── Bombs ─────────────────────────────────────────────────────────
        for b in s.bombs:
            fuse_frac = b.fuse / BOMB_FUSE_TICKS
            r = 4 + 3 * fuse_frac
            bomb_c = QColor(255, int(160 * fuse_frac), 0)
            p.setPen(Qt.NoPen)
            p.setBrush(bomb_c)
            p.drawEllipse(QPointF(b.x, b.y), r, r)
            ship_c = pal.piece(_SHIP_COLORS[min(b.owner, len(_SHIP_COLORS) - 1)])
            pen = QPen(ship_c)
            pen.setWidthF(1.5 / sx)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            span = int(360 * 16 * fuse_frac)
            p.drawArc(
                int(b.x - r - 3), int(b.y - r - 3),
                int((r + 3) * 2), int((r + 3) * 2),
                90 * 16, span,
            )

        # ── Ships ─────────────────────────────────────────────────────────
        for i, ship in enumerate(s.ships):
            if not ship.alive:
                continue
            if ship.invincible > 0 and (self._tick // 4) % 2 != 0:
                continue
            color_idx = _SHIP_COLORS[min(i, len(_SHIP_COLORS) - 1)]
            ship_c = pal.piece(color_idx)

            if ship.thrusting:
                flame = _rotated(_THRUSTER_POINTS, ship.angle)
                flame.translate(ship.x, ship.y)
                pen = QPen(pal.piece(1))
                pen.setWidthF(1.5 / sx)
                p.setPen(pen)
                p.setBrush(QColor(pal.piece(2).red(), pal.piece(2).green(), pal.piece(2).blue(), 180))
                p.drawPolygon(flame)

            poly = _rotated(_SHIP_POINTS, ship.angle)
            poly.translate(ship.x, ship.y)
            pen = QPen(ship_c)
            pen.setWidthF(1.5 / sx)
            p.setPen(pen)
            p.setBrush(QColor(ship_c.red(), ship_c.green(), ship_c.blue(), 60))
            p.drawPolygon(poly)

            label = self._ship_label(i)
            p.setPen(ship_c)
            p.drawText(QPointF(ship.x - 8, ship.y - 18), label)

        p.restore()

        # ── HUD ───────────────────────────────────────────────────────────
        p.setPen(pal.text_muted)
        hud_parts = []
        for i, sh in enumerate(s.ships):
            lbl = self._ship_label(i)
            status = "" if sh.alive else " (dead)"
            hud_parts.append(f"{lbl}: {sh.score}{status}")
        p.drawText(6, 18, "   ".join(hud_parts))
        if self._pvp:
            p.drawText(6, 34, "P1: A/D rotate  W thrust  S bomb     P2: ←/→ rotate  ↑ thrust  ↓ bomb")
        else:
            p.drawText(6, 34, "A/D rotate   W thrust   S bomb")

        wind_angle = math.degrees(math.atan2(s.wind_vx, -s.wind_vy)) % 360
        p.drawText(sw - 120, 18, f"Wind: {wind_angle:.0f}°")
