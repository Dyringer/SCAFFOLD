from __future__ import annotations

import random
from dataclasses import dataclass, field

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import Action, BaseGame, GameMode, GameState, PlayerSlot
from app.subapps.games_hub.ui import register_game

FIELD_W = 480
FIELD_H = 520

PLAYER_W = 32
PLAYER_H = 16
PLAYER_Y = FIELD_H - 36
PLAYER_SPEED = 5

BULLET_W = 3
BULLET_H = 10
BULLET_SPEED = 9

INVADER_COLS = 11
INVADER_ROWS = 5
INVADER_W = 32
INVADER_H = 24
INVADER_GAP_X = 8
INVADER_GAP_Y = 10
INVADER_TOP = 48
MOVE_INTERVAL_INIT = 600   # ms between invader steps
MOVE_INTERVAL_MIN  = 80

BOMB_INTERVAL = 1200       # ms between enemy bombs
BOMB_SPEED = 4

TICK_MS = 16


@dataclass
class Invader:
    row: int
    col: int
    alive: bool = True


@dataclass
class Bullet:
    x: float
    y: float
    vy: float   # negative = player bullet, positive = enemy bomb


@dataclass
class SpaceInvadersState:
    player_x: float
    invaders: list[Invader]
    bullets: list[Bullet]
    offset_x: float    # current herd x offset
    offset_y: float    # current herd y offset
    direction: int     # 1 = right, -1 = left
    score: int = 0
    wave: int = 1
    can_fire: bool = True   # one bullet at a time for player

    @staticmethod
    def new(wave: int = 1) -> "SpaceInvadersState":
        invaders = [
            Invader(row=r, col=c)
            for r in range(INVADER_ROWS)
            for c in range(INVADER_COLS)
        ]
        return SpaceInvadersState(
            player_x=(FIELD_W - PLAYER_W) / 2,
            invaders=invaders,
            bullets=[],
            offset_x=0.0,
            offset_y=0.0,
            direction=1,
            wave=wave,
        )

    def alive_invaders(self) -> list[Invader]:
        return [i for i in self.invaders if i.alive]

    def leftmost_col(self) -> int:
        cols = [i.col for i in self.alive_invaders()]
        return min(cols) if cols else 0

    def rightmost_col(self) -> int:
        cols = [i.col for i in self.alive_invaders()]
        return max(cols) if cols else INVADER_COLS - 1

    def lowest_row(self) -> int:
        rows = [i.row for i in self.alive_invaders()]
        return max(rows) if rows else 0


def _invader_rect(inv: Invader, ox: float, oy: float) -> tuple[float, float, float, float]:
    x = ox + inv.col * (INVADER_W + INVADER_GAP_X)
    y = oy + INVADER_TOP + inv.row * (INVADER_H + INVADER_GAP_Y)
    return x, y, INVADER_W, INVADER_H


