from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import BaseGame, GameMode, GameResult, GameState
from app.subapps.games_hub.ui import register_game

COLS = 20
ROWS = 20
TICK_MS = 130          # base speed
SPEED_STEP = 5         # ms shaved off per 5 apples eaten
MIN_TICK = 60


@dataclass
class SnakeState:
    body: deque[tuple[int, int]]       # head first
    direction: tuple[int, int]         # (dr, dc)
    next_dir: tuple[int, int]
    apple: tuple[int, int]
    score: int = 0
    apples_eaten: int = 0

    @staticmethod
    def new() -> "SnakeState":
        # Head at col 12, tail stretching left — direction is right (0, 1)
        body: deque[tuple[int, int]] = deque([
            (ROWS // 2, COLS // 2 + 2),   # head
            (ROWS // 2, COLS // 2 + 1),
            (ROWS // 2, COLS // 2),        # tail
        ])
        state = SnakeState(
            body=body,
            direction=(0, 1),
            next_dir=(0, 1),
            apple=(0, 0),
        )
        state.apple = _random_apple(state.body)
        return state


def _random_apple(body: deque[tuple[int, int]]) -> tuple[int, int]:
    occupied = set(body)
    free = [(r, c) for r in range(ROWS) for c in range(COLS) if (r, c) not in occupied]
    return random.choice(free) if free else (0, 0)


@register_game
class SnakeGame(BaseGame):
    game_id = "snake"
    display_name = "Snake"
    icon_char = "🐍"

    def __init__(self) -> None:
        super().__init__()
        self._state = SnakeState.new()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timers.append(self._timer)
        self._widget: QWidget | None = None

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.snake.renderer import SnakeRenderer
        self._widget = SnakeRenderer(self._state, self._on_direction)
        return self._widget

    def start(self, mode: GameMode, players: dict[int, str]) -> None:
        self._state = SnakeState.new()
        if self._widget is not None:
            self._widget.state = self._state
        super().start(mode, players)
        self._timer.start(TICK_MS)

    def resume(self) -> None:
        super().resume()
        self._timer.start(self._current_speed())

    def _on_direction(self, dr: int, dc: int) -> None:
        s = self._state
        # Ignore if opposite direction
        if (dr, dc) != (-s.direction[0], -s.direction[1]):
            s.next_dir = (dr, dc)

    def get_state(self) -> dict:
        s = self._state
        return {"body": list(s.body), "apple": s.apple, "score": s.score}

    def _tick(self) -> None:
        s = self._state
        s.direction = s.next_dir
        head = (s.body[0][0] + s.direction[0], s.body[0][1] + s.direction[1])

        # Wall collision
        if not (0 <= head[0] < ROWS and 0 <= head[1] < COLS):
            self._die()
            return

        # Self collision
        if head in s.body:
            self._die()
            return

        s.body.appendleft(head)

        if head == s.apple:
            s.apples_eaten += 1
            s.score += 10 * (s.apples_eaten // 5 + 1)
            s.apple = _random_apple(s.body)
            # Speed up every 5 apples
            if s.apples_eaten % 5 == 0:
                self._timer.start(self._current_speed())
            self.score_tick.emit(f"Score: {s.score:,}")
        else:
            s.body.pop()

        if self._widget is not None:
            self._widget.update()

    def _die(self) -> None:
        self._timer.stop()
        self._set_state(GameState.OVER)
        self.game_over.emit(GameResult(scores={0: self._state.score}, winner=None))

    def _current_speed(self) -> int:
        reduction = (self._state.apples_eaten // 5) * SPEED_STEP
        return max(MIN_TICK, TICK_MS - reduction)
