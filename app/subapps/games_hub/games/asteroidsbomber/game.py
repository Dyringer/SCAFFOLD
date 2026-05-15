from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import BaseGame, GameMode, GameResult, GameState
from app.subapps.games_hub.ui import register_game

FIELD_W = 700
FIELD_H = 550

SHIP_ACCEL     = 0.25
SHIP_FRICTION  = 0.98
SHIP_ROT_SPEED = 4.0
MAX_SPEED      = 7.0
SHIP_RADIUS    = 10

BOMB_SPEED       = 1.8
BOMB_FUSE_TICKS  = 180
BOMB_BLAST_R     = 70
BOMB_MAX_LIVE    = 2
BOMB_COOLDOWN    = 40

ASTEROID_SIZES   = [40, 22, 12]
ASTEROID_COUNT   = 10
ASTEROID_SPEED   = 1.2

EXPLOSION_TICKS  = 40

TICK_MS = 16


@dataclass
class _Input:
    left:   bool = False
    right:  bool = False
    thrust: bool = False
    bomb:   bool = False


@dataclass
class Ship:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    angle: float = 0.0
    alive: bool = True
    invincible: int = 90
    thrusting: bool = False
    bombs_live: int = 0
    bomb_cooldown: int = 0
    score: int = 0


@dataclass
class Bomb:
    x: float
    y: float
    vx: float
    vy: float
    owner: int
    fuse: int = BOMB_FUSE_TICKS


@dataclass
class Explosion:
    x: float
    y: float
    radius: float
    life: int = EXPLOSION_TICKS


@dataclass
class Asteroid:
    x: float
    y: float
    vx: float
    vy: float
    angle: float
    rot_speed: float
    size: int


@dataclass
class ABState:
    ships: list[Ship]
    bombs: list[Bomb]
    explosions: list[Explosion]
    asteroids: list[Asteroid]
    wind_vx: float = 0.0
    wind_vy: float = 0.0
    tick: int = 0

    @staticmethod
    def new(num_extra_ships: int) -> "ABState":
        wind_angle = random.uniform(0, 360)
        wvx = math.cos(math.radians(wind_angle)) * ASTEROID_SPEED
        wvy = math.sin(math.radians(wind_angle)) * ASTEROID_SPEED

        ship_count = 1 + num_extra_ships
        ships = []
        for i in range(ship_count):
            a = 360 * i / ship_count
            r = 160
            ships.append(Ship(
                x=FIELD_W / 2 + math.cos(math.radians(a)) * r,
                y=FIELD_H / 2 + math.sin(math.radians(a)) * r,
                angle=a + 90,
            ))

        asteroids = _spawn_asteroids(wvx, wvy, ships)
        return ABState(ships=ships, bombs=[], explosions=[], asteroids=asteroids,
                       wind_vx=wvx, wind_vy=wvy)


def _spawn_asteroids(wvx: float, wvy: float, ships: list[Ship]) -> list[Asteroid]:
    asts = []
    for _ in range(ASTEROID_COUNT):
        size = random.choices([0, 1, 2], weights=[3, 3, 4])[0]
        for _ in range(20):
            x = random.uniform(20, FIELD_W - 20)
            y = random.uniform(20, FIELD_H - 20)
            if all(math.hypot(x - s.x, y - s.y) > 100 for s in ships):
                break
        asts.append(Asteroid(
            x=x, y=y, vx=wvx, vy=wvy,
            angle=random.uniform(0, 360),
            rot_speed=random.uniform(-1.5, 1.5),
            size=size,
        ))
    return asts


