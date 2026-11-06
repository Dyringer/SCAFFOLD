"""Firmware-image helpers: suggest a flash offset for a chosen .bin file.

ESP-IDF / Arduino / Zephyr builds produce either
  * a *merged* image (bootloader + partition table + app) flashed at 0x0, or
  * separate images: bootloader (0x0 on S3/C3/C6/H2, 0x1000 on ESP32/S2),
    partition table (0x8000) and the app (conventionally 0x10000).

A merged image is recognisable by the partition-table magic (0xAA 0x50) at
offset 0x8000 inside the file; an app/bootloader image starts with the ESP
image magic 0xE9. Anything else is left to the user (returns None).
"""
from __future__ import annotations

from pathlib import Path

ESP_IMAGE_MAGIC = 0xE9
PARTITION_MAGIC = b"\xaa\x50"
PARTITION_TABLE_OFFSET = 0x8000
APP_OFFSET = 0x10000

# Offsets offered in each image row's picker.
OFFSET_PRESETS: list[int] = [0x0, 0x1000, 0x8000, APP_OFFSET]


def guess_offset(path: str | Path) -> int | None:
    """Best-effort flash offset for `path`, or None if it can't be told."""
    try:
        with open(path, "rb") as f:
            data = f.read(PARTITION_TABLE_OFFSET + len(PARTITION_MAGIC))
    except OSError:
        return None
    if not data:
        return None
    if data[:2] == PARTITION_MAGIC:
        return PARTITION_TABLE_OFFSET
    if data[PARTITION_TABLE_OFFSET:] == PARTITION_MAGIC:
        return 0x0
    # A lone bootloader is also 0xE9 but always < 32 KiB; its offset is
    # chip-dependent (0x0 vs 0x1000), so don't guess for small images.
    if data[0] == ESP_IMAGE_MAGIC and len(data) > PARTITION_TABLE_OFFSET:
        return APP_OFFSET
    return None


def parse_offset(text: str) -> int | None:
    """Parse "0x10000", "10000h", or "65536" (leading token only) -> int."""
    token = text.strip().split()[0] if text.strip() else ""
    if not token:
        return None
    try:
        if token.lower().endswith("h"):
            return int(token[:-1], 16)
        return int(token, 0)
    except ValueError:
        return None
