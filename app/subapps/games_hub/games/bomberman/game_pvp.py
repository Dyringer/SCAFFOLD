from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import BaseGame, GameMode, GameResult, GameState
from app.subapps.games_hub.games.bomberman.game_core import (
    BombermanState, InputState, GameOverEvent,
    P1, P2, TICK_MS, apply_input, place_bomb, step,
)


class BombermanPvPGame(BaseGame):
    game_id      = "bomberman"
    display_name = "Bomberman — 2 Players"
    icon_char    = "💣"

    def __init__(self) -> None:
        super().__init__()
        self._state        = BombermanState.new()
        self._input1       = InputState()
        self._input2       = InputState()
        self._bomb_held1   = False
        self._bomb_held2   = False
        self._widget: QWidget | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timers.append(self._timer)

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.bomberman.renderer import BombermanRenderer
        from PySide6.QtCore import Qt
        self._widget = BombermanRenderer(
            self._state, self._input1, p1_bomb=Qt.Key_F,
            p2_label="P2", input2=self._input2, p2_bomb=Qt.Key_M,
        )
        return self._widget

    def start(self, mode: GameMode, players: dict[int, str]) -> None:
        self._state = BombermanState.new()
        for inp in (self._input1, self._input2):
            inp.up = inp.down = inp.left = inp.right = inp.bomb = False
        self._bomb_held1 = self._bomb_held2 = False
        if self._widget is not None:
            self._widget.state = self._state
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
        s = self._state
        self._bomb_held1 = apply_input(s, P1, self._input1, lambda: place_bomb(s, P1), self._bomb_held1)
        self._bomb_held2 = apply_input(s, P2, self._input2, lambda: place_bomb(s, P2), self._bomb_held2)

        events = step(s)
        for evt in events:
            if isinstance(evt, GameOverEvent):
                self._timer.stop()
                self._set_state(GameState.OVER)
                winner_idx = evt.winner
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
