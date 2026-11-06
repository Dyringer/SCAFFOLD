"""Parse `esptool flash_id` output into a `ChipInfo`.

Formats are taken from esptool 4.7 (`__init__.py` main(), `cmds.py`
`flash_id`/`read_mac`), e.g.

    Chip is ESP32-S3 (QFN56) (revision v0.2)
    Features: WiFi, BLE, Embedded PSRAM 8MB (AP_3v3)
    Crystal is 40MHz
    MAC: 34:85:18:aa:bb:cc
    Manufacturer: c8
    Device: 4018
    Detected flash size: 16MB

Pure functions, so they're unit-tested without a device.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CHIP = re.compile(r"^Chip is (?P<chip>.+?)(?: \(revision (?P<rev>v?[\d.]+)\))?$", re.M)
_FEATURES = re.compile(r"^Features: (?P<v>.+)$", re.M)
_CRYSTAL = re.compile(r"^Crystal is (?P<v>\d+)\s*MHz", re.M)
_MAC = re.compile(r"^MAC: (?P<v>[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", re.M)
_MFR = re.compile(r"^Manufacturer: (?P<v>[0-9a-fA-F]+)", re.M)
_DEVICE = re.compile(r"^Device: (?P<v>[0-9a-fA-F]+)", re.M)
_SIZE = re.compile(r"^Detected flash size: (?P<v>\S+)", re.M)
_SIZE_VALUE = re.compile(r"^(\d+)\s*(KB|MB|GB)$", re.I)

# JEDEC manufacturer ids commonly seen on ESP modules.
_MANUFACTURERS = {
    0x20: "XMC", 0x0B: "XTX", 0x1C: "EON", 0x68: "Boya", 0x85: "Puya",
    0x9D: "ISSI", 0xA1: "Fudan", 0xC2: "Macronix", 0xC8: "GigaDevice", 0xEF: "Winbond",
}


@dataclass(frozen=True)
class ChipInfo:
    chip: str = ""
    revision: str = ""
    features: str = ""
    crystal: str = ""
    mac: str = ""
    flash_mfr: str = ""        # hex, e.g. "c8"
    flash_device: str = ""     # hex, e.g. "4018"
    flash_size: str = ""       # as esptool prints it, e.g. "16MB" ("" if unknown)

    @property
    def flash_size_bytes(self) -> int | None:
        m = _SIZE_VALUE.match(self.flash_size)
        if m is None:
            return None
        unit = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}[m.group(2).upper()]
        return int(m.group(1)) * unit

    @property
    def flash_id(self) -> str:
        """`GigaDevice 4018` style label ("" when nothing was read)."""
        if not self.flash_mfr:
            return ""
        name = _MANUFACTURERS.get(int(self.flash_mfr, 16), "")
        ident = f"{self.flash_mfr}/{self.flash_device}" if self.flash_device else self.flash_mfr
        return f"{name}  ({ident})" if name else ident

    @property
    def is_empty(self) -> bool:
        return not any((self.chip, self.flash_mfr, self.flash_size))


def parse_chip_info(text: str) -> ChipInfo:
    """Extract what we can from esptool output; missing fields stay empty."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    def first(pattern: re.Pattern[str], group: str = "v") -> str:
        m = pattern.search(text)
        return (m.group(group) or "").strip() if m else ""

    chip = _CHIP.search(text)
    size = first(_SIZE)
    return ChipInfo(
        chip=(chip.group("chip") if chip else "").strip(),
        revision=(chip.group("rev") or "") if chip else "",
        features=first(_FEATURES),
        crystal=f"{first(_CRYSTAL)} MHz" if _CRYSTAL.search(text) else "",
        mac=first(_MAC).lower(),
        flash_mfr=first(_MFR).lower(),
        flash_device=first(_DEVICE).lower(),
        flash_size="" if size.lower() == "unknown" else size,
    )
