from __future__ import annotations

import math

from app.subapps.games_hub.games.asteroids.game_core import (
    ASTEROID_SIZES, FIELD_H, FIELD_W, AsteroidsState,
)
from app.subapps.games_hub.games.asteroids.nn_brain import NeuralNet

# Raycast directions relative to ship nose (degrees offset)
_RAY_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315]
_RAY_MAX    = math.hypot(FIELD_W, FIELD_H)
_RAY_STEP   = 4.0


def compute_inputs(s: AsteroidsState) -> list[float]:
    """Build 12-element input vector from AsteroidsState."""
    vx   = s.ship_vx / 7.0
    vy   = s.ship_vy / 7.0
    rad  = math.radians(s.ship_angle)
    sin_a = math.sin(rad)
    cos_a = math.cos(rad)
    rays  = _raycast_all(s)
    return [vx, vy, sin_a, cos_a] + rays


def _raycast_all(s: AsteroidsState) -> list[float]:
    return [
        1.0 - _nearest_along_ray(s, math.sin(math.radians(s.ship_angle + off)),
                                     -math.cos(math.radians(s.ship_angle + off))) / _RAY_MAX
        for off in _RAY_ANGLES
    ]


def _nearest_along_ray(s: AsteroidsState, dx: float, dy: float) -> float:
    t = _RAY_STEP
    while t < _RAY_MAX:
        rx = (s.ship_x + dx * t) % FIELD_W
        ry = (s.ship_y + dy * t) % FIELD_H
        for ast in s.asteroids:
            if math.hypot(rx - ast.x, ry - ast.y) < ASTEROID_SIZES[ast.size]:
                return t
        t += _RAY_STEP
    return _RAY_MAX


class AsteroidsBot:
    """Wraps a NeuralNet and maps its outputs to game actions."""

    FIRE_THRESHOLD   = 0.6
    ACTION_THRESHOLD = 0.5

    def __init__(self, net: NeuralNet) -> None:
        self.net = net

    def decide(
        self, state: AsteroidsState, with_activations: bool = False
    ) -> tuple:
        """
        Returns (rotate_left, rotate_right, thrust, fire)
        or      (rotate_left, rotate_right, thrust, fire, activations)
        when with_activations=True.
        """
        inputs = compute_inputs(state)
        if with_activations:
            out, acts = self.net.forward_with_activations(inputs)
        else:
            out  = self.net.forward(inputs)
            acts = None

        rotate_left  = out[0] > self.ACTION_THRESHOLD
        rotate_right = out[1] > self.ACTION_THRESHOLD
        thrust       = out[2] > self.ACTION_THRESHOLD
        fire         = out[3] > self.FIRE_THRESHOLD

        if with_activations:
            return rotate_left, rotate_right, thrust, fire, acts
        return rotate_left, rotate_right, thrust, fire
