from dataclasses import dataclass
from typing import Callable, TypeVar

from PySide6.QtCore import QObject, Signal

T = TypeVar("T")


@dataclass
class Message:
    sender_id: str


class MessageBus(QObject):
    _signal = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._handlers: dict[type, list[Callable]] = {}
        self._signal.connect(self._dispatch)

    def _dispatch(self, message: object) -> None:
        handlers = self._handlers.get(type(message), [])
        for handler in list(handlers):
            handler(message)

    def publish(self, message: Message) -> None:
        self._signal.emit(message)

    def subscribe(self, msg_type: type[T], handler: Callable[[T], None]) -> None:
        self._handlers.setdefault(msg_type, []).append(handler)

    def unsubscribe(self, msg_type: type[T], handler: Callable[[T], None]) -> None:
        handlers = self._handlers.get(msg_type, [])
        try:
            handlers.remove(handler)
        except ValueError:
            pass


message_bus = MessageBus()
