from __future__ import annotations

from PySide6.QtWidgets import QApplication, QStyle, QWidget

from app.core.base_subapp import BaseSubApp, CommandDef, SubAppState
from app.core.settings_store import SettingDef


class SerialTerminalSubApp(BaseSubApp):
    id = "serial_terminal"
    name = "Serial Terminal"
    hidden = False
    _icon_char = "🔌"

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)
        self._panel: QWidget | None = None

    def create_body(self) -> QWidget:
        from app.subapps.serial_terminal.ui import SerialTerminalPanel
        self._panel = SerialTerminalPanel()
        self._panel.status_changed.connect(self.status_changed)
        return self._panel

    def get_settings(self) -> list[SettingDef]:
        return [
            SettingDef(
                key="serial.history",
                label="Console scrollback (lines)",
                type="choice",
                default=5000,
                choices=[
                    (1000, "1,000 lines"),
                    (5000, "5,000 lines"),
                    (10000, "10,000 lines"),
                    (50000, "50,000 lines"),
                ],
            ),
            SettingDef(
                key="serial.rx_watchdog",
                label="Stalled-link watchdog",
                type="choice",
                default=0,
                choices=[
                    (0, "Off"),
                    (5, "Warn after 5 s of silence"),
                    (15, "Warn after 15 s of silence"),
                    (30, "Warn after 30 s of silence"),
                    (60, "Warn after 60 s of silence"),
                ],
            ),
        ]

    def get_commands(self) -> list[CommandDef]:
        return [
            CommandDef(
                "serial.clear",
                "Clear console",
                lambda: self._call("clear_console"),
                "Ctrl+L",
            ),
        ]

    def on_activated(self) -> None:
        self.state_changed.emit(SubAppState.READY)
        self.status_changed.emit("Serial Terminal")

    def on_deactivated(self) -> None:
        # Keep the connection alive across subapp switches — the user
        # expects the port to stay open. Nothing to do here.
        pass

    def shutdown(self) -> None:
        # Release the OS serial handle during teardown, before services
        # stop and the window is destroyed. See feedback-shutdown-architecture.
        if self._panel is not None:
            self._panel.close_port()  # type: ignore[attr-defined]

    def _call(self, method: str) -> None:
        if self._panel is None:
            return
        fn = getattr(self._panel, method, None)
        if callable(fn):
            fn()
