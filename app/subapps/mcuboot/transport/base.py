"""Transport interface for SMP: moves whole SMP packets, framing is private."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar


class Transport(ABC):
    key: ClassVar[str]
    label: ClassVar[str]
    available: ClassVar[bool] = True

    #: Max SMP packet bytes (header + payload) per send.
    mtu: int = 256

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    @abstractmethod
    def send(self, packet: bytes) -> None:
        """Send one whole SMP packet."""

    @abstractmethod
    def recv(self, timeout: float) -> bytes:
        """Receive one whole SMP packet; raises TimeoutError."""