class _ABBase(BaseGame):
    """Shared physics for both AsteroidsBomber variants."""

    game_id   = "asteroidsbomber"
    icon_char = "💣"

    def __init__(self, pvp: bool) -> None:
        super().__init__()
        self._pvp    = pvp
        self._state  = ABState.new(1)
        self._inputs: list[_Input] = [_Input(), _Input()]
        self._bomb_held: list[bool] = [False, False]
        self._timer  = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timers.append(self._timer)
        self._widget: QWidget | None = None

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.asteroidsbomber.renderer import ABRenderer
        self._widget = ABRenderer(self._state, self._inputs, pvp=self._pvp)
        return self._widget

    def start(self, mode: GameMode, players: dict[int, str]) -> None:
        self._state = ABState.new(1)
        for inp in self._inputs:
            inp.left = inp.right = inp.thrust = inp.bomb = False
        self._bomb_held = [False, False]
        if self._widget is not None:
            self._widget.state = self._state
            self._widget.clear_held()
        super().start(mode, players)
        self._timer.start()

    def _tick(self) -> None:
        s = self._state
        s.tick += 1

        for i, ship in enumerate(s.ships):
            if ship.alive:
                inp = self._inputs[i] if i < len(self._inputs) else _Input()
                _move_ship(ship, inp)

        self._drive_non_player_ships()

        # Rising-edge bomb for human-controlled ships
        self._handle_bombs()

        for b in s.bombs:
            b.x = (b.x + b.vx) % FIELD_W
            b.y = (b.y + b.vy) % FIELD_H
            b.fuse -= 1

        detonated: list[int] = [i for i, b in enumerate(s.bombs) if b.fuse <= 0]
        for idx in sorted(detonated, reverse=True):
            b = s.bombs.pop(idx)
            s.ships[b.owner].bombs_live = max(0, s.ships[b.owner].bombs_live - 1)
            self._detonate(b.x, b.y, b.owner)

        s.explosions = [e for e in s.explosions if e.life > 0]
        for e in s.explosions:
            e.life -= 1

        for a in s.asteroids:
            a.x = (a.x + a.vx) % FIELD_W
            a.y = (a.y + a.vy) % FIELD_H
            a.angle += a.rot_speed

        for ship in s.ships:
            if not ship.alive or ship.invincible > 0:
                continue
            for a in s.asteroids:
                if math.hypot(ship.x - a.x, ship.y - a.y) < ASTEROID_SIZES[a.size] + SHIP_RADIUS:
                    ship.alive = False
                    break

        self._check_bomb_asteroid_hits()
        self._check_win()

        if self._widget is not None:
            self._widget.update()

    def _handle_bombs(self) -> None:
        """Rising-edge bomb drop for P1 (and P2 in PvP)."""
        player_count = 2 if self._pvp else 1
        for i in range(player_count):
            inp = self._inputs[i]
            pressed = inp.bomb and not self._bomb_held[i]
            self._bomb_held[i] = inp.bomb
            if pressed:
                self._try_bomb(i)

    def _drive_non_player_ships(self) -> None:
        raise NotImplementedError

    def _detonate(self, bx: float, by: float, owner: int) -> None:
        s = self._state
        s.explosions.append(Explosion(x=bx, y=by, radius=BOMB_BLAST_R))
        for i, ship in enumerate(s.ships):
            if not ship.alive or i == owner:
                continue
            if math.hypot(ship.x - bx, ship.y - by) < BOMB_BLAST_R + SHIP_RADIUS:
                if ship.invincible == 0:
                    ship.alive = False
                    s.ships[owner].score += 1
        s.asteroids = [
            a for a in s.asteroids
            if math.hypot(a.x - bx, a.y - by) >= BOMB_BLAST_R + ASTEROID_SIZES[a.size] * 0.6
        ]

    def _check_bomb_asteroid_hits(self) -> None:
        s = self._state
        detonated: list[int] = []
        for bi, b in enumerate(s.bombs):
            for a in s.asteroids:
                if math.hypot(b.x - a.x, b.y - a.y) < ASTEROID_SIZES[a.size] + 4:
                    detonated.append(bi)
                    break
            if bi in detonated:
                continue
            for i, ship in enumerate(s.ships):
                if i == b.owner or not ship.alive or ship.invincible > 0:
                    continue
                if math.hypot(b.x - ship.x, b.y - ship.y) < SHIP_RADIUS + 4:
                    detonated.append(bi)
                    break
        for idx in sorted(set(detonated), reverse=True):
            b = s.bombs.pop(idx)
            s.ships[b.owner].bombs_live = max(0, s.ships[b.owner].bombs_live - 1)
            self._detonate(b.x, b.y, b.owner)

    def _check_win(self) -> None:
        if self._game_state != GameState.RUNNING:
            return
        s = self._state
        alive = [i for i, sh in enumerate(s.ships) if sh.alive]
        if len(alive) > 1:
            return
        self._timer.stop()
        self._set_state(GameState.OVER)
        winner = alive[0] if len(alive) == 1 else None
        scores = {i: sh.score for i, sh in enumerate(s.ships)}
        self.game_over.emit(GameResult(scores=scores, winner=winner))

    def _try_bomb(self, ship_idx: int) -> None:
        s = self._state
        ship = s.ships[ship_idx]
        if not ship.alive or ship.bombs_live >= BOMB_MAX_LIVE or ship.bomb_cooldown > 0:
            return
        rad = math.radians(ship.angle)
        bx = ship.x + math.sin(rad) * (SHIP_RADIUS + 6)
        by = ship.y - math.cos(rad) * (SHIP_RADIUS + 6)
        s.bombs.append(Bomb(
            x=bx, y=by,
            vx=ship.vx + math.sin(rad) * BOMB_SPEED,
            vy=ship.vy - math.cos(rad) * BOMB_SPEED,
            owner=ship_idx,
        ))
        ship.bombs_live += 1
        ship.bomb_cooldown = BOMB_COOLDOWN

    def get_state(self) -> dict:
        s = self._state
        return {"tick": s.tick, "ships_alive": sum(1 for sh in s.ships if sh.alive)}


@register_game
class AsteroidsBomberSingleGame(_ABBase):
    display_name = "Asteroid Bomber — vs Bot"

    def __init__(self) -> None:
        super().__init__(pvp=False)

    def _drive_non_player_ships(self) -> None:
        from app.subapps.games_hub.games.asteroidsbomber.bot import bot_act
        s = self._state
        for i in range(1, len(s.ships)):
            if s.ships[i].alive:
                bot_act(s, i, self._inputs[i], lambda idx=i: self._try_bomb(idx))


@register_game
class AsteroidsBomberPvPGame(_ABBase):
    display_name = "Asteroid Bomber — 2 Players"

    def __init__(self) -> None:
        super().__init__(pvp=True)

    def _drive_non_player_ships(self) -> None:
        pass


def _move_ship(ship: Ship, inp: _Input) -> None:
    if ship.invincible > 0:
        ship.invincible -= 1
    if ship.bomb_cooldown > 0:
        ship.bomb_cooldown -= 1

    if inp.left:
        ship.angle -= SHIP_ROT_SPEED
    if inp.right:
        ship.angle += SHIP_ROT_SPEED

    ship.thrusting = inp.thrust
    if inp.thrust:
        rad = math.radians(ship.angle)
        ship.vx += math.sin(rad) * SHIP_ACCEL
        ship.vy -= math.cos(rad) * SHIP_ACCEL
        speed = math.hypot(ship.vx, ship.vy)
        if speed > MAX_SPEED:
            ship.vx = ship.vx / speed * MAX_SPEED
            ship.vy = ship.vy / speed * MAX_SPEED

    ship.vx *= SHIP_FRICTION
    ship.vy *= SHIP_FRICTION
    ship.x = (ship.x + ship.vx) % FIELD_W
    ship.y = (ship.y + ship.vy) % FIELD_H
