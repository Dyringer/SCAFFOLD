from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle, QWidget

from app.core.base_subapp import BaseSubApp, SubAppState
from app.core.settings_store import SettingDef


class SettingsSubApp(BaseSubApp):
    id = "settings"
    name = "Settings"
    hidden = False
    _icon_char = "⚙️"

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        self._panel: QWidget | None = None

    def create_body(self) -> QWidget:
        from app.subapps.settings.ui import SettingsPanel
        self._panel = SettingsPanel()
        return self._panel

    def create_header_widget(self) -> QWidget | None:
        from app.subapps.settings.ui import SettingsHeaderWidget
        return SettingsHeaderWidget()

    def get_settings(self) -> list[SettingDef]:
        return []

    def on_activated(self) -> None:
        self.state_changed.emit(SubAppState.READY)
