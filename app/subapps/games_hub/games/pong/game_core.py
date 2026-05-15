from __future__ import annotations

import math
import random
from dataclasses import dataclass

FIELD_W = 800
FIELD_H = 500

PADDLE_W     = 12
PADDLE_H     = 80
PADDLE_SPEED = 6

BALL_SIZE       = 12
BALL_SPEED_INIT = 5.0
BALL_SPEED_MAX  = 14.0
BALL_SPEED_INC  = 0.3

WIN_SCORE = 7
TICK_MS   = 16


# ---------------------------------------------------------------------------
# State

@dataclass
class PaddleState:
    y:     float
    score: int   = 0
    dy:    float = 0.0


@dataclass
class BallState:
    x:  float
    y:  float
    vx: float
    vy: float


@dataclass
class PongState:
    left:    PaddleState
    right:   PaddleState
    ball:    BallState
    serving: bool = True

    @staticmethod
    def initial() -> "PongState":
        return PongState(
            left=PaddleState(y=(FIELD_H - PADDLE_H) / 2),
            right=PaddleState(y=(FIELD_H - PADDLE_H) / 2),
            ball=_center_ball(),
        )


@dataclass
class InputState:
    left_up:   bool = False
    left_down: bool = False
    right_up:  bool = False
    right_down: bool = False


def _center_ball(vx_sign: int = 1) -> BallState:
    angle = random.uniform(-0.4, 0.4)
    return BallState(
        x=FIELD_W / 2,
        y=FIELD_H / 2,
        vx=BALL_SPEED_INIT * vx_sign * math.cos(angle),
        vy=BALL_SPEED_INIT * math.sin(angle),
    )


# ---------------------------------------------------------------------------
# Events

class ScoreEvent:
    __slots__ = ("left", "right")
    def __init__(self, left: int, right: int) -> None:
        self.left  = left
        self.right = right


class GameOverEvent:
    __slots__ = ("left", "right", "winner")
    def __init__(self, left: int, right: int, winner: int) -> None:
        self.left   = left
        self.right  = right
        self.winner = winner  # 0 = left, 1 = right


# ---------------------------------------------------------------------------
# CPU AI

def cpu_dy(state: PongState) -> float:
    ball   = state.ball
    paddle = state.right
    centre = paddle.y + PADDLE_H / 2
    diff   = ball.y - centre
    if ball.vx > 0:
        return max(-PADDLE_SPEED * 0.85, min(PADDLE_SPEED * 0.85, diff * 0.12))
    return max(-PADDLE_SPEED * 0.4, min(PADDLE_SPEED * 0.4, diff * 0.05))


# ---------------------------------------------------------------------------
# Physics step

def step(s: PongState, left_dy: float, right_dy: float) -> list:
    """
    Advance game state by one tick.

    left_dy / right_dy: desired paddle velocities (pixels per tick, signed).
    Returns a list of ScoreEvent / GameOverEvent instances (usually empty).
    """
    events: list = []

    s.left.dy  = left_dy
    s.right.dy = right_dy

    s.left.y  = max(0, min(FIELD_H - PADDLE_H, s.left.y  + s.left.dy))
    s.right.y = max(0, min(FIELD_H - PADDLE_H, s.right.y + s.right.dy))

    s.ball.x += s.ball.vx
    s.ball.y += s.ball.vy

    # Wall bounces
    if s.ball.y <= 0:
        s.ball.y  = 0
        s.ball.vy = abs(s.ball.vy)
    elif s.ball.y + BALL_SIZE >= FIELD_H:
        s.ball.y  = FIELD_H - BALL_SIZE
        s.ball.vy = -abs(s.ball.vy)

    # Paddle collisions
    if (s.ball.x <= PADDLE_W and
            s.left.y <= s.ball.y + BALL_SIZE / 2 <= s.left.y + PADDLE_H):
        s.ball.x  = PADDLE_W
        s.ball.vx = abs(s.ball.vx)
        _apply_spin(s.ball, s.left.dy)
        _inc_speed(s.ball)

    if (s.ball.x + BALL_SIZE >= FIELD_W - PADDLE_W and
            s.right.y <= s.ball.y + BALL_SIZE / 2 <= s.right.y + PADDLE_H):
        s.ball.x  = FIELD_W - PADDLE_W - BALL_SIZE
        s.ball.vx = -abs(s.ball.vx)
        _apply_spin(s.ball, s.right.dy)
        _inc_speed(s.ball)

    # Scoring
    if s.ball.x + BALL_SIZE < 0:
        s.right.score += 1
        events.append(_score_or_over(s))
    elif s.ball.x > FIELD_W:
        s.left.score += 1
        events.append(_score_or_over(s))

    return events


def _score_or_over(s: PongState) -> "ScoreEvent | GameOverEvent":
    if s.left.score >= WIN_SCORE:
        return GameOverEvent(s.left.score, s.right.score, winner=0)
    if s.right.score >= WIN_SCORE:
        return GameOverEvent(s.left.score, s.right.score, winner=1)
    return ScoreEvent(s.left.score, s.right.score)


def _apply_spin(ball: BallState, paddle_dy: float) -> None:
    ball.vy += paddle_dy * 0.4
    speed = math.hypot(ball.vx, ball.vy)
    if speed > BALL_SPEED_MAX:
        ball.vx = ball.vx / speed * BALL_SPEED_MAX
        ball.vy = ball.vy / speed * BALL_SPEED_MAX


def _inc_speed(ball: BallState) -> None:
    speed     = math.hypot(ball.vx, ball.vy)
    new_speed = min(speed + BALL_SPEED_INC, BALL_SPEED_MAX)
    if speed > 0:
        ball.vx = ball.vx / speed * new_speed
        ball.vy = ball.vy / speed * new_speed
