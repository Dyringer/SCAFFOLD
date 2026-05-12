from __future__ import annotations

from abc import ABCMeta, abstractmethod
from enum import Enum, auto
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    pass


class _Meta(type(QObject), ABCMeta):
    pass


class PlayerSlot(Enum):
    P1 = "p1"
    P2 = "p2"


class GameMode(Enum):
    SINGLE = "single"
    LOCAL_PVP = "local_pvp"
    LAN_PVP = "lan_pvp"


class Action(Enum):
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    FIRE = auto()
    PAUSE = auto()


class GameState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    OVER = "over"


class BaseGame(QObject, metaclass=_Meta):
    """Abstract base for all games. Hub calls the lifecycle methods; games emit signals."""

    game_over = Signal(dict)     # {"p1": int, "p2": int | None}
    score_tick = Signal(dict)    # same shape, live updates
    state_changed = Signal(str)  # GameState.value

    # --- class-level metadata; override in each game ---
    game_id: str = ""
    display_name: str = ""
    icon_char: str = "🎮"
    icon_path: str = ""          # relative to app/resources/
    max_players: int = 1
    supports_lan: bool = False

    def __init__(self) -> None:
        super().__init__()
        self._game_state = GameState.IDLE
        self._mode: GameMode = GameMode.SINGLE
        self._players: dict[PlayerSlot, str] = {}

    # ------------------------------------------------------------------
    # Lifecycle — called by the hub

    @abstractmethod
    def create_widget(self) -> QWidget:
        """Return the game canvas widget. Called once by the hub."""

    def start(self, mode: GameMode, players: dict[PlayerSlot, str]) -> None:
        """Begin a new game session."""
        self._mode = mode
        self._players = players
        self._set_state(GameState.RUNNING)

    def pause(self) -> None:
        if self._game_state == GameState.RUNNING:
            self._set_state(GameState.PAUSED)

    def resume(self) -> None:
        if self._game_state == GameState.PAUSED:
            self._set_state(GameState.RUNNING)

    def reset(self) -> None:
        self._set_state(GameState.IDLE)

    def stop(self) -> None:
        self._set_state(GameState.IDLE)

    # ------------------------------------------------------------------
    # Input — called by InputRouter

    def key_press(self, action: Action, slot: PlayerSlot) -> None:
        pass

    def key_release(self, action: Action, slot: PlayerSlot) -> None:
        pass

    # ------------------------------------------------------------------
    # LAN serialisation interface (implement when supports_lan = True)

    def get_state(self) -> dict:
        """Return full serialisable game state snapshot."""
        return {}

    def apply_state(self, state: dict) -> None:
        """Apply a received state snapshot (LAN client side)."""

    # ------------------------------------------------------------------

    @property
    def current_state(self) -> GameState:
        return self._game_state

    def _set_state(self, state: GameState) -> None:
        self._game_state = state
        self.state_changed.emit(state.value)
