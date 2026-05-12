from __future__ import annotations

from PySide6.QtCore import Qt

from app.subapps.games_hub.base_game import Action, BaseGame, GameState, PlayerSlot

# Default key → (slot, action) mapping.
# Loaded once; overridable via settings ("games.keymap.p1.*", "games.keymap.p2.*").
_DEFAULT_MAP: dict[Qt.Key, tuple[PlayerSlot, Action]] = {
    # P1 — WASD + Space/Z
    Qt.Key_W:     (PlayerSlot.P1, Action.UP),
    Qt.Key_S:     (PlayerSlot.P1, Action.DOWN),
    Qt.Key_A:     (PlayerSlot.P1, Action.LEFT),
    Qt.Key_D:     (PlayerSlot.P1, Action.RIGHT),
    Qt.Key_Space: (PlayerSlot.P1, Action.FIRE),
    Qt.Key_Z:     (PlayerSlot.P1, Action.FIRE),
    # P2 — Arrow keys + Enter
    Qt.Key_Up:     (PlayerSlot.P2, Action.UP),
    Qt.Key_Down:   (PlayerSlot.P2, Action.DOWN),
    Qt.Key_Left:   (PlayerSlot.P2, Action.LEFT),
    Qt.Key_Right:  (PlayerSlot.P2, Action.RIGHT),
    Qt.Key_Return: (PlayerSlot.P2, Action.FIRE),
    # Shared pause
    Qt.Key_Escape: (PlayerSlot.P1, Action.PAUSE),
    Qt.Key_P:      (PlayerSlot.P1, Action.PAUSE),
}


def _build_map() -> dict[Qt.Key, tuple[PlayerSlot, Action]]:
    from app.core.settings_store import settings_store

    action_names = {a.name.lower(): a for a in Action}
    slot_names = {s.name.lower(): s for s in PlayerSlot}
    result = dict(_DEFAULT_MAP)

    overrides = settings_store.all_for_prefix("games.keymap.")
    for dot_key, key_name in overrides.items():
        # dot_key like "games.keymap.p1.up" → slot="p1", action="up"
        parts = dot_key.split(".")
        if len(parts) != 4:
            continue
        slot = slot_names.get(parts[2])
        action = action_names.get(parts[3])
        qt_key = getattr(Qt, f"Key_{key_name.capitalize()}", None)
        if slot and action and qt_key is not None:
            result[qt_key] = (slot, action)

    return result


class InputRouter:
    """Routes Qt key events to the active game's key_press / key_release methods."""

    def __init__(self) -> None:
        self._game: BaseGame | None = None
        self._map: dict[Qt.Key, tuple[PlayerSlot, Action]] = _build_map()

    def attach(self, game: BaseGame) -> None:
        self._game = game

    def detach(self) -> None:
        self._game = None

    def reload_keymap(self) -> None:
        self._map = _build_map()

    def handle_key_press(self, key: Qt.Key) -> bool:
        """Returns True if the key was consumed."""
        if self._game is None or self._game.current_state not in (
            GameState.RUNNING, GameState.PAUSED
        ):
            return False
        mapping = self._map.get(key)
        if mapping is None:
            return False
        slot, action = mapping
        if action == Action.PAUSE:
            if self._game.current_state == GameState.RUNNING:
                self._game.pause()
            else:
                self._game.resume()
            return True
        self._game.key_press(action, slot)
        return True

    def handle_key_release(self, key: Qt.Key) -> bool:
        if self._game is None or self._game.current_state != GameState.RUNNING:
            return False
        mapping = self._map.get(key)
        if mapping is None:
            return False
        slot, action = mapping
        if action == Action.PAUSE:
            return True
        self._game.key_release(action, slot)
        return True


input_router = InputRouter()
