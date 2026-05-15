from __future__ import annotations

import math
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from app.subapps.games_hub.games.asteroidsbomber.game import ABState, Ship

from app.subapps.games_hub.games.asteroidsbomber.game import (
    ASTEROID_SIZES, BOMB_BLAST_R,
    BOMB_MAX_LIVE, FIELD_H, FIELD_W,
    SHIP_ACCEL, SHIP_FRICTION, SHIP_RADIUS, SHIP_ROT_SPEED,
    _Input,
)

# ── Tuning ─────────────────────────────────────────────────────────────────
DANGER_MARGIN    = 15    # extra px on top of blast radius
ASTEROID_AVOID_R = 100   # edge-to-edge distance that triggers avoidance
BOMB_FIRE_DIST   = BOMB_BLAST_R * 0.9   # fire when this close to target
LOOKAHEAD_TICKS  = 25    # how far ahead to predict positions
TURN_DEAD_ZONE   = 3.0   # degrees — ignore tiny angle errors
BRAKE_THRESHOLD  = 120   # px — start braking when this close to avoid overshooting


# ─────────────────────────────────────────────────────────────────────────
# Geometry helpers (wrap-aware)
# ─────────────────────────────────────────────────────────────────────────

def _wrap_dist(ax: float, ay: float, bx: float, by: float) -> float:
    dx = min(abs(ax - bx), FIELD_W - abs(ax - bx))
    dy = min(abs(ay - by), FIELD_H - abs(ay - by))
    return math.hypot(dx, dy)


def _wrap_delta(fx: float, fy: float, tx: float, ty: float) -> tuple[float, float]:
    """Shortest vector f → t respecting wrap."""
    dx = tx - fx
    dy = ty - fy
    if abs(dx) > FIELD_W / 2:
        dx -= math.copysign(FIELD_W, dx)
    if abs(dy) > FIELD_H / 2:
        dy -= math.copysign(FIELD_H, dy)
    return dx, dy


def _angle_diff(a: float, b: float) -> float:
    """Signed shortest rotation from a to b (degrees)."""
    d = (b - a) % 360
    return d - 360 if d > 180 else d


def _bearing(fx: float, fy: float, tx: float, ty: float) -> float:
    """Bearing f→t in degrees (0 = up, clockwise)."""
    dx, dy = _wrap_delta(fx, fy, tx, ty)
    return math.degrees(math.atan2(dx, -dy)) % 360


# ─────────────────────────────────────────────────────────────────────────
# Physics simulation helpers
# ─────────────────────────────────────────────────────────────────────────

def _future_pos(x: float, y: float, vx: float, vy: float, ticks: int) -> tuple[float, float]:
    """Predict position after `ticks` steps under friction, no thrust."""
    # Sum of geometric series: pos += vx*(1 + f + f^2 + … + f^(n-1)) = vx*(1-f^n)/(1-f)
    f = SHIP_FRICTION
    if abs(1.0 - f) < 1e-9:
        factor = ticks
    else:
        factor = (1.0 - f ** ticks) / (1.0 - f)
    fx = (x + vx * factor) % FIELD_W
    fy = (y + vy * factor) % FIELD_H
    return fx, fy


def _future_pos_asteroid(ax: float, ay: float, avx: float, avy: float,
                         ticks: int) -> tuple[float, float]:
    """Asteroids have no friction — straight line."""
    return (ax + avx * ticks) % FIELD_W, (ay + avy * ticks) % FIELD_H


# ─────────────────────────────────────────────────────────────────────────
# Threat assessment
# ─────────────────────────────────────────────────────────────────────────

def _bomb_threat_vec(state: "ABState", ship_idx: int) -> tuple[float, float, float]:
    """
    Returns (threat_level, escape_dx, escape_dy).
    threat_level > 0 means the ship is in danger.
    escape vector points away from the most dangerous bomb's predicted detonation point.
    """
    ship = state.ships[ship_idx]
    worst_threat = 0.0
    escape_dx = escape_dy = 0.0

    for b in state.bombs:
        if b.owner == ship_idx:
            continue
        # Where will the bomb detonate?
        det_x = (b.x + b.vx * b.fuse) % FIELD_W
        det_y = (b.y + b.vy * b.fuse) % FIELD_H
        # Where will the ship be at that moment (coasting, no thrust assumed)?
        ship_fx, ship_fy = _future_pos(ship.x, ship.y, ship.vx, ship.vy, b.fuse)
        dist = _wrap_dist(ship_fx, ship_fy, det_x, det_y)
        threat = (BOMB_BLAST_R + DANGER_MARGIN) - dist
        if threat > worst_threat:
            worst_threat = threat
            # Escape vector: away from detonation point at predicted ship position
            dx, dy = _wrap_delta(det_x, det_y, ship_fx, ship_fy)
            mag = math.hypot(dx, dy)
            if mag > 0:
                escape_dx, escape_dy = dx / mag, dy / mag

    return worst_threat, escape_dx, escape_dy


