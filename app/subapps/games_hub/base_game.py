from __future__ import annotations

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from app.core.settings_store import SettingDef


class _Meta(type(QObject), ABCMeta):
    pass


# ---------------------------------------------------------------------------
# Public enums

class GameMode(Enum):
    SINGLE    = "single"
    LOCAL_PVP = "local_pvp"
    LAN_PVP   = "lan_pvp"


class GameState(Enum):
    IDLE    = "idle"
    RUNNING = "running"
    PAUSED  = "paused"
    OVER    = "over"


# ---------------------------------------------------------------------------
# GameResult — emitted by game_over signal instead of a raw dict.

@dataclass
class GameResult:
    scores:  dict[int, int]   # player index (0-based) → score
    winner:  int | None       # winning player index, or None (solo / draw)
    message: str | None = None  # optional e.g. "Draw", "Wave 7"


# ---------------------------------------------------------------------------
# GameComposite

@dataclass
class GameComposite:
    """Groups related game variants under one hub card."""
    display_name: str
    icon_char:    str
    variants:     list[type["BaseGame"]]
    game_id:      str = ""

    def __post_init__(self) -> None:
        if not self.game_id and self.variants:
            self.game_id = self.variants[0].game_id


# ---------------------------------------------------------------------------
# BaseGame

class BaseGame(QObject, metaclass=_Meta):
    """Abstract base for all games. Hub calls lifecycle methods; games emit signals."""

    game_over    = Signal(object)  # GameResult
    score_tick   = Signal(str)     # pre-formatted score string for the hub bar
    state_changed = Signal(str)    # GameState.value

    # Class-level metadata — override in each game
    game_id:      str = ""
    display_name: str = ""
    icon_char:    str = "🎮"
    icon_path:    str = ""

    def __init__(self) -> None:
        super().__init__()
        self._game_state = GameState.IDLE
        self._mode:    GameMode     = GameMode.SINGLE
        self._players: dict[int, str] = {}
        self._timers:  list[QTimer]   = []

    # ------------------------------------------------------------------
    # Hub extension points

    @classmethod
    def get_settings(cls) -> list["SettingDef"]:
        return []

    def toolbar_actions(self) -> list[tuple[str, object]]:
        return []

    def can_pause(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Lifecycle — called by the hub

    @abstractmethod
    def create_widget(self) -> QWidget:
        """Return the game canvas widget. Called once by the hub."""

    def start(self, mode: GameMode, players: dict[int, str]) -> None:
        self._mode    = mode
        self._players = players
        self._set_state(GameState.RUNNING)

    def pause(self) -> None:
        if self._game_state == GameState.RUNNING:
            for t in self._timers:
                t.stop()
            self._set_state(GameState.PAUSED)

    def resume(self) -> None:
        if self._game_state == GameState.PAUSED:
            for t in self._timers:
                t.start()
            self._set_state(GameState.RUNNING)

    def stop(self) -> None:
        for t in self._timers:
            t.stop()
        self._set_state(GameState.IDLE)

    def reset(self) -> None:
        self._set_state(GameState.IDLE)

    # ------------------------------------------------------------------
    # LAN serialisation interface

    def get_state(self) -> dict:
        return {}

    def apply_state(self, state: dict) -> None:
        pass

    # ------------------------------------------------------------------

    @property
    def current_state(self) -> GameState:
        return self._game_state

    def _set_state(self, state: GameState) -> None:
        self._game_state = state
        self.state_changed.emit(state.value)
