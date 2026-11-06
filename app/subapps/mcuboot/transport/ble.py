"""Bluetooth LE SMP transport (stub).

BLE carries raw SMP packets (no serial framing), split to the ATT MTU, written
to / notified from the SMP characteristic. It is planned via a BLE library
like bleak.
"""
from __future__ import annotations

from typing import ClassVar

from app.subapps.mcuboot.transport.base import Transport

SMP_SERVICE_UUID = "8D53DC1D-1DB7-4CD3-868B-8A527460AA84"
SMP_CHARACTERISTIC_UUID = "DA2E7828-FBCE-4E01-AE9E-261174997C48"

_NOT_IMPL = "BLE transport is not implemented yet"


class BleTransport(Transport):
    key: ClassVar[str] = "ble"
    label: ClassVar[str] = "Bluetooth LE"
    available: ClassVar[bool] = False

    def __init__(self, address: str, mtu: int = 244) -> None:
        self.address = address
        self.mtu = mtu

    def open(self) -> None:
        raise NotImplementedError(_NOT_IMPL)

    def close(self) -> None:
        pass

    @property
    def is_open(self) -> bool:
        return False

    def send(self, packet: bytes) -> None:
        raise NotImplementedError(_NOT_IMPL)

    def recv(self, timeout: float) -> bytes:
        raise NotImplementedError(_NOT_IMPL)
