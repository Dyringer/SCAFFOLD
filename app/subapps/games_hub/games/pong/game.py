from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import Action, BaseGame, GameMode, GameState, PlayerSlot
from app.subapps.games_hub.ui import register_game

# Field dimensions (logical units, renderer scales to actual pixels)
FIELD_W = 800
FIELD_H = 500

PADDLE_W = 12
PADDLE_H = 80
PADDLE_SPEED = 6

BALL_SIZE = 12
BALL_SPEED_INIT = 5.0
BALL_SPEED_MAX = 14.0
BALL_SPEED_INC = 0.3     # speed added per paddle hit

WIN_SCORE = 7
TICK_MS = 16             # ~60 fps


@dataclass
class PaddleState:
    y: float              # top-left y (x is fixed per side)
    score: int = 0
    dy: float = 0.0      # current velocity from input


@dataclass
class BallState:
    x: float
    y: float
    vx: float
    vy: float


@dataclass
class PongState:
    left: PaddleState
    right: PaddleState
    ball: BallState
    serving: bool = True  # pause before each point

    @staticmethod
    def initial() -> "PongState":
        return PongState(
            left=PaddleState(y=(FIELD_H - PADDLE_H) / 2),
            right=PaddleState(y=(FIELD_H - PADDLE_H) / 2),
            ball=_center_ball(),
        )


def _center_ball(vx_sign: int = 1) -> BallState:
    angle = random.uniform(-0.4, 0.4)  # radians, not too steep
    return BallState(
        x=FIELD_W / 2,
        y=FIELD_H / 2,
        vx=BALL_SPEED_INIT * vx_sign * math.cos(angle),
        vy=BALL_SPEED_INIT * math.sin(angle),
    )


