from __future__ import annotations

import math

from app.subapps.games_hub.games.asteroids.game_core import (
    ASTEROID_SIZES, BULLET_SPEED, FIELD_H, FIELD_W, FIRE_COOLDOWN_TICKS, AsteroidsState,
)
from app.subapps.games_hub.games.asteroids.nn_brain import NeuralNet

# Danger raycasts: 12 evenly-spaced (every 30°) covering the full 360°.
_RAY_ANGLES = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]

# Half-field diagonal — max meaningful distance on a toroidal field
_RAY_MAX = math.hypot(FIELD_W / 2, FIELD_H / 2)


def compute_inputs(s: AsteroidsState, fire_cooldown: int = 0) -> list[float]:
    """Build 25-element input vector.

    Movement (4)
    [0]  sin of ship velocity direction  (0 if stationary)
    [1]  cos of ship velocity direction  (1 if stationary — "forward" default)
    [2]  speed normalised to [0, 1]
    [3]  gun_ready: 1.0 = can fire now, 0.0 = just fired

    Danger — 12 raycasts at 30° intervals (4–15)
    [4-15]  1.0 = asteroid touching ship, 0.0 = nothing within _RAY_MAX

    Gun-line target (3)
    [16] target_dist: normalised distance to asteroid in gun sights (0=far, 1=touching)
    [17] target_size: 0=small  0.5=medium  1.0=large
    [18] target_approach: positive = that asteroid is closing in on ship

    Threat bearing (2)
    [19] sin of bearing from ship nose to nearest/most-dangerous asteroid (ship-local frame)
    [20] cos of bearing  (1.0 = straight ahead, -1.0 = behind)

    Threat approach speed (1)
    [21] threat_approach: normalised dot-product of threat velocity toward ship (-1=fleeing, 1=charging)

    Shooting state (1)
    [22] bullet_on_target: 1.0 if a bullet is already heading for the gun-line target

    Lead angle to priority target (2)
    [23] sin of bearing from ship nose to bullet-intercept point of priority target
    [24] cos of bearing  (1.0 = dead ahead, fire now)
    """
    # ------------------------------------------------------------------
    # Movement sensors
    speed = math.hypot(s.ship_vx, s.ship_vy)
    if speed > 1e-6:
        sin_vel = s.ship_vx / speed
        cos_vel = -s.ship_vy / speed   # -vy because y axis is flipped (up = negative)
    else:
        sin_vel, cos_vel = 0.0, 1.0

    speed_n   = min(speed / 7.0, 1.0)
    gun_ready = 1.0 - (fire_cooldown / FIRE_COOLDOWN_TICKS)

    # ------------------------------------------------------------------
    # Danger raycasts
    rays = _raycast_all(s)

    # ------------------------------------------------------------------
    # Ship orientation (needed to transform world vectors to ship-local frame)
    rad   = math.radians(s.ship_angle)
    sin_a = math.sin(rad)
    cos_a = math.cos(rad)

    if not s.asteroids:
        return ([sin_vel, cos_vel, speed_n, gun_ready]
                + rays
                + [0.0, 0.0, 0.0,   # gun-line target
                   0.0, 1.0,         # threat bearing (default: ahead)
                   0.0,              # threat approach speed
                   0.0,              # bullet_on_target
                   0.0, 1.0])        # lead angle (default: dead ahead)

    # ------------------------------------------------------------------
    # Gun-line target: asteroid the forward ray would hit right now
    gun_target = _gun_line_target(s, sin_a, cos_a)

    if gun_target is not None:
        ast, gt_dx, gt_dy, gt_dist = gun_target
        target_dist     = max(0.0, 1.0 - gt_dist / _RAY_MAX)
        # ast.size is 0=large..N-1=small; invert so 1.0=large, 0.0=small
        target_size     = 1.0 - ast.size / (len(ASTEROID_SIZES) - 1)
        gt_nx, gt_ny    = gt_dx / gt_dist, gt_dy / gt_dist
        target_approach = -(ast.vx * gt_nx + ast.vy * gt_ny) / 3.0
        target_approach = max(-1.0, min(1.0, target_approach))
        bullet_on_tgt   = _bullet_heading_for(s, gt_dx, gt_dy, gt_dist)
    else:
        target_dist     = 0.0
        target_size     = 0.0
        target_approach = 0.0
        bullet_on_tgt   = 0.0

    # ------------------------------------------------------------------
    # Threat bearing: most dangerous asteroid = closest weighted by size
    threat       = _most_dangerous(s)
    th_dx, th_dy = _toroidal_wrap(threat.x - s.ship_x, threat.y - s.ship_y)
    th_d         = math.hypot(th_dx, th_dy) or 1e-6
    th_nx, th_ny = th_dx / th_d, th_dy / th_d
    # Rotate into ship-local frame: x=right, y=forward
    threat_sin = th_nx * sin_a + th_ny * (-cos_a)
    threat_cos = th_nx * cos_a + th_ny * sin_a
    # Threat approach speed: positive = charging toward ship
    threat_approach = max(-1.0, min(1.0, -(threat.vx * th_nx + threat.vy * th_ny) / 3.0))

    # ------------------------------------------------------------------
    # Lead angle: bearing to bullet-intercept point of priority target
    lead_sin, lead_cos = _lead_angle(s, sin_a, cos_a)

    return ([sin_vel, cos_vel, speed_n, gun_ready]
            + rays
            + [target_dist, target_size, target_approach,
               threat_sin, threat_cos,
               threat_approach,
               bullet_on_tgt,
               lead_sin, lead_cos])


