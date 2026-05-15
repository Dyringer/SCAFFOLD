from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import BaseGame, GameMode, GameResult, GameState
from app.subapps.games_hub.games.bomberman.game_core import (
    BombermanState, InputState, GameOverEvent, PlayerDiedEvent,
    P1, P2, TICK_MS, apply_input, place_bomb, step,
)


class BombermanSingleGame(BaseGame):
    game_id      = "bomberman"
    display_name = "Bomberman — vs Bot"
    icon_char    = "💣"

    def __init__(self) -> None:
        super().__init__()
        self._state         = BombermanState.new()
        self._input         = InputState()
        self._bomb_held     = False
        self._widget: QWidget | None = None
        self._bot_debug_path: list[tuple[int, int]] = []

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timers.append(self._timer)

    @classmethod
    def get_settings(cls) -> list:
        from app.core.settings_store import SettingDef
        return [
            SettingDef("bomberman.debug_bot_path", "Bomberman: Show bot planned path", "bool", False),
        ]

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.bomberman.renderer import BombermanRenderer
        from PySide6.QtCore import Qt
        self._widget = BombermanRenderer(self._state, self._input, p1_bomb=Qt.Key_Space, p2_label="CPU")
        return self._widget

    def start(self, mode: GameMode, players: dict[int, str]) -> None:
        self._state = BombermanState.new()
        self._input.up = self._input.down = self._input.left = False
        self._input.right = self._input.bomb = False
        self._bomb_held     = False
        self._bot_debug_path = []
        if self._widget is not None:
            self._widget.state    = self._state
            self._widget.bot_path = []
            self._widget.clear_held()
        super().start(mode, players)
        self._timer.start()

    def get_state(self) -> dict:
        s = self._state
        return {
            "p1": (s.players[P1].row, s.players[P1].col),
            "p2": (s.players[P2].row, s.players[P2].col),
        }

    def _tick(self) -> None:
        from app.subapps.games_hub.games.bomberman.bot import bot_act, bot_path
        from app.core.settings_store import settings_store

        s = self._state

        # P1 human input
        self._bomb_held = apply_input(s, P1, self._input, lambda: place_bomb(s, P1), self._bomb_held)

        # P2 bot input
        bot_act(s, lambda: place_bomb(s, P2))

        # Debug path
        if settings_store.get("bomberman.debug_bot_path", False):
            bot = s.players[P2]
            if bot.bombs_placed == 0:
                new_path, _ = bot_path(s)
                if new_path:
                    self._bot_debug_path = new_path
        else:
            self._bot_debug_path = []
        if self._widget is not None:
            self._widget.bot_path = self._bot_debug_path

        events = step(s)
        self._handle_events(events)

    def _handle_events(self, events: list) -> None:
        for evt in events:
            if isinstance(evt, GameOverEvent):
                self._timer.stop()
                self._set_state(GameState.OVER)
                winner_idx = evt.winner  # 0=P1, 1=P2, None=draw
                scores = {
                    0: 1 if winner_idx == P1 else 0,
                    1: 1 if winner_idx == P2 else 0,
                }
                self.game_over.emit(GameResult(scores=scores, winner=winner_idx))
                if self._widget is not None:
                    self._widget.update()
                return
        if self._widget is not None:
            self._widget.update()
