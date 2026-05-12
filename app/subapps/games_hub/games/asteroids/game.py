from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import Action, BaseGame, GameMode, GameState, PlayerSlot
from app.subapps.games_hub.ui import register_game

FIELD_W = 600
FIELD_H = 500

SHIP_ACCEL    = 0.25
SHIP_FRICTION = 0.98
SHIP_ROT_SPEED = 4.0   # degrees per tick (~240 deg/sec at 60 fps)
MAX_SPEED     = 7.0

BULLET_SPEED  = 9.0
BULLET_LIFE   = 45     # ticks

ASTEROID_SIZES = [40, 22, 12]   # radii
ASTEROID_SCORE = [20, 50, 100]
INITIAL_ASTEROIDS = 4

INVINCIBLE_TICKS = 120  # after respawn
LIVES_START = 3

TICK_MS = 16


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
    size: int       # index into ASTEROID_SIZES


@dataclass
class AsteroidsState:
    ship_x: float
    ship_y: float
    ship_vx: float
    ship_vy: float
    ship_angle: float       # degrees, 0 = up
    bullets: list[Bullet]
    asteroids: list[Asteroid]
    score: int = 0
    lives: int = LIVES_START
    invincible: int = 0     # ticks remaining
    thrusting: bool = False
    wave: int = 1

    @staticmethod
    def new() -> "AsteroidsState":
        s = AsteroidsState(
            ship_x=FIELD_W / 2, ship_y=FIELD_H / 2,
            ship_vx=0, ship_vy=0, ship_angle=0,
            bullets=[], asteroids=[],
        )
        s.asteroids = _spawn_wave(1)
        return s


def _spawn_wave(wave: int) -> list[Asteroid]:
    count = INITIAL_ASTEROIDS + wave - 1
    asteroids = []
    cx, cy = FIELD_W / 2, FIELD_H / 2
    for _ in range(count):
        # Spawn away from centre
        angle = random.uniform(0, 360)
        dist = random.uniform(120, 200)
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


def _split(ast: Asteroid) -> list[Asteroid]:
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


@register_game
class AsteroidsGame(BaseGame):
    game_id = "asteroids"
    display_name = "Asteroids"
    icon_char = "☄️"
    max_players = 1
    supports_lan = False

    def __init__(self) -> None:
        super().__init__()
        self._state = AsteroidsState.new()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._widget: QWidget | None = None
        self._held_left = False
        self._held_right = False
        self._held_thrust = False
        self._fire_cooldown = 0

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.asteroids.renderer import AsteroidsRenderer
        self._widget = AsteroidsRenderer(self._state)
        return self._widget

    def start(self, mode: GameMode, players: dict[PlayerSlot, str]) -> None:
        self._state = AsteroidsState.new()
        self._held_left = self._held_right = self._held_thrust = False
        self._fire_cooldown = 0
        if self._widget is not None:
            self._widget._state = self._state  # type: ignore[attr-defined]
        super().start(mode, players)
        self._timer.start()

    def pause(self) -> None:
        self._timer.stop()
        super().pause()

    def resume(self) -> None:
        super().resume()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        super().stop()

    def key_press(self, action: Action, slot: PlayerSlot) -> None:
        if self._game_state != GameState.RUNNING:
            return
        if action == Action.LEFT:   self._held_left  = True
        elif action == Action.RIGHT: self._held_right = True
        elif action == Action.UP:    self._held_thrust = True
        elif action == Action.FIRE:  self._try_fire()

    def key_release(self, action: Action, slot: PlayerSlot) -> None:
        if action == Action.LEFT:   self._held_left  = False
        elif action == Action.RIGHT: self._held_right = False
        elif action == Action.UP:    self._held_thrust = False

    def get_state(self) -> dict:
        s = self._state
        return {"ship_x": s.ship_x, "ship_y": s.ship_y, "score": s.score, "lives": s.lives}

    # ------------------------------------------------------------------

    def _try_fire(self) -> None:
        if self._fire_cooldown > 0 or len(self._state.bullets) >= 4:
            return
        s = self._state
        rad = math.radians(s.ship_angle)
        s.bullets.append(Bullet(
            x=s.ship_x + math.sin(rad) * 14,
            y=s.ship_y - math.cos(rad) * 14,
            vx=s.ship_vx + math.sin(rad) * BULLET_SPEED,
            vy=s.ship_vy - math.cos(rad) * BULLET_SPEED,
        ))
        self._fire_cooldown = 8

    def _tick(self) -> None:
        s = self._state

        if self._fire_cooldown > 0:
            self._fire_cooldown -= 1

        # Rotate
        if self._held_left:
            s.ship_angle -= SHIP_ROT_SPEED
        if self._held_right:
            s.ship_angle += SHIP_ROT_SPEED

        # Thrust
        s.thrusting = self._held_thrust
        if self._held_thrust:
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

        # Move ship (wrap)
        s.ship_x = (s.ship_x + s.ship_vx) % FIELD_W
        s.ship_y = (s.ship_y + s.ship_vy) % FIELD_H

        if s.invincible > 0:
            s.invincible -= 1

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

        # Bullet vs asteroid
        new_asteroids: list[Asteroid] = []
        hit_bullets: set[int] = set()
        for ai, ast in enumerate(s.asteroids):
            radius = ASTEROID_SIZES[ast.size]
            hit = False
            for bi, b in enumerate(s.bullets):
                if bi in hit_bullets:
                    continue
                if math.hypot(b.x - ast.x, b.y - ast.y) < radius:
                    hit = True
                    hit_bullets.add(bi)
                    s.score += ASTEROID_SCORE[ast.size]
                    self.score_tick.emit({"p1": s.score})
                    new_asteroids.extend(_split(ast))
                    break
            if not hit:
                new_asteroids.append(ast)

        s.bullets = [b for i, b in enumerate(s.bullets) if i not in hit_bullets]
        s.asteroids = new_asteroids

        # Ship vs asteroid
        if s.invincible == 0:
            ship_r = 10
            for ast in s.asteroids:
                if math.hypot(s.ship_x - ast.x, s.ship_y - ast.y) < ASTEROID_SIZES[ast.size] + ship_r:
                    s.lives -= 1
                    if s.lives <= 0:
                        self._timer.stop()
                        self._set_state(GameState.OVER)
                        self.game_over.emit({"p1": s.score})
                        return
                    # Respawn
                    s.ship_x, s.ship_y = FIELD_W / 2, FIELD_H / 2
                    s.ship_vx = s.ship_vy = 0
                    s.invincible = INVINCIBLE_TICKS
                    s.bullets.clear()
                    break

        # Next wave
        if not s.asteroids:
            s.wave += 1
            s.asteroids = _spawn_wave(s.wave)
            s.ship_x, s.ship_y = FIELD_W / 2, FIELD_H / 2
            s.ship_vx = s.ship_vy = 0
            s.invincible = INVINCIBLE_TICKS

        if self._widget is not None:
            self._widget.update()
