from __future__ import annotations

from PySide6.QtWidgets import QApplication, QStyle, QWidget

from app.core.base_subapp import BaseSubApp, CommandDef, SubAppState


class EspOtaSubApp(BaseSubApp):
    id = "esp_ota"
    name = "ESP OTA"
    hidden = False
    _icon_char = "📡"

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_DriveNetIcon)
        self._panel: QWidget | None = None

    def create_body(self) -> QWidget:
        from app.subapps.esp_ota.ui import EspOtaPanel
        self._panel = EspOtaPanel()
        self._panel.status_changed.connect(self.status_changed)
        return self._panel

    def get_commands(self) -> list[CommandDef]:
        return [
            CommandDef("esp_ota.start", "Start OTA update (Wi-Fi)",
                       lambda: self._call("start_ota")),
            CommandDef("esp_ota.cancel", "Cancel OTA update",
                       lambda: self._call("cancel_ota")),
        ]

    def on_activated(self) -> None:
        self.state_changed.emit(SubAppState.READY)
        self.status_changed.emit("ESP OTA")

    def shutdown(self) -> None:
        # Abort an in-flight upload and stop the probe timer so no worker
        # thread outlives the app.
        if self._panel is not None:
            self._panel.shutdown()  # type: ignore[attr-defined]
