from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle, QWidget

from app.core.base_subapp import BaseSubApp, SubAppState
from app.core.settings_store import SettingDef, settings_store
from app.services.network import network_service
from app.services.network.discovery import AUTO


class NetworkToolsSubApp(BaseSubApp):
    id = "network_tools"
    name = "Network Tools"
    hidden = False

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_DriveNetIcon)
        self._panel: QWidget | None = None

    def create_body(self) -> QWidget:
        from app.subapps.network_tools.ui import NetworkToolsPanel
        self._panel = NetworkToolsPanel(network_service)
        return self._panel

    def get_settings(self) -> list[SettingDef]:
        # Build interface choice list at call time so the Settings panel
        # shows currently-detected interfaces. Format: [(value, display_label)].
        show_all = bool(settings_store.get("network.interface_show_all", False))
        choices: list = [(AUTO, "Auto (prefer RFC1918)")]
        disc = network_service.discovery
        if disc is not None:
            strict = not show_all
            candidates = disc.candidate_addresses(strict=strict)
            current = network_service.interface_pref
            if current != AUTO and strict and not any(
                addr == current for addr, _, _ in candidates
            ):
                candidates = disc.candidate_addresses(strict=False)
            for addr, iface_name, cls in candidates:
                choices.append((addr, f"{addr}   [{iface_name}]   {cls.name.lower()}"))

        return [
            SettingDef(
                key="network.nick",
                label="Nickname",
                type="str",
                default=network_service.nick,
            ),
            SettingDef(
                key="network.interface",
                label="Discovery interface",
                type="choice",
                default=AUTO,
                choices=choices,
            ),
            SettingDef(
                key="network.interface_show_all",
                label="Show non-RFC1918 interfaces",
                type="bool",
                default=False,
            ),
        ]

    def on_activated(self) -> None:
        self.status_changed.emit(
            f"peer_id={network_service.peer_id[:8]}  nick={network_service.nick}"
        )
        self.state_changed.emit(SubAppState.READY)
