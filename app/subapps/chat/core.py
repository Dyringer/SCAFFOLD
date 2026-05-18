from __future__ import annotations

from PySide6.QtWidgets import QApplication, QStyle, QWidget

from app.core.base_subapp import BaseSubApp, SubAppState
from app.core.notification_bus import notification_bus
from app.core.registry import registry
from app.subapps.chat.model import CHAT_NS, ChatLine, ChatModel, Direction, EVERYONE


class ChatSubApp(BaseSubApp):
    id = "chat"
    name = "Chat"
    hidden = False
    _icon_char = "💬"

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_MessageBoxInformation)
        self._panel: QWidget | None = None
        self._model = ChatModel(self)
        # When chat is not the active subapp, route incoming messages to
        # a toast + sidebar badge.
        self._model.line_added.connect(self._on_line_added)

    def create_body(self) -> QWidget:
        from app.subapps.chat.ui import ChatPanel
        self._panel = ChatPanel(self._model)
        return self._panel

    def shutdown(self) -> None:
        from app.services.network import network_service
        network_service.unregister_namespace(CHAT_NS)

    def on_activated(self) -> None:
        # Clear sidebar unread badge on activation; the panel handles
        # per-thread mark-read for whichever thread is open.
        sidebar = getattr(registry, "sidebar", None)
        if sidebar is not None:
            sidebar.set_unread(self.id, 0)
        self.state_changed.emit(SubAppState.READY)
        self._update_status()

    @property
    def model(self) -> ChatModel:
        return self._model

    # ------------------------------------------------------------------
    # notification routing

    def _is_active(self) -> bool:
        return registry.active_id == self.id

    def _on_line_added(self, _thread_id: str, line: ChatLine) -> None:
        # React only to inbound peer messages (not own outgoing, not system).
        if line.direction != Direction.INCOMING:
            self._update_status()
            return

        # Toast always fires on inbound — user wants to know about every
        # message regardless of which subapp is currently active.
        if line.thread_id == EVERYONE:
            title = f"💬 {line.sender_nick}  (everyone)"
        else:
            title = f"💬 {line.sender_nick}"
        notification_bus.notify.emit("info", title, line.text)

        # Sidebar badge only bumps when chat is NOT the active subapp.
        # If user is looking at chat, the panel marks read immediately
        # for the visible thread, so the badge would just flicker.
        if not self._is_active():
            sidebar = getattr(registry, "sidebar", None)
            if sidebar is not None:
                sidebar.increment_unread(self.id)

        self._update_status()

    def _update_status(self) -> None:
        total = self._model.total_unread()
        if total:
            self.status_changed.emit(f"{total} unread")
        else:
            self.status_changed.emit("")
