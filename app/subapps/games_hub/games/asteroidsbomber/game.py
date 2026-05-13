from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import Action, BaseGame, GameMode, GameState, PlayerSlot
from app.subapps.games_hub.ui import register_game

# ── Field ──────────────────────────────────────────────────────────────────
FIELD_W = 700
FIELD_H = 550

# ── Ship physics (identical to Asteroids) ──────────────────────────────────
SHIP_ACCEL     = 0.25
SHIP_FRICTION  = 0.98
SHIP_ROT_SPEED = 4.0    # degrees/tick
MAX_SPEED      = 7.0
SHIP_RADIUS    = 10

# ── Bomb ───────────────────────────────────────────────────────────────────
BOMB_SPEED       = 1.8   # pixels/tick (slow projectile)
BOMB_FUSE_TICKS  = 180   # ~3 s at 60 fps
BOMB_BLAST_R     = 70    # pixels
BOMB_MAX_LIVE    = 2     # per ship at once
BOMB_COOLDOWN    = 40    # ticks between placements

# ── Asteroids ──────────────────────────────────────────────────────────────
ASTEROID_SIZES   = [40, 22, 12]   # radii
ASTEROID_COUNT   = 10
ASTEROID_SPEED   = 1.2            # constant magnitude

# ── Explosion visual ───────────────────────────────────────────────────────
EXPLOSION_TICKS  = 40

TICK_MS = 16   # ~60 fps


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class Ship:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    angle: float = 0.0     # degrees, 0 = up
    alive: bool = True
    invincible: int = 90   # ticks
    thrusting: bool = False
    bombs_live: int = 0
    bomb_cooldown: int = 0
    score: int = 0
    # held-key state (only meaningful for human P1)
    held_left: bool = False
    held_right: bool = False
    held_thrust: bool = False


@dataclass
class Bomb:
    x: float
    y: float
    vx: float
    vy: float
    owner: int             # ship index
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
    vx: float              # wind direction — same for all
    vy: float
    angle: float
    rot_speed: float
    size: int              # index into ASTEROID_SIZES


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
    def new(num_bots: int) -> "ABState":
        wind_angle = random.uniform(0, 360)
        wvx = math.cos(math.radians(wind_angle)) * ASTEROID_SPEED
        wvy = math.sin(math.radians(wind_angle)) * ASTEROID_SPEED

        # Spread ships around centre at safe angles
        ship_count = 1 + num_bots
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
        # Random size distribution
        size = random.choices([0, 1, 2], weights=[3, 3, 4])[0]
        # Random position, but not too close to any ship
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


# ── Game class ─────────────────────────────────────────────────────────────

