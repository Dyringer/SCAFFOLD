from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


class KeyHandler:
    """
    Mixin for renderer QWidgets that need held-key input.

    Subclass alongside QWidget, declare _TRACKED as a set of Qt.Key_*
    values, and implement _sync_input() to map self._held to your state.

    OS key-repeat sends interleaved press+release pairs. Using a set makes
    both add() and discard() idempotent, so repeats are harmless without
    any isAutoRepeat() checks.

    Usage:
        class MyRenderer(KeyHandler, QWidget):
            _TRACKED = {Qt.Key_Left, Qt.Key_Right, Qt.Key_Space}

            def _sync_input(self) -> None:
                self._state.left  = Qt.Key_Left  in self._held
                self._state.right = Qt.Key_Right in self._held
                self._state.fire  = Qt.Key_Space in self._held
    """

    _TRACKED: set[int] = set()

    def _key_handler_init(self) -> None:
        self._held: set[int] = set()

    def _sync_input(self) -> None:
        """Override to map self._held to your game's input state."""

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in self._TRACKED:
            self._held.add(key)
            self._sync_input()
        else:
            super().keyPressEvent(event)  # type: ignore[misc]

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in self._TRACKED:
            self._held.discard(key)
            self._sync_input()
        else:
            super().keyReleaseEvent(event)  # type: ignore[misc]

    def clear_held(self) -> None:
        """Call when the game resets so no keys are phantom-held."""
        self._held.clear()
        self._sync_input()
