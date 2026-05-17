from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle, QWidget

from app.core.base_subapp import BaseSubApp, CommandDef, SubAppState


class ScratchpadSubApp(BaseSubApp):
    id = "scratchpad"
    name = "Scratchpad"
    hidden = False
    _icon_char = "📝"

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        self._panel: QWidget | None = None

    def create_body(self) -> QWidget:
        from app.subapps.scratchpad.ui import ScratchpadPanel
        self._panel = ScratchpadPanel()
        self._panel.status_changed.connect(self.status_changed)
        return self._panel

    def get_commands(self) -> list[CommandDef]:
        return [
            CommandDef("scratchpad.new", "New note", lambda: self._call("new_note"), "Ctrl+N"),
        ]

    def on_activated(self) -> None:
        self.state_changed.emit(SubAppState.READY)
        self.status_changed.emit("Scratchpad")

    def on_deactivated(self) -> None:
        if self._panel is not None:
            self._panel.deactivate()  # type: ignore[attr-defined]

    def _call(self, method: str) -> None:
        if self._panel is None:
            return
        fn = getattr(self._panel, method, None)
        if callable(fn):
            fn()