# ---------------------------------------------------------------------------
# Helpers

def _toroidal_wrap(dx: float, dy: float) -> tuple[float, float]:
    if dx >  FIELD_W / 2: dx -= FIELD_W
    if dx < -FIELD_W / 2: dx += FIELD_W
    if dy >  FIELD_H / 2: dy -= FIELD_H
    if dy < -FIELD_H / 2: dy += FIELD_H
    return dx, dy


def _toroidal_dist(dx: float, dy: float) -> float:
    dx = abs(dx); dy = abs(dy)
    if dx > FIELD_W / 2: dx = FIELD_W - dx
    if dy > FIELD_H / 2: dy = FIELD_H - dy
    return math.hypot(dx, dy)


def _gun_line_target(s: AsteroidsState, sin_a: float, cos_a: float):
    """Return (asteroid, dx, dy, dist) for the asteroid the gun is aimed at, or None."""
    best_t = _RAY_MAX
    result = None
    ox, oy = s.ship_x, s.ship_y
    for ast in s.asteroids:
        r = ASTEROID_SIZES[ast.size]
        for wx in (ast.x, ast.x - FIELD_W, ast.x + FIELD_W):
            for wy in (ast.y, ast.y - FIELD_H, ast.y + FIELD_H):
                cx, cy = wx - ox, wy - oy
                t_proj = cx * sin_a + cy * (-cos_a)
                if t_proj < 0:
                    continue
                perp2 = cx * cx + cy * cy - t_proj * t_proj
                if perp2 >= r * r:
                    continue
                t_hit = t_proj - math.sqrt(r * r - perp2)
                if 0 < t_hit < best_t:
                    best_t = t_hit
                    result = (ast, cx, cy, math.hypot(cx, cy))
    return result


def _most_dangerous(s: AsteroidsState):
    """Nearest asteroid weighted by size (large = more dangerous)."""
    def danger(a):
        d = _toroidal_dist(a.x - s.ship_x, a.y - s.ship_y)
        return d / (ASTEROID_SIZES[a.size] + 1)
    return min(s.asteroids, key=danger)


def _bullet_heading_for(s: AsteroidsState, tgt_dx: float, tgt_dy: float, tgt_dist: float) -> float:
    """1.0 if any bullet is flying within ~20° of the target direction, else 0.0."""
    if not s.bullets or tgt_dist < 1e-6:
        return 0.0
    tgt_nx = tgt_dx / tgt_dist
    tgt_ny = tgt_dy / tgt_dist
    for b in s.bullets:
        bspeed = math.hypot(b.vx, b.vy) or 1e-6
        dot = (b.vx / bspeed) * tgt_nx + (b.vy / bspeed) * tgt_ny
        if dot > 0.94:   # cos(20°) ≈ 0.94
            return 1.0
    return 0.0


def _raycast_all(s: AsteroidsState) -> list[float]:
    rad = math.radians(s.ship_angle)
    return [
        max(0.0, 1.0 - _ray_hit_distance(
            s,
            math.sin(rad + math.radians(off)),
            -math.cos(rad + math.radians(off)),
        ) / _RAY_MAX)
        for off in _RAY_ANGLES
    ]


