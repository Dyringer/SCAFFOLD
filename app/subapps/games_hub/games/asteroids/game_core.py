from __future__ import annotations

import math
import random
from dataclasses import dataclass

FIELD_W = 600
FIELD_H = 500

SHIP_ACCEL     = 0.25
SHIP_FRICTION  = 0.98
SHIP_ROT_SPEED = 4.0    # degrees per tick
MAX_SPEED      = 7.0

BULLET_SPEED = 9.0
BULLET_LIFE  = 45       # ticks
MAX_BULLETS  = 4
FIRE_COOLDOWN_TICKS = 16

ASTEROID_SIZES = [40, 22, 12]   # radii by size index
ASTEROID_SCORE = [20, 50, 100]  # points by size index (large→small)
INITIAL_ASTEROIDS = 4

INVINCIBLE_TICKS = 120
LIVES_START = 3

TICK_MS = 16


# ---------------------------------------------------------------------------
# Entities

@dataclass
class Bullet:
    x: float
    y: float
    vx: float
    vy: float
    life: int = BULLET_LIFE


@dataclass
class Asteroid:
    x: float
    y: float
    vx: float
    vy: float
    angle: float
    rot_speed: float
    size: int           # index into ASTEROID_SIZES


@dataclass
class InputState:
    left:   bool = False
    right:  bool = False
    thrust: bool = False
    fire:   bool = False


@dataclass
class AsteroidsState:
    ship_x: float
    ship_y: float
    ship_vx: float
    ship_vy: float
    ship_angle: float   # degrees, 0 = up
    bullets: list[Bullet]
    asteroids: list[Asteroid]
    score: int = 0
    lives: int = LIVES_START
    invincible: int = 0
    thrusting: bool = False
    wave: int = 1

    @staticmethod
    def new() -> "AsteroidsState":
        s = AsteroidsState(
            ship_x=FIELD_W / 2, ship_y=FIELD_H / 2,
            ship_vx=0, ship_vy=0, ship_angle=0,
            bullets=[], asteroids=[],
        )
        s.asteroids = spawn_wave(1)
        return s


# ---------------------------------------------------------------------------
# Wave / split helpers

def spawn_wave(wave: int) -> list[Asteroid]:
    count = INITIAL_ASTEROIDS + wave - 1
    asteroids = []
    cx, cy = FIELD_W / 2, FIELD_H / 2
    for _ in range(count):
        angle = random.uniform(0, 360)
        dist  = random.uniform(120, 200)
        x = (cx + math.cos(math.radians(angle)) * dist) % FIELD_W
        y = (cy + math.sin(math.radians(angle)) * dist) % FIELD_H
        speed = random.uniform(0.6, 1.4) * (1 + (wave - 1) * 0.15)
        va = random.uniform(0, 360)
        asteroids.append(Asteroid(
            x=x, y=y,
            vx=math.cos(math.radians(va)) * speed,
            vy=math.sin(math.radians(va)) * speed,
            angle=random.uniform(0, 360),
            rot_speed=random.uniform(-0.5, 0.5),
            size=0,
        ))
    return asteroids


def split_asteroid(ast: Asteroid) -> list[Asteroid]:
    if ast.size >= len(ASTEROID_SIZES) - 1:
        return []
    children = []
    for _ in range(2):
        va = random.uniform(0, 360)
        speed = random.uniform(1.0, 2.5)
        children.append(Asteroid(
            x=ast.x, y=ast.y,
            vx=math.cos(math.radians(va)) * speed,
            vy=math.sin(math.radians(va)) * speed,
            angle=ast.angle,
            rot_speed=random.uniform(-3, 3),
            size=ast.size + 1,
        ))
    return children


# ---------------------------------------------------------------------------
# Physics step — pure function, no Qt, no signals

class HitEvent:
    """Emitted when a bullet destroys an asteroid."""
    __slots__ = ("points",)
    def __init__(self, points: int) -> None:
        self.points = points


class DeathEvent:
    """Emitted when the ship collides with an asteroid."""
    __slots__ = ()


class GameOverEvent:
    """Emitted when lives reach zero."""
    __slots__ = ()


class WaveCompleteEvent:
    """Emitted when all asteroids are cleared."""
    __slots__ = ("new_wave",)
    def __init__(self, new_wave: int) -> None:
        self.new_wave = new_wave


