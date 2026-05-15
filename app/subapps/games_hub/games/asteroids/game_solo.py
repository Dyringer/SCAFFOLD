from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import BaseGame, GameMode, GameResult, GameState
from app.subapps.games_hub.games.asteroids.game_core import (
    AsteroidsState, GameOverEvent, HitEvent, InputState, TICK_MS,
)


class AsteroidsGame(BaseGame):
    game_id      = "asteroids"
    display_name = "Asteroids"
    icon_char    = "☄️"

    def __init__(self) -> None:
        super().__init__()
        self._state         = AsteroidsState.new()
        self._fire_cooldown = 0
        self._input         = InputState()
        self._widget: QWidget | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timers.append(self._timer)

    # ------------------------------------------------------------------
    # BaseGame interface

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.asteroids.renderer import AsteroidsRenderer
        self._widget = AsteroidsRenderer(self._state, self._input)
        return self._widget

    def start(self, mode: GameMode, players: dict[int, str]) -> None:
        self._reset_state()
        super().start(mode, players)
        self._timer.start()

    def get_state(self) -> dict:
        s = self._state
        return {"ship_x": s.ship_x, "ship_y": s.ship_y, "score": s.score, "lives": s.lives}

    # ------------------------------------------------------------------
    # Internal

    def _reset_state(self) -> None:
        self._state         = AsteroidsState.new()
        self._fire_cooldown = 0
        self._input.left = self._input.right = self._input.thrust = self._input.fire = False
        if self._widget is not None:
            self._widget.state = self._state

    def _tick(self) -> None:
        from app.subapps.games_hub.games.asteroids.game_core import step

        self._fire_cooldown, events = step(self._state, self._input, self._fire_cooldown)

        for evt in events:
            if isinstance(evt, HitEvent):
                self.score_tick.emit(f"Score: {self._state.score:,}")
            elif isinstance(evt, GameOverEvent):
                self._timer.stop()
                self._set_state(GameState.OVER)
                self.game_over.emit(GameResult(scores={0: self._state.score}, winner=None))
                return

        if self._widget is not None:
            self._widget.update()
