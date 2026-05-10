from abc import ABCMeta, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget

from app.core.settings_store import SettingDef


class SubAppState(Enum):
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"


@dataclass
class CommandDef:
    id: str
    label: str
    callback: Callable[[], None]
    shortcut: str | None = field(default=None)
    icon: QIcon | None = field(default=None)


class _Meta(type(QObject), ABCMeta):
    pass


class BaseSubApp(QObject, metaclass=_Meta):
    status_changed = Signal(str)
    state_changed = Signal(SubAppState)

    id: str = ""
    name: str = ""
    icon: QIcon
    hidden: bool = False

    @abstractmethod
    def create_body(self) -> QWidget: ...

    def create_header_widget(self) -> QWidget | None:
        return None

    def get_settings(self) -> list[SettingDef]:
        return []

    def get_commands(self) -> list[CommandDef]:
        return []

    def on_activated(self) -> None:
        pass

    def on_deactivated(self) -> None:
        pass

    def run_async(
        self,
        fn: Callable,
        on_done: Callable,
        on_error: Callable | None = None,
    ) -> None:
        from app.core.async_runner import async_runner
        async_runner.run(fn, on_done, on_error)