@register_game
class AsteroidsBomberGame(BaseGame):
    game_id      = "asteroidsbomber"
    display_name = "Asteroid Bomber"
    icon_char    = "💣"
    max_players  = 2
    supports_lan = False

    # Number of bot opponents in SINGLE mode — can be changed before start()
    num_bots: int = 1

    def __init__(self) -> None:
        super().__init__()
        self._pvp = False          # True when LOCAL_PVP
        self._state: ABState = ABState.new(self.num_bots)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._widget: QWidget | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.asteroidsbomber.renderer import ABRenderer
        self._widget = ABRenderer(self._state)
        return self._widget

    def start(self, mode: GameMode, players: dict[PlayerSlot, str]) -> None:
        self._pvp = (mode == GameMode.LOCAL_PVP)
        # PvP: 1 human opponent (ship[1]), no bots; Single: num_bots bot ships
        extra_ships = 1 if self._pvp else self.num_bots
        self._state = ABState.new(extra_ships)
        if self._widget is not None:
            self._widget._state = self._state  # type: ignore[attr-defined]
            self._widget._pvp   = self._pvp    # type: ignore[attr-defined]
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

    # ── Input ──────────────────────────────────────────────────────────────

    def key_press(self, action: Action, slot: PlayerSlot) -> None:
        if self._game_state != GameState.RUNNING:
            return
        idx = 0 if slot == PlayerSlot.P1 else 1
        if idx >= len(self._state.ships):
            return
        ship = self._state.ships[idx]
        if action == Action.LEFT:   ship.held_left   = True
        elif action == Action.RIGHT: ship.held_right  = True
        elif action == Action.UP:    ship.held_thrust  = True
        elif action == Action.DOWN:  self._try_bomb(idx)   # S / Down-arrow = bomb

    def key_release(self, action: Action, slot: PlayerSlot) -> None:
        idx = 0 if slot == PlayerSlot.P1 else 1
        if idx >= len(self._state.ships):
            return
        ship = self._state.ships[idx]
        if action == Action.LEFT:   ship.held_left   = False
        elif action == Action.RIGHT: ship.held_right  = False
        elif action == Action.UP:    ship.held_thrust  = False

    # ── Physics tick ───────────────────────────────────────────────────────

    def _tick(self) -> None:
        s = self._state
        s.tick += 1

        # Move all ships
        for i, ship in enumerate(s.ships):
            if not ship.alive:
                continue
            _move_ship(ship)

        # Bot decisions — only for non-human slots (skip all in PvP)
        if not self._pvp:
            from app.subapps.games_hub.games.asteroidsbomber.bot import bot_act
            for i in range(1, len(s.ships)):
                if s.ships[i].alive:
                    bot_act(s, i, lambda idx=i: self._try_bomb(idx))

        # Move bombs
        for b in s.bombs:
            b.x = (b.x + b.vx) % FIELD_W
            b.y = (b.y + b.vy) % FIELD_H
            b.fuse -= 1

        # Detonate expired bombs
        detonated: list[int] = [i for i, b in enumerate(s.bombs) if b.fuse <= 0]
        for idx in sorted(detonated, reverse=True):
            b = s.bombs.pop(idx)
            s.ships[b.owner].bombs_live = max(0, s.ships[b.owner].bombs_live - 1)
            self._detonate(b.x, b.y, b.owner)

        # Tick explosions
        s.explosions = [e for e in s.explosions if e.life > 0]
        for e in s.explosions:
            e.life -= 1

        # Move asteroids (wrap)
        for a in s.asteroids:
            a.x = (a.x + a.vx) % FIELD_W
            a.y = (a.y + a.vy) % FIELD_H
            a.angle += a.rot_speed

        # Ship–asteroid collision
        for ship in s.ships:
            if not ship.alive or ship.invincible > 0:
                continue
            for a in s.asteroids:
                if math.hypot(ship.x - a.x, ship.y - a.y) < ASTEROID_SIZES[a.size] + SHIP_RADIUS:
                    ship.alive = False
                    break

        # Bomb–asteroid collision (live bombs hit asteroids)
        self._check_bomb_asteroid_hits()

        self._check_win()

        if self._widget is not None:
            self._widget.update()

    def _detonate(self, bx: float, by: float, owner: int) -> None:
        s = self._state
        s.explosions.append(Explosion(x=bx, y=by, radius=BOMB_BLAST_R))

        # Kill ships in blast (except owner — no self-kill)
        for i, ship in enumerate(s.ships):
            if not ship.alive or i == owner:
                continue
            if math.hypot(ship.x - bx, ship.y - by) < BOMB_BLAST_R + SHIP_RADIUS:
                if ship.invincible == 0:
                    ship.alive = False
                    s.ships[owner].score += 1

        # Destroy asteroids in blast
        s.asteroids = [
            a for a in s.asteroids
            if math.hypot(a.x - bx, a.y - by) >= BOMB_BLAST_R + ASTEROID_SIZES[a.size] * 0.6
        ]

    def _check_bomb_asteroid_hits(self) -> None:
        # Bombs that physically touch an asteroid or enemy ship detonate early
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

        # Emit win/loss (1/0) so the overlay always shows "Px WINS!" correctly.
        # Mid-game kill counts stay on ship.score for the HUD only.
        winner = alive[0] if len(alive) == 1 else None
        scores: dict = {}
        for i in range(len(s.ships)):
            scores[f"p{i+1}"] = 1 if i == winner else 0
        self.game_over.emit(scores)

    def _try_bomb(self, ship_idx: int) -> None:
        s = self._state
        ship = s.ships[ship_idx]
        if not ship.alive:
            return
        if ship.bombs_live >= BOMB_MAX_LIVE:
            return
        if ship.bomb_cooldown > 0:
            return
        rad = math.radians(ship.angle)
        # Fire from ship nose
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


# ── Ship movement (shared by game tick and bot simulation) ─────────────────

def _move_ship(ship: Ship) -> None:
    if ship.invincible > 0:
        ship.invincible -= 1
    if ship.bomb_cooldown > 0:
        ship.bomb_cooldown -= 1

    if ship.held_left:
        ship.angle -= SHIP_ROT_SPEED
    if ship.held_right:
        ship.angle += SHIP_ROT_SPEED

    ship.thrusting = ship.held_thrust
    if ship.held_thrust:
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
