from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle, QWidget

from app.core.base_subapp import BaseSubApp, CommandDef, SubAppState
from app.core.message_bus import Message, message_bus
from app.core.settings_store import SettingDef, settings_store


@dataclass
class CountChanged(Message):
    value: int
    step: int


class CounterSubApp(BaseSubApp):
    id = "counter"
    name = "Counter"
    hidden = False
    _icon_char = "🔢"

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_ArrowUp)
        self._count = 0
        self._step: int = settings_store.get("counter.step", 1)
        self._panel: QWidget | None = None
        self._header_widget: QWidget | None = None

    # ------------------------------------------------------------------
    # BaseSubApp contract

    def create_body(self) -> QWidget:
        from app.subapps.counter.ui import CounterPanel
        self._panel = CounterPanel()
        self._panel.increment_clicked.connect(self.increment)
        self._panel.decrement_clicked.connect(self.decrement)
        self._panel.set_count(self._count)
        return self._panel

    def create_header_widget(self) -> QWidget | None:
        from app.subapps.counter.ui import CounterHeaderWidget
        self._header_widget = CounterHeaderWidget()
        self._header_widget.set_count(self._count)
        return self._header_widget

    def get_settings(self) -> list[SettingDef]:
        return [
            SettingDef(
                "counter.step",
                "Increment step",
                "choice",
                1,
                [1, 5, 10],
            )
        ]

    def get_commands(self) -> list[CommandDef]:
        return [
            CommandDef("counter.increment", "Increment counter", self.increment, "Ctrl+Up"),
            CommandDef("counter.decrement", "Decrement counter", self.decrement),
            CommandDef("counter.reset", "Reset counter", self.reset),
        ]

    def on_activated(self) -> None:
        self._step = settings_store.get("counter.step", 1)
        self.status_changed.emit(f"Step: {self._step}")
        self.state_changed.emit(SubAppState.READY)

    # ------------------------------------------------------------------
    # logic

    def increment(self) -> None:
        self._count += self._step
        self._sync()

    def decrement(self) -> None:
        self._count -= self._step
        self._sync()

    def reset(self) -> None:
        self._count = 0
        self._sync()

    def _sync(self) -> None:
        if self._panel:
            self._panel.set_count(self._count)  # type: ignore[attr-defined]
        if self._header_widget:
            self._header_widget.set_count(self._count)  # type: ignore[attr-defined]
        self.status_changed.emit(f"Step: {self._step}")
        message_bus.publish(CountChanged(sender_id=self.id, value=self._count, step=self._step))
