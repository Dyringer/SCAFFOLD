from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from app.core.base_subapp import BaseSubApp

log = logging.getLogger(__name__)


class Registry(QObject):
    subapp_registered = Signal(object)   # BaseSubApp
    subapp_activated = Signal(str)       # subapp id

    def __init__(self) -> None:
        super().__init__()
        self._apps: dict[str, BaseSubApp] = {}
        self._active_id: str | None = None
        self._sidebar: object = None   # set by window after construction
        self._body_stack: object = None
        self._header: object = None
        self._footer: object = None
        self._command_palette: object = None
        self._shortcut_manager: object = None

    # ------------------------------------------------------------------
    # UI wiring
    # ------------------------------------------------------------------

    def bind_ui(
        self,
        *,
        header,
        body_stack,
        footer,
        command_palette,
        sidebar=None,
    ) -> None:
        self._header = header
        self._body_stack = body_stack
        self._footer = footer
        self._command_palette = command_palette
        self._sidebar = sidebar

    @property
    def sidebar(self):
        return self._sidebar

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------

    def register(self, subapp: BaseSubApp) -> None:
        if not subapp.id:
            raise ValueError("SubApp must have a non-empty id")
        if subapp.id in self._apps:
            raise ValueError(f"SubApp id '{subapp.id}' already registered")
        self._apps[subapp.id] = subapp
        log.info("registered %s", subapp.id)
        self.subapp_registered.emit(subapp)

    # ------------------------------------------------------------------
    # lookup
    # ------------------------------------------------------------------

    def get(self, subapp_id: str) -> BaseSubApp | None:
        return self._apps.get(subapp_id)

    def all(self, include_hidden: bool = False) -> list[BaseSubApp]:
        return [a for a in self._apps.values() if include_hidden or not a.hidden]

    @property
    def active_id(self) -> str | None:
        return self._active_id

    # ------------------------------------------------------------------
    # activation
    # ------------------------------------------------------------------

    def shutdown_all(self) -> None:
        """Tear down every registered subapp, last-registered first.

        Each subapp's shutdown() is best-effort: a failure in one is
        logged and the next still runs. After this returns, no subapp
        should hold a strong reference to a service or a native handle.
        """
        for subapp in reversed(list(self._apps.values())):
            try:
                subapp.shutdown()
            except Exception:
                log.exception("subapp %s shutdown failed", subapp.id)

    def activate(self, subapp_id: str) -> None:
        subapp = self._apps.get(subapp_id)
        if subapp is None:
            log.warning("activate: unknown id '%s'", subapp_id)
            return

        # deactivate current
        if self._active_id and self._active_id != subapp_id:
            prev = self._apps.get(self._active_id)
            if prev:
                prev.on_deactivated()

        self._active_id = subapp_id

        if self._header:
            self._header.set_universal_widget(subapp.create_header_widget())
        if self._body_stack:
            self._body_stack.switch_to(subapp_id)
        if self._footer:
            self._footer.connect_subapp(subapp)
        if self._command_palette:
            self._command_palette.set_subapp_commands(subapp.get_commands())
        if self._shortcut_manager:
            self._shortcut_manager.register_commands(subapp.get_commands())

        subapp.on_activated()

        from app.core.settings_store import settings_store
        settings_store.set("app.last_subapp", subapp_id)
        self.subapp_activated.emit(subapp_id)
        log.info("activated %s", subapp_id)


registry = Registry()