def _asteroid_threat_vec(state: "ABState", ship_idx: int) -> tuple[float, float, float]:
    """
    Returns (closest_edge_dist, repulse_dx, repulse_dy).
    Accounts for both ship and asteroid velocity over LOOKAHEAD_TICKS.
    """
    ship = state.ships[ship_idx]
    ship_fx, ship_fy = _future_pos(ship.x, ship.y, ship.vx, ship.vy, LOOKAHEAD_TICKS)

    closest = math.inf
    rep_dx = rep_dy = 0.0

    for a in state.asteroids:
        radius = ASTEROID_SIZES[a.size]
        ast_fx, ast_fy = _future_pos_asteroid(a.x, a.y, a.vx, a.vy, LOOKAHEAD_TICKS)
        # Edge-to-edge distance in the future
        edge_dist = _wrap_dist(ship_fx, ship_fy, ast_fx, ast_fy) - radius - SHIP_RADIUS
        if edge_dist < closest:
            closest = edge_dist
            dx, dy = _wrap_delta(ast_fx, ast_fy, ship_fx, ship_fy)
            mag = math.hypot(dx, dy)
            if mag > 0:
                rep_dx, rep_dy = dx / mag, dy / mag

    return closest, rep_dx, rep_dy


# ─────────────────────────────────────────────────────────────────────────
# Steering primitives
# ─────────────────────────────────────────────────────────────────────────

def _set_keys(inp: "_Input", left: bool, right: bool, thrust: bool) -> None:
    inp.left   = left
    inp.right  = right
    inp.thrust = thrust


def _steer_to_angle(ship: "Ship", inp: "_Input", desired_angle: float, thrust: bool) -> None:
    diff = _angle_diff(ship.angle, desired_angle)
    left  = diff < -TURN_DEAD_ZONE
    right = diff > TURN_DEAD_ZONE
    _set_keys(inp, left, right, thrust)


def _steer_toward_point(ship: "Ship", inp: "_Input", tx: float, ty: float, *,
                         allow_thrust: bool = True, brake: bool = False) -> None:
    dist = _wrap_dist(ship.x, ship.y, tx, ty)
    desired = _bearing(ship.x, ship.y, tx, ty)
    diff = _angle_diff(ship.angle, desired)

    if brake and dist < BRAKE_THRESHOLD:
        vspeed = math.hypot(ship.vx, ship.vy)
        if vspeed > 1.5:
            vel_bearing = math.degrees(math.atan2(ship.vx, -ship.vy)) % 360
            vel_toward = abs(_angle_diff(vel_bearing, desired)) < 90
            if vel_toward and vspeed > 2.0:
                brake_angle = (vel_bearing + 180) % 360
                _steer_to_angle(ship, inp, brake_angle, thrust=True)
                return

    thrust = allow_thrust and abs(diff) < 50
    _steer_to_angle(ship, inp, desired, thrust)


def _steer_along_vector(ship: "Ship", inp: "_Input", dx: float, dy: float) -> None:
    angle = math.degrees(math.atan2(dx, -dy)) % 360
    _steer_to_angle(ship, inp, angle, thrust=True)


# ─────────────────────────────────────────────────────────────────────────
# Intercept prediction for hunting
# ─────────────────────────────────────────────────────────────────────────

def _intercept_point(ship: "Ship", target: "Ship") -> tuple[float, float]:
    """
    Estimate where to aim to intercept the target.
    Simple: project target position LOOKAHEAD_TICKS ahead (coasting),
    then steer toward that point.
    """
    # Use half lookahead so we don't over-lead at close range
    dist = _wrap_dist(ship.x, ship.y, target.x, target.y)
    lead = max(8, min(LOOKAHEAD_TICKS, int(dist / 6)))
    tx, ty = _future_pos(target.x, target.y, target.vx, target.vy, lead)
    return tx, ty


# ─────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────

def bot_act(state: "ABState", bot_idx: int, inp: "_Input", place_bomb: Callable[[], None]) -> None:
    """Called once per game tick for each bot ship."""
    ship = state.ships[bot_idx]
    if not ship.alive:
        return

    # ── Phase 0: Evade predicted bomb blast ───────────────────────────────
    threat_level, esc_dx, esc_dy = _bomb_threat_vec(state, bot_idx)
    if threat_level > 0:
        _steer_along_vector(ship, inp, esc_dx, esc_dy)
        return

    # ── Phase 1: Avoid asteroids (velocity-predictive) ────────────────────
    ast_edge_dist, rep_dx, rep_dy = _asteroid_threat_vec(state, bot_idx)
    if ast_edge_dist < ASTEROID_AVOID_R:
        _steer_along_vector(ship, inp, rep_dx, rep_dy)
        return

    # ── Phase 2: Hunt closest enemy ───────────────────────────────────────
    target = _pick_target(state, bot_idx)
    if target is None:
        _set_keys(inp, False, False, False)
        return

    dist = _wrap_dist(ship.x, ship.y, target.x, target.y)

    if (dist < BOMB_FIRE_DIST
            and ship.bomb_cooldown == 0
            and ship.bombs_live < BOMB_MAX_LIVE
            and dist > BOMB_BLAST_R * 1.15):
        place_bomb()

    tx, ty = _intercept_point(ship, target)
    _steer_toward_point(ship, inp, tx, ty, allow_thrust=True, brake=True)


def _pick_target(state: "ABState", bot_idx: int):
    """Return the nearest alive non-self ship, or None."""
    ship = state.ships[bot_idx]
    best_d = math.inf
    best   = None
    for i, s in enumerate(state.ships):
        if i == bot_idx or not s.alive:
            continue
        d = _wrap_dist(ship.x, ship.y, s.x, s.y)
        if d < best_d:
            best_d = d
            best   = s
    return best
