"""SMP transport registry. "usb" is first and therefore the default."""
from __future__ import annotations

from dataclasses import dataclass

from app.subapps.mcuboot.transport.base import Transport
from app.subapps.mcuboot.transport.ble import BleTransport
from app.subapps.mcuboot.transport.serial import SerialTransport

__all__ = [
    "DEFAULT_TRANSPORT", "TRANSPORTS", "BleTransport", "SerialTransport",
    "Transport", "TransportInfo",
]


@dataclass(frozen=True)
class TransportInfo:
    key: str
    label: str
    available: bool
    factory: type[Transport]


def _info(cls: type[Transport]) -> TransportInfo:
    return TransportInfo(cls.key, cls.label, cls.available, cls)


TRANSPORTS: dict[str, TransportInfo] = {
    SerialTransport.key: _info(SerialTransport),
    BleTransport.key: _info(BleTransport),
}
DEFAULT_TRANSPORT = "usb"