@register_game
class SpaceInvadersGame(BaseGame):
    game_id = "space_invaders"
    display_name = "Space Invaders"
    icon_char = "👾"

    def __init__(self) -> None:
        super().__init__()
        self._state = SpaceInvadersState.new()
        self._move_timer = QTimer(self)
        self._move_timer.timeout.connect(self._move_invaders)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(TICK_MS)
        self._tick_timer.timeout.connect(self._tick)
        self._bomb_timer = QTimer(self)
        self._bomb_timer.timeout.connect(self._drop_bomb)
        self._widget: QWidget | None = None
        self._held_left = False
        self._held_right = False

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.space_invaders.renderer import SpaceInvadersRenderer
        self._widget = SpaceInvadersRenderer(self._state)
        return self._widget

    def start(self, mode: GameMode, players: dict[PlayerSlot, str]) -> None:
        self._state = SpaceInvadersState.new()
        self._held_left = self._held_right = False
        if self._widget is not None:
            self._widget._state = self._state  # type: ignore[attr-defined]
        super().start(mode, players)
        self._start_timers()

    def pause(self) -> None:
        self._move_timer.stop()
        self._tick_timer.stop()
        self._bomb_timer.stop()
        super().pause()

    def resume(self) -> None:
        super().resume()
        self._start_timers()

    def stop(self) -> None:
        self._move_timer.stop()
        self._tick_timer.stop()
        self._bomb_timer.stop()
        super().stop()

    def key_press(self, action: Action, slot: PlayerSlot) -> None:
        if self._game_state != GameState.RUNNING:
            return
        if action == Action.LEFT:
            self._held_left = True
        elif action == Action.RIGHT:
            self._held_right = True
        elif action in (Action.FIRE, Action.UP) and self._state.can_fire:
            s = self._state
            s.bullets.append(Bullet(
                x=s.player_x + PLAYER_W / 2 - BULLET_W / 2,
                y=PLAYER_Y - BULLET_H,
                vy=-BULLET_SPEED,
            ))
            s.can_fire = False

    def key_release(self, action: Action, slot: PlayerSlot) -> None:
        if action == Action.LEFT:
            self._held_left = False
        elif action == Action.RIGHT:
            self._held_right = False

    def get_state(self) -> dict:
        s = self._state
        return {"player_x": s.player_x, "score": s.score, "wave": s.wave}

    # ------------------------------------------------------------------

    def _start_timers(self) -> None:
        speed = self._move_speed()
        self._move_timer.start(speed)
        self._tick_timer.start()
        self._bomb_timer.start(BOMB_INTERVAL)

    def _move_speed(self) -> int:
        alive = len(self._state.alive_invaders())
        total = INVADER_COLS * INVADER_ROWS
        # Speed up as invaders die
        fraction = alive / total
        speed = int(MOVE_INTERVAL_INIT * fraction + MOVE_INTERVAL_MIN * (1 - fraction))
        # Also faster in later waves
        speed = max(MOVE_INTERVAL_MIN, speed - (self._state.wave - 1) * 40)
        return speed

    def _move_invaders(self) -> None:
        s = self._state
        step = INVADER_W // 4
        herd_w = (INVADER_COLS - 1) * (INVADER_W + INVADER_GAP_X) + INVADER_W
        left_edge = s.offset_x + s.leftmost_col() * (INVADER_W + INVADER_GAP_X)
        right_edge = left_edge + (s.rightmost_col() - s.leftmost_col()) * (INVADER_W + INVADER_GAP_X) + INVADER_W

        if s.direction == 1 and right_edge + step >= FIELD_W:
            s.offset_y += INVADER_H // 2
            s.direction = -1
        elif s.direction == -1 and left_edge - step <= 0:
            s.offset_y += INVADER_H // 2
            s.direction = 1
        else:
            s.offset_x += step * s.direction

        # Invaders reach player line → game over
        lowest_y = s.offset_y + INVADER_TOP + s.lowest_row() * (INVADER_H + INVADER_GAP_Y) + INVADER_H
        if lowest_y >= PLAYER_Y:
            self._end_game()
            return

        self._move_timer.setInterval(self._move_speed())
        self._sync()

    def _drop_bomb(self) -> None:
        alive = self._state.alive_invaders()
        if not alive:
            return
        inv = random.choice(alive)
        x, y, w, h = _invader_rect(inv, self._state.offset_x, self._state.offset_y)
        self._state.bullets.append(Bullet(x=x + w / 2, y=y + h, vy=BOMB_SPEED))

    def _tick(self) -> None:
        s = self._state

        # Move player
        if self._held_left:
            s.player_x = max(0, s.player_x - PLAYER_SPEED)
        if self._held_right:
            s.player_x = min(FIELD_W - PLAYER_W, s.player_x + PLAYER_SPEED)

        # Move bullets
        to_remove: list[int] = []
        for i, b in enumerate(s.bullets):
            b.y += b.vy
            if b.y < -BULLET_H or b.y > FIELD_H:
                to_remove.append(i)
                if b.vy < 0:   # player bullet expired
                    s.can_fire = True
        for i in reversed(to_remove):
            s.bullets.pop(i)

        # Collision: player bullets vs invaders
        player_bullets = [b for b in s.bullets if b.vy < 0]
        for b in player_bullets:
            for inv in s.alive_invaders():
                ix, iy, iw, ih = _invader_rect(inv, s.offset_x, s.offset_y)
                if ix <= b.x <= ix + iw and iy <= b.y <= iy + ih:
                    inv.alive = False
                    s.bullets.remove(b)
                    s.can_fire = True
                    row_score = (INVADER_ROWS - inv.row) * 10
                    s.score += row_score * s.wave
                    self.score_tick.emit(f"Score: {s.score:,}")
                    break

        # All invaders dead → next wave
        if not s.alive_invaders():
            s.wave += 1
            new = SpaceInvadersState.new(wave=s.wave)
            new.score = s.score
            new.player_x = s.player_x
            self._state = new
            if self._widget is not None:
                self._widget._state = self._state  # type: ignore[attr-defined]
            self._move_timer.setInterval(self._move_speed())
            self._sync()
            return

        # Collision: enemy bombs vs player
        px1, px2 = s.player_x, s.player_x + PLAYER_W
        for b in [blt for blt in s.bullets if blt.vy > 0]:
            if px1 <= b.x <= px2 and PLAYER_Y <= b.y <= PLAYER_Y + PLAYER_H:
                self._end_game()
                return

        self._sync()

    def _end_game(self) -> None:
        self._move_timer.stop()
        self._tick_timer.stop()
        self._bomb_timer.stop()
        self._set_state(GameState.OVER)
        self.game_over.emit({"p1": self._state.score})

    def _sync(self) -> None:
        if self._widget is not None:
            self._widget.update()