def _ray_hit_distance(s: AsteroidsState, rdx: float, rdy: float) -> float:
    best = _RAY_MAX
    ox, oy = s.ship_x, s.ship_y
    for ast in s.asteroids:
        r = ASTEROID_SIZES[ast.size]
        for wx in (ast.x, ast.x - FIELD_W, ast.x + FIELD_W):
            for wy in (ast.y, ast.y - FIELD_H, ast.y + FIELD_H):
                cx, cy = wx - ox, wy - oy
                t_proj = cx * rdx + cy * rdy
                if t_proj < 0:
                    continue
                perp2 = cx * cx + cy * cy - t_proj * t_proj
                if perp2 >= r * r:
                    continue
                t_hit = t_proj - math.sqrt(r * r - perp2)
                if 0 < t_hit < best:
                    best = t_hit
    return best


def _lead_angle(s: AsteroidsState, sin_a: float, cos_a: float) -> tuple[float, float]:
    """Bearing (ship-local sin/cos) to the bullet-intercept point of the priority target.

    Uses the quadratic intercept formula: find time t such that
    |ast_pos + ast_vel*t - bullet_origin| == BULLET_SPEED * t,
    then return the bearing to that intercept point.
    Returns (0, 1) — dead ahead — when no solution exists.
    """
    if not s.asteroids:
        return 0.0, 1.0

    # Priority target: gun-line target if available, else most dangerous
    gun = _gun_line_target(s, sin_a, cos_a)
    ast = gun[0] if gun is not None else _most_dangerous(s)

    # Solve |rel_pos + rel_vel*t|² == BULLET_SPEED² * t² for t.
    # Ship drift in bullet velocity is ignored (good approximation since
    # BULLET_SPEED ≫ MAX_SPEED).
    rx, ry = _toroidal_wrap(ast.x - s.ship_x, ast.y - s.ship_y)
    rvx = ast.vx - s.ship_vx
    rvy = ast.vy - s.ship_vy

    a = rvx * rvx + rvy * rvy - BULLET_SPEED * BULLET_SPEED
    b = 2.0 * (rx * rvx + ry * rvy)
    c = rx * rx + ry * ry

    t = _earliest_positive_root(a, b, c)

    if t is None:
        ix, iy = rx, ry              # no valid intercept → direct bearing
    else:
        ix = rx + ast.vx * t
        iy = ry + ast.vy * t

    id_ = math.hypot(ix, iy) or 1e-6
    inx, iny = ix / id_, iy / id_
    lead_sin = inx * sin_a + iny * (-cos_a)
    lead_cos = inx * cos_a + iny * sin_a
    return lead_sin, lead_cos


def _earliest_positive_root(a: float, b: float, c: float) -> float | None:
    """Smallest positive t such that a*t² + b*t + c == 0, or None."""
    if abs(a) < 1e-9:
        if abs(b) < 1e-9:
            return None
        t = -c / b
        return t if t > 0 else None

    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    sq = math.sqrt(disc)
    t1 = (-b - sq) / (2.0 * a)
    t2 = (-b + sq) / (2.0 * a)
    candidates = [t for t in (t1, t2) if t > 0]
    return min(candidates) if candidates else None


class AsteroidsBot:
    """Wraps a NeuralNet and maps its outputs to game actions."""

    def __init__(self, net: NeuralNet) -> None:
        self.net = net

    def decide(self, state: AsteroidsState, fire_cooldown: int = 0) -> tuple[bool, bool, bool, bool]:
        return _outputs_to_actions(self.net.forward(compute_inputs(state, fire_cooldown)))

    def decide_with_activations(
        self, state: AsteroidsState, fire_cooldown: int = 0,
    ) -> tuple[bool, bool, bool, bool, list[list[float]]]:
        out, acts = self.net.forward_with_activations(compute_inputs(state, fire_cooldown))
        return (*_outputs_to_actions(out), acts)


def _outputs_to_actions(out: list[float]) -> tuple[bool, bool, bool, bool]:
    # Each output is a tanh in [-1, 1]; positive means "do this action".
    return out[0] > 0.0, out[1] > 0.0, out[2] > 0.0, out[3] > 0.0
