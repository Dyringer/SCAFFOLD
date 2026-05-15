from __future__ import annotations

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QStyle, QWidget

if TYPE_CHECKING:
    from app.subapps.games_hub.ui import HubPanel

from app.core.base_subapp import BaseSubApp, CommandDef, SubAppState
from app.core.settings_store import SettingDef
from app.subapps.games_hub.score_store import score_store


class GamesHubSubApp(BaseSubApp):
    id = "games_hub"
    name = "Games"
    hidden = False
    _icon_char = "🎮"

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)
        self._panel: "HubPanel | None" = None

    def create_body(self) -> QWidget:
        from app.subapps.games_hub.ui import HubPanel
        self._panel = HubPanel()
        return self._panel

    def get_settings(self) -> list[SettingDef]:
        from app.subapps.games_hub.ui import aggregate_settings
        return aggregate_settings()

    def get_commands(self) -> list[CommandDef]:
        return [
            CommandDef("games_hub.open", "Open Games Hub", self._open),
            CommandDef("games_hub.reset_scores", "Reset All Game Scores", self._reset_scores),
        ]

    def on_activated(self) -> None:
        self.status_changed.emit("Games Hub")
        self.state_changed.emit(SubAppState.READY)

    def on_deactivated(self) -> None:
        if self._panel is not None:
            self._panel.stop_active_game()

    def _open(self) -> None:
        from app.core.registry import registry
        registry.activate(self.id)

    def _reset_scores(self) -> None:
        score_store.reset_all()
        if self._panel is not None:
            self._panel.refresh()
