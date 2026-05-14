from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import Action, BaseGame, GameMode, GameState, PlayerSlot  # noqa: F401
from app.subapps.games_hub.ui import register_game
from app.subapps.games_hub.games.asteroids.game_core import (
    AsteroidsState, GameOverEvent, HitEvent, TICK_MS,
)


@register_game
class AsteroidsGame(BaseGame):
    game_id      = "asteroids"
    display_name = "Asteroids"
    icon_char    = "☄️"

    def __init__(self) -> None:
        super().__init__()
        self._state         = AsteroidsState.new()
        self._fire_cooldown = 0
        self._held_left     = False
        self._held_right    = False
        self._held_thrust   = False
        self._request_fire  = False
        self._widget: QWidget | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    # BaseGame interface

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.asteroids.renderer import AsteroidsRenderer
        self._widget = AsteroidsRenderer(self._state)
        return self._widget

    def start(self, mode: GameMode, players: dict[PlayerSlot, str]) -> None:
        self._reset_state()
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
        if action == Action.LEFT:    self._held_left    = True
        elif action == Action.RIGHT: self._held_right   = True
        elif action == Action.UP:    self._held_thrust  = True
        elif action == Action.FIRE:  self._request_fire = True

    def key_release(self, action: Action, slot: PlayerSlot) -> None:
        if action == Action.LEFT:    self._held_left   = False
        elif action == Action.RIGHT: self._held_right  = False
        elif action == Action.UP:    self._held_thrust = False

    def get_state(self) -> dict:
        s = self._state
        return {"ship_x": s.ship_x, "ship_y": s.ship_y, "score": s.score, "lives": s.lives}

    # ------------------------------------------------------------------
    # Internal

    def _reset_state(self) -> None:
        self._state         = AsteroidsState.new()
        self._fire_cooldown = 0
        self._held_left = self._held_right = self._held_thrust = self._request_fire = False
        if self._widget is not None:
            self._widget._state = self._state  # type: ignore[attr-defined]

    def _tick(self) -> None:
        from app.subapps.games_hub.games.asteroids.game_core import step

        fire = self._request_fire
        self._request_fire = False

        self._fire_cooldown, events = step(
            self._state,
            self._held_left, self._held_right, self._held_thrust,
            self._fire_cooldown, fire,
        )

        for evt in events:
            if isinstance(evt, HitEvent):
                self.score_tick.emit(f"Score: {self._state.score:,}")
            elif isinstance(evt, GameOverEvent):
                self._timer.stop()
                self._set_state(GameState.OVER)
                self.game_over.emit({"p1": self._state.score})
                return

        if self._widget is not None:
            self._widget.update()
