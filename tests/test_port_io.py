"""Unit tests for SerialPort port-enumeration filtering.

Pure decision logic — _is_real_device only calls hasVendorIdentifier() and
portName() on its argument, so a small duck-typed stub stands in for
QSerialPortInfo (which can't be constructed with arbitrary VID/name in a test).

The contract: drop Linux's legacy platform UARTs (/dev/ttyS*, which exist by
the dozen whether or not anything is attached) WITHOUT hiding real USB-serial
adapters that report blank manufacturer strings (CH340 and other cheap clones).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.subapps.serial_terminal.port_io import SerialPort


@dataclass
class _FakeInfo:
    """Stand-in for QSerialPortInfo exposing only what _is_real_device reads."""

    name: str
    has_vid: bool

    def portName(self) -> str:  # noqa: N802 (matches Qt API)
        return self.name

    def hasVendorIdentifier(self) -> bool:  # noqa: N802 (matches Qt API)
        return self.has_vid


def _keep(name: str, has_vid: bool) -> bool:
    return SerialPort._is_real_device(_FakeInfo(name, has_vid))


def test_legacy_platform_uart_without_usb_is_dropped() -> None:
    # The /dev/ttyS* flood — no USB identity → filtered out.
    assert _keep("ttyS0", has_vid=False) is False
    assert _keep("ttyS31", has_vid=False) is False


def test_usb_cdc_acm_is_kept() -> None:
    # The typical embedded board (Pico, STM32 CDC) — always has a VID.
    assert _keep("ttyACM0", has_vid=True) is True


def test_usb_serial_adapter_is_kept() -> None:
    assert _keep("ttyUSB0", has_vid=True) is True


def test_cheap_clone_with_blank_strings_is_kept_via_vid() -> None:
    # CH340-style adapter: blank manufacturer/description but a real USB VID.
    # Filtering on description text would wrongly hide it; the VID keeps it.
    assert _keep("ttyUSB0", has_vid=True) is True


def test_windows_com_port_is_kept_even_without_vid() -> None:
    # On Windows COM* names don't start with ttyS; keep regardless of VID so
    # the filter is a no-op there (it targets only Linux's ttyS* noise).
    assert _keep("COM3", has_vid=False) is True


def test_non_usb_non_ttys_port_is_kept() -> None:
    # Virtual/PTY or other transports that aren't bare ttyS* stay visible.
    assert _keep("ttyAMA0", has_vid=False) is True
    assert _keep("rfcomm0", has_vid=False) is True


def test_ttys_with_usb_vid_is_kept() -> None:
    # Defensive: if a USB device ever surfaced as ttyS* with a VID, keep it —
    # the VID branch wins over the name check.
    assert _keep("ttyS5", has_vid=True) is True
