from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.subapps.games_hub.games.asteroids.game import (
    ASTEROID_SIZES, FIELD_H, FIELD_W, AsteroidsState,
)
from app.subapps.games_hub.palette import GamePalette

_SHIP_POINTS = [
    QPointF(0,   -14),   # nose
    QPointF(-8,   8),    # left base
    QPointF(0,    4),    # tail notch
    QPointF(8,    8),    # right base
]
_THRUSTER_POINTS = [
    QPointF(-4,  4),
    QPointF(0,  14),
    QPointF(4,   4),
]


def _rotated(points: list[QPointF], angle_deg: float) -> QPolygonF:
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return QPolygonF([
        QPointF(p.x() * cos_a - p.y() * sin_a,
                p.x() * sin_a + p.y() * cos_a)
        for p in points
    ])


class AsteroidsRenderer(QWidget):
    def __init__(self, state: AsteroidsState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._tick = 0
        self.setMinimumSize(400, 340)
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

        p.fillRect(0, 0, sw, sh, pal.board_bg)
        s = self._state

        p.save()
        p.scale(sx, sy)

        # Asteroids — peach fill, lemon edge
        ast_fill = pal.piece(1)   # peach
        ast_edge = pal.piece(2)   # lemon
        for ast in s.asteroids:
            r = ASTEROID_SIZES[ast.size]
            poly = _rotated(_asteroid_shape(r, id(ast) % 360), ast.angle)
            poly.translate(ast.x, ast.y)
            p.setBrush(ast_fill)
            pen = QPen(ast_edge)
            pen.setWidthF(1.5 / sx)
            p.setPen(pen)
            p.drawPolygon(poly)

        # Bullets — lemon yellow
        p.setPen(Qt.NoPen)
        p.setBrush(pal.piece(2))
        for b in s.bullets:
            p.drawEllipse(QPointF(b.x, b.y), 2.5, 2.5)

        # Ship — mint green (blink when invincible)
        ship_c = pal.piece(3)
        if s.invincible == 0 or (self._tick // 4) % 2 == 0:
            if s.thrusting:
                flame = _rotated(_THRUSTER_POINTS, s.ship_angle)
                flame.translate(s.ship_x, s.ship_y)
                pen = QPen(pal.piece(1))   # peach flame
                pen.setWidthF(1.5 / sx)
                p.setPen(pen)
                p.setBrush(QColor(pal.piece(2).red(), pal.piece(2).green(), pal.piece(2).blue(), 180))
                p.drawPolygon(flame)

            ship_poly = _rotated(_SHIP_POINTS, s.ship_angle)
            ship_poly.translate(s.ship_x, s.ship_y)
            pen = QPen(ship_c)
            pen.setWidthF(1.5 / sx)
            p.setPen(pen)
            p.setBrush(QColor(ship_c.red(), ship_c.green(), ship_c.blue(), 60))
            p.drawPolygon(ship_poly)

        p.restore()

        # HUD
        p.setPen(pal.text_muted)
        p.drawText(6, 18, f"Score: {s.score}   Wave: {s.wave}   {'♥ ' * s.lives}")
        p.drawText(6, 34, "A/D rotate   W thrust   Space fire")


def _asteroid_shape(r: int, seed: float) -> list[QPointF]:
    n = 10
    pts = []
    for i in range(n):
        angle = 360 * i / n + seed
        jitter = r * (0.75 + 0.25 * math.sin(seed * i * 1.7))
        rad = math.radians(angle)
        pts.append(QPointF(math.cos(rad) * jitter, math.sin(rad) * jitter))
    return pts
