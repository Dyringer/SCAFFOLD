from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import Action, BaseGame, GameMode, GameState, PlayerSlot
from app.subapps.games_hub.ui import register_game

FIELD_W = 480
FIELD_H = 560

PADDLE_W = 72
PADDLE_H = 10
PADDLE_Y = FIELD_H - 40
PADDLE_SPEED = 7

BALL_R = 7
BALL_SPEED_INIT = 5.0
BALL_SPEED_MAX  = 10.0
BALL_SPEED_INC  = 0.15

BRICK_COLS = 10
BRICK_ROWS = 6
BRICK_W = FIELD_W // BRICK_COLS
BRICK_H = 20
BRICK_TOP = 60
BRICK_GAP = 2

TICK_MS = 16

# Points per row (bottom rows worth more)
_ROW_POINTS = [50, 40, 30, 20, 10, 10]


@dataclass
class BrickState:
    alive: bool = True
    row: int = 0
    col: int = 0


@dataclass
class BreakoutState:
    paddle_x: float          # left edge
    ball_x: float
    ball_y: float
    ball_vx: float
    ball_vy: float
    bricks: list[BrickState]
    score: int = 0
    lives: int = 3
    launched: bool = False   # False = ball sitting on paddle

    @staticmethod
    def new() -> "BreakoutState":
        bricks = [
            BrickState(alive=True, row=r, col=c)
            for r in range(BRICK_ROWS)
            for c in range(BRICK_COLS)
        ]
        px = (FIELD_W - PADDLE_W) / 2
        return BreakoutState(
            paddle_x=px,
            ball_x=px + PADDLE_W / 2,
            ball_y=PADDLE_Y - BALL_R - 1,
            ball_vx=0.0,
            ball_vy=0.0,
            bricks=bricks,
        )

    def reset_ball(self) -> None:
        self.paddle_x = (FIELD_W - PADDLE_W) / 2
        self.ball_x = self.paddle_x + PADDLE_W / 2
        self.ball_y = PADDLE_Y - BALL_R - 1
        self.ball_vx = 0.0
        self.ball_vy = 0.0
        self.launched = False

    @property
    def bricks_remaining(self) -> int:
        return sum(1 for b in self.bricks if b.alive)


@register_game
class BreakoutGame(BaseGame):
    game_id = "breakout"
    display_name = "Breakout"
    icon_char = "🧱"
    max_players = 1
    supports_lan = False

    def __init__(self) -> None:
        super().__init__()
        self._state = BreakoutState.new()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._widget: QWidget | None = None
        self._held_left = False
        self._held_right = False

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.breakout.renderer import BreakoutRenderer
        self._widget = BreakoutRenderer(self._state)
        return self._widget

    def start(self, mode: GameMode, players: dict[PlayerSlot, str]) -> None:
        self._state = BreakoutState.new()
        self._held_left = self._held_right = False
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
        if action == Action.LEFT:
            self._held_left = True
        elif action == Action.RIGHT:
            self._held_right = True
        elif action in (Action.FIRE, Action.UP) and not self._state.launched:
            self._launch()

    def key_release(self, action: Action, slot: PlayerSlot) -> None:
        if action == Action.LEFT:
            self._held_left = False
        elif action == Action.RIGHT:
            self._held_right = False

    def get_state(self) -> dict:
        s = self._state
        return {
            "paddle_x": s.paddle_x, "ball_x": s.ball_x, "ball_y": s.ball_y,
            "score": s.score, "lives": s.lives,
            "bricks": [(b.row, b.col, b.alive) for b in s.bricks],
        }

    # ------------------------------------------------------------------

    def _launch(self) -> None:
        angle = random.uniform(-0.6, 0.6)
        self._state.ball_vx = BALL_SPEED_INIT * math.sin(angle)
        self._state.ball_vy = -BALL_SPEED_INIT * math.cos(angle)
        self._state.launched = True

    def _tick(self) -> None:
        s = self._state

        # Move paddle
        if self._held_left:
            s.paddle_x = max(0, s.paddle_x - PADDLE_SPEED)
        if self._held_right:
            s.paddle_x = min(FIELD_W - PADDLE_W, s.paddle_x + PADDLE_SPEED)

        if not s.launched:
            s.ball_x = s.paddle_x + PADDLE_W / 2
            self._sync()
            return

        # Move ball
        s.ball_x += s.ball_vx
        s.ball_y += s.ball_vy

        # Wall bounces
        if s.ball_x - BALL_R <= 0:
            s.ball_x = BALL_R
            s.ball_vx = abs(s.ball_vx)
        elif s.ball_x + BALL_R >= FIELD_W:
            s.ball_x = FIELD_W - BALL_R
            s.ball_vx = -abs(s.ball_vx)
        if s.ball_y - BALL_R <= 0:
            s.ball_y = BALL_R
            s.ball_vy = abs(s.ball_vy)

        # Paddle collision
        if (
            s.ball_vy > 0
            and s.paddle_x <= s.ball_x <= s.paddle_x + PADDLE_W
            and PADDLE_Y - BALL_R <= s.ball_y <= PADDLE_Y + PADDLE_H
        ):
            s.ball_y = PADDLE_Y - BALL_R
            # Angle based on where ball hits paddle
            rel = (s.ball_x - (s.paddle_x + PADDLE_W / 2)) / (PADDLE_W / 2)
            angle = rel * 1.1
            speed = min(math.hypot(s.ball_vx, s.ball_vy) + BALL_SPEED_INC, BALL_SPEED_MAX)
            s.ball_vx = speed * math.sin(angle)
            s.ball_vy = -speed * math.cos(angle)

        # Ball lost
        if s.ball_y - BALL_R > FIELD_H:
            s.lives -= 1
            if s.lives <= 0:
                self._timer.stop()
                self._set_state(GameState.OVER)
                self.game_over.emit({"p1": s.score})
                return
            s.reset_ball()
            self._sync()
            return

        # Brick collisions
        self._check_bricks()

        # All bricks cleared — next level (rebuild bricks, speed up)
        if s.bricks_remaining == 0:
            for b in s.bricks:
                b.alive = True
            speed = min(math.hypot(s.ball_vx, s.ball_vy) + 0.5, BALL_SPEED_MAX)
            norm = speed / math.hypot(s.ball_vx, s.ball_vy) if math.hypot(s.ball_vx, s.ball_vy) else 1
            s.ball_vx *= norm
            s.ball_vy *= norm

        self.score_tick.emit({"p1": s.score})
        self._sync()

    def _check_bricks(self) -> None:
        s = self._state
        for b in s.bricks:
            if not b.alive:
                continue
            bx = b.col * BRICK_W + BRICK_GAP
            by = BRICK_TOP + b.row * BRICK_H + BRICK_GAP
            bw = BRICK_W - BRICK_GAP * 2
            bh = BRICK_H - BRICK_GAP * 2

            if not (bx <= s.ball_x + BALL_R and s.ball_x - BALL_R <= bx + bw and
                    by <= s.ball_y + BALL_R and s.ball_y - BALL_R <= by + bh):
                continue

            b.alive = False
            s.score += _ROW_POINTS[b.row]

            # Determine bounce axis
            overlap_x = min(s.ball_x + BALL_R - bx, bx + bw - (s.ball_x - BALL_R))
            overlap_y = min(s.ball_y + BALL_R - by, by + bh - (s.ball_y - BALL_R))
            if overlap_x < overlap_y:
                s.ball_vx = -s.ball_vx
            else:
                s.ball_vy = -s.ball_vy
            break  # one brick per tick

    def _sync(self) -> None:
        if self._widget is not None:
            self._widget.update()