def step(
    s: AsteroidsState,
    inp: InputState,
    fire_cooldown: int,
) -> tuple[int, list]:
    """
    Advance game state by one tick.

    Returns (new_fire_cooldown, events) where events is a list of
    HitEvent / DeathEvent / GameOverEvent / WaveCompleteEvent instances.
    """
    events: list = []

    # Fire cooldown
    if fire_cooldown > 0:
        fire_cooldown -= 1

    # Rotate
    if inp.left:
        s.ship_angle -= SHIP_ROT_SPEED
    if inp.right:
        s.ship_angle += SHIP_ROT_SPEED

    # Thrust
    s.thrusting = inp.thrust
    if inp.thrust:
        rad = math.radians(s.ship_angle)
        s.ship_vx += math.sin(rad) * SHIP_ACCEL
        s.ship_vy -= math.cos(rad) * SHIP_ACCEL
        speed = math.hypot(s.ship_vx, s.ship_vy)
        if speed > MAX_SPEED:
            s.ship_vx = s.ship_vx / speed * MAX_SPEED
            s.ship_vy = s.ship_vy / speed * MAX_SPEED

    # Friction
    s.ship_vx *= SHIP_FRICTION
    s.ship_vy *= SHIP_FRICTION

    # Move ship
    s.ship_x = (s.ship_x + s.ship_vx) % FIELD_W
    s.ship_y = (s.ship_y + s.ship_vy) % FIELD_H

    # Invincibility countdown
    if s.invincible > 0:
        s.invincible -= 1

    # Fire — held flag, cooldown throttles rate
    if inp.fire and fire_cooldown == 0 and len(s.bullets) < MAX_BULLETS:
        rad = math.radians(s.ship_angle)
        s.bullets.append(Bullet(
            x=s.ship_x + math.sin(rad) * 14,
            y=s.ship_y - math.cos(rad) * 14,
            vx=s.ship_vx + math.sin(rad) * BULLET_SPEED,
            vy=s.ship_vy - math.cos(rad) * BULLET_SPEED,
        ))
        fire_cooldown = FIRE_COOLDOWN_TICKS

    # Move bullets
    s.bullets = [b for b in s.bullets if b.life > 0]
    for b in s.bullets:
        b.x = (b.x + b.vx) % FIELD_W
        b.y = (b.y + b.vy) % FIELD_H
        b.life -= 1

    # Move asteroids
    for a in s.asteroids:
        a.x = (a.x + a.vx) % FIELD_W
        a.y = (a.y + a.vy) % FIELD_H
        a.angle += a.rot_speed

    # Bullet vs asteroid collisions
    new_asteroids: list[Asteroid] = []
    hit_bullets: set[int] = set()
    for ast in s.asteroids:
        radius = ASTEROID_SIZES[ast.size]
        hit = False
        for bi, b in enumerate(s.bullets):
            if bi in hit_bullets:
                continue
            if math.hypot(b.x - ast.x, b.y - ast.y) < radius:
                hit = True
                hit_bullets.add(bi)
                pts = ASTEROID_SCORE[ast.size]
                s.score += pts
                events.append(HitEvent(pts))
                new_asteroids.extend(split_asteroid(ast))
                break
        if not hit:
            new_asteroids.append(ast)

    s.bullets = [b for i, b in enumerate(s.bullets) if i not in hit_bullets]
    s.asteroids = new_asteroids

    # Ship vs asteroid collisions
    if s.invincible == 0:
        ship_r = 10
        for ast in s.asteroids:
            if math.hypot(s.ship_x - ast.x, s.ship_y - ast.y) < ASTEROID_SIZES[ast.size] + ship_r:
                s.lives -= 1
                if s.lives <= 0:
                    events.append(GameOverEvent())
                    return fire_cooldown, events
                s.ship_x, s.ship_y = FIELD_W / 2, FIELD_H / 2
                s.ship_vx = s.ship_vy = 0
                s.invincible = INVINCIBLE_TICKS
                s.bullets.clear()
                events.append(DeathEvent())
                break

    # Wave complete
    if not s.asteroids:
        s.wave += 1
        s.asteroids = spawn_wave(s.wave)
        s.ship_x, s.ship_y = FIELD_W / 2, FIELD_H / 2
        s.ship_vx = s.ship_vy = 0
        s.invincible = INVINCIBLE_TICKS
        events.append(WaveCompleteEvent(s.wave))

    return fire_cooldown, events
