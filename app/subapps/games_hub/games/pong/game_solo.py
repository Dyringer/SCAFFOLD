from __future__ import annotations

import random

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import BaseGame, GameMode, GameResult, GameState
from app.subapps.games_hub.games.pong.game_core import (
    InputState, PongState, ScoreEvent, GameOverEvent,
    TICK_MS, PADDLE_SPEED, cpu_dy, step, _center_ball,
)


class _PongBase(BaseGame):
    """Shared lifecycle and physics wiring for both Pong variants."""

    game_id  = "pong"
    icon_char = "🏓"

    def __init__(self) -> None:
        super().__init__()
        self._state  = PongState.initial()
        self._input  = InputState()
        self._widget: QWidget | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timers.append(self._timer)

        self._serve_timer = QTimer(self)
        self._serve_timer.setSingleShot(True)
        self._serve_timer.timeout.connect(self._launch_ball)

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.pong.renderer import PongRenderer
        self._widget = PongRenderer(self._state, self._input)
        return self._widget

    def start(self, mode: GameMode, players: dict[int, str]) -> None:
        self._state = PongState.initial()
        self._input.left_up = self._input.left_down = False
        self._input.right_up = self._input.right_down = False
        if self._widget is not None:
            self._widget.state  = self._state
            self._widget.clear_held()
        super().start(mode, players)
        self._begin_serve()

    def pause(self) -> None:
        self._serve_timer.stop()
        super().pause()   # stops _timer via _timers

    def resume(self) -> None:
        super().resume()  # restarts _timer via _timers
        if self._state.serving:
            self._timer.stop()
            self._begin_serve()

    def stop(self) -> None:
        self._serve_timer.stop()
        super().stop()

    def get_state(self) -> dict:
        s = self._state
        return {
            "left":    {"y": s.left.y,  "score": s.left.score},
            "right":   {"y": s.right.y, "score": s.right.score},
            "ball":    {"x": s.ball.x,  "y": s.ball.y},
            "serving": s.serving,
        }

    # ------------------------------------------------------------------
    # Subclass contract

    def _right_dy(self) -> float:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Internal

    def _begin_serve(self) -> None:
        self._state.serving = True
        self._refresh()
        self._serve_timer.start(1200)

    def _launch_ball(self) -> None:
        self._state.serving = False
        vx_sign = 1 if random.random() > 0.5 else -1
        self._state.ball = _center_ball(vx_sign)
        self._timer.start()

    def _left_dy(self) -> float:
        up   = self._input.left_up
        down = self._input.left_down
        if up and not down:
            return -PADDLE_SPEED
        if down and not up:
            return PADDLE_SPEED
        return 0.0

    def _tick(self) -> None:
        events = step(self._state, self._left_dy(), self._right_dy())
        for evt in events:
            if isinstance(evt, ScoreEvent):
                self.score_tick.emit(f"{evt.left} : {evt.right}")
                self._timer.stop()
                self._begin_serve()
                return
            elif isinstance(evt, GameOverEvent):
                self._timer.stop()
                self._set_state(GameState.OVER)
                winner = 0 if evt.winner == 0 else 1
                self.game_over.emit(GameResult(
                    scores={0: evt.left, 1: evt.right},
                    winner=winner,
                ))
                return
        self.score_tick.emit(f"{self._state.left.score} : {self._state.right.score}")
        self._refresh()

    def _refresh(self) -> None:
        if self._widget is not None:
            self._widget.update()


class PongSingleGame(_PongBase):
    display_name = "Pong — vs CPU"

    def _right_dy(self) -> float:
        return cpu_dy(self._state)


class PongPvPGame(_PongBase):
    display_name = "Pong — 2 Players"

    def _right_dy(self) -> float:
        up   = self._input.right_up
        down = self._input.right_down
        if up and not down:
            return -PADDLE_SPEED
        if down and not up:
            return PADDLE_SPEED
        return 0.0