@register_game
class PongGame(BaseGame):
    game_id = "pong"
    display_name = "Pong"
    icon_char = "🏓"
    icon_path = ""
    max_players = 2
    supports_lan = False

    def __init__(self) -> None:
        super().__init__()
        self._state = PongState.initial()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._widget: QWidget | None = None
        self._mode = GameMode.SINGLE
        # Held directions per slot
        self._held: dict[PlayerSlot, float] = {PlayerSlot.P1: 0.0, PlayerSlot.P2: 0.0}
        self._serve_timer = QTimer(self)
        self._serve_timer.setSingleShot(True)
        self._serve_timer.timeout.connect(self._launch_ball)

    # ------------------------------------------------------------------
    # BaseGame contract

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.pong.renderer import PongRenderer
        self._widget = PongRenderer(self._state)
        return self._widget

    def start(self, mode: GameMode, players: dict[PlayerSlot, str]) -> None:
        self._mode = mode
        self._state = PongState.initial()
        self._held = {PlayerSlot.P1: 0.0, PlayerSlot.P2: 0.0}
        if self._widget is not None:
            self._widget._state = self._state  # type: ignore[attr-defined]
        super().start(mode, players)
        self._begin_serve()

    def pause(self) -> None:
        self._timer.stop()
        self._serve_timer.stop()
        super().pause()

    def resume(self) -> None:
        super().resume()
        if self._state.serving:
            self._begin_serve()
        else:
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._serve_timer.stop()
        super().stop()

    def key_press(self, action: Action, slot: PlayerSlot) -> None:
        if self._game_state != GameState.RUNNING:
            return
        if action == Action.UP:
            self._held[slot] = -1.0
        elif action == Action.DOWN:
            self._held[slot] = 1.0

    def key_release(self, action: Action, slot: PlayerSlot) -> None:
        if action in (Action.UP, Action.DOWN):
            self._held[slot] = 0.0

    def get_state(self) -> dict:
        s = self._state
        return {
            "left": {"y": s.left.y, "score": s.left.score, "dy": s.left.dy},
            "right": {"y": s.right.y, "score": s.right.score, "dy": s.right.dy},
            "ball": {"x": s.ball.x, "y": s.ball.y, "vx": s.ball.vx, "vy": s.ball.vy},
            "serving": s.serving,
        }

    # ------------------------------------------------------------------

    def _begin_serve(self) -> None:
        self._state.serving = True
        self._sync()
        self._serve_timer.start(1200)

    def _launch_ball(self) -> None:
        self._state.serving = False
        vx_sign = 1 if random.random() > 0.5 else -1
        self._state.ball = _center_ball(vx_sign)
        self._timer.start()

    def _tick(self) -> None:
        s = self._state

        # Move paddles
        s.left.dy = self._held[PlayerSlot.P1] * PADDLE_SPEED
        if self._mode == GameMode.LOCAL_PVP:
            s.right.dy = self._held[PlayerSlot.P2] * PADDLE_SPEED
        else:
            s.right.dy = self._cpu_dy()

        s.left.y = max(0, min(FIELD_H - PADDLE_H, s.left.y + s.left.dy))
        s.right.y = max(0, min(FIELD_H - PADDLE_H, s.right.y + s.right.dy))

        # Move ball
        s.ball.x += s.ball.vx
        s.ball.y += s.ball.vy

        # Top / bottom wall bounce
        if s.ball.y <= 0:
            s.ball.y = 0
            s.ball.vy = abs(s.ball.vy)
        elif s.ball.y + BALL_SIZE >= FIELD_H:
            s.ball.y = FIELD_H - BALL_SIZE
            s.ball.vy = -abs(s.ball.vy)

        # Left paddle collision
        if (
            s.ball.x <= PADDLE_W
            and s.left.y <= s.ball.y + BALL_SIZE / 2 <= s.left.y + PADDLE_H
        ):
            s.ball.x = PADDLE_W
            s.ball.vx = abs(s.ball.vx)
            self._apply_spin(s.ball, s.left.dy)
            self._inc_speed(s.ball)

        # Right paddle collision
        if (
            s.ball.x + BALL_SIZE >= FIELD_W - PADDLE_W
            and s.right.y <= s.ball.y + BALL_SIZE / 2 <= s.right.y + PADDLE_H
        ):
            s.ball.x = FIELD_W - PADDLE_W - BALL_SIZE
            s.ball.vx = -abs(s.ball.vx)
            self._apply_spin(s.ball, s.right.dy)
            self._inc_speed(s.ball)

        # Scoring
        if s.ball.x + BALL_SIZE < 0:
            s.right.score += 1
            self._after_score()
        elif s.ball.x > FIELD_W:
            s.left.score += 1
            self._after_score()

        self.score_tick.emit({"p1": s.left.score, "p2": s.right.score})
        self._sync()

    def _after_score(self) -> None:
        self._timer.stop()
        s = self._state
        if s.left.score >= WIN_SCORE or s.right.score >= WIN_SCORE:
            self._set_state(GameState.OVER)
            self.game_over.emit({"p1": s.left.score, "p2": s.right.score})
        else:
            self._begin_serve()

    def _cpu_dy(self) -> float:
        ball = self._state.ball
        paddle = self._state.right
        centre = paddle.y + PADDLE_H / 2
        target = ball.y
        diff = target - centre
        # Only react when ball is heading right
        if ball.vx > 0:
            return max(-PADDLE_SPEED * 0.85, min(PADDLE_SPEED * 0.85, diff * 0.12))
        return max(-PADDLE_SPEED * 0.4, min(PADDLE_SPEED * 0.4, diff * 0.05))

    @staticmethod
    def _apply_spin(ball: BallState, paddle_dy: float) -> None:
        ball.vy += paddle_dy * 0.4
        # Cap vertical speed
        speed = math.hypot(ball.vx, ball.vy)
        if speed > BALL_SPEED_MAX:
            ball.vx = ball.vx / speed * BALL_SPEED_MAX
            ball.vy = ball.vy / speed * BALL_SPEED_MAX

    @staticmethod
    def _inc_speed(ball: BallState) -> None:
        speed = math.hypot(ball.vx, ball.vy)
        new_speed = min(speed + BALL_SPEED_INC, BALL_SPEED_MAX)
        if speed > 0:
            ball.vx = ball.vx / speed * new_speed
            ball.vy = ball.vy / speed * new_speed

    def _sync(self) -> None:
        if self._widget is not None:
            self._widget.update()  # type: ignore[attr-defined]
