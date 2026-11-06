from __future__ import annotations

from PySide6.QtWidgets import QApplication, QStyle, QWidget

from app.core.base_subapp import BaseSubApp, CommandDef, SubAppState


class EspFlasherSubApp(BaseSubApp):
    id = "espflasher"
    name = "ESP Flasher"
    hidden = False
    _icon_char = "⚡"

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_DriveHDIcon)
        self._panel: QWidget | None = None

    def create_body(self) -> QWidget:
        from app.subapps.espflasher.ui import EspFlasherPanel
        self._panel = EspFlasherPanel()
        self._panel.status_changed.connect(self.status_changed)
        return self._panel

    def get_commands(self) -> list[CommandDef]:
        return [
            CommandDef("espflasher.start", "Start DFU (flash firmware)",
                       lambda: self._call("start_flash")),
            CommandDef("espflasher.cancel", "Cancel flashing",
                       lambda: self._call("cancel_flash")),
        ]

    def on_activated(self) -> None:
        self.state_changed.emit(SubAppState.READY)
        self.status_changed.emit("ESP Flasher")

    def shutdown(self) -> None:
        # Kill a running esptool so it doesn't outlive the app holding the port.
        if self._panel is not None:
            self._panel.shutdown()  # type: ignore[attr-defined]
