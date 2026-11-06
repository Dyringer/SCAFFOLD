"""Turn esptool's console output into structured progress events.

esptool has no machine-readable progress mode; it prints human text. When its
stdout is a pipe (not a TTY) every progress update is a full line, flushed
immediately — e.g.

    Connecting....
    Chip is ESP32-S3 (QFN56) (revision v0.2)
    Erasing flash (this may take a while)...
    Writing at 0x00010000... (3 %)
    Wrote 1048576 bytes (612345 compressed) at 0x00010000 in 9.1 seconds ...
    Hash of data verified.
    12345 (7 %)                 <- read_flash progress (see `Stage.READING`)
    Hard resetting via RTS pin...
    A fatal error occurred: Failed to connect to ESP32-S3: No serial data received.

`parse_line` maps one such line to a `FlashEvent` (or None for chatter we
don't act on). It is pure so it can be unit-tested without a device.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Stage(Enum):
    CONNECTING = "Connecting"
    CHIP = "Chip detected"
    ERASING = "Erasing"
    WRITING = "Writing"
    WROTE = "Wrote"          # one image finished (esptool repeats per image)
    READING = "Reading"      # read_flash: "<bytes> (<pct> %)"
    READ = "Read"            # read_flash finished
    VERIFIED = "Verified"
    RESETTING = "Resetting"
    ERROR = "Error"


@dataclass(frozen=True)
class FlashEvent:
    stage: Stage
    percent: int | None = None
    detail: str = ""


_RULES: list[tuple[re.Pattern[str], Stage]] = [
    (re.compile(r"^Connecting"), Stage.CONNECTING),
    (re.compile(r"^Chip is (?P<detail>.+)$"), Stage.CHIP),
    (re.compile(r"^Erasing (flash|region)"), Stage.ERASING),
    (re.compile(r"^Writing at 0x[0-9a-fA-F]+\.\.\. \((?P<pct>\d+) %\)"), Stage.WRITING),
    (re.compile(r"^Wrote \d+ bytes"), Stage.WROTE),
    (re.compile(r"^\d+ \((?P<pct>\d+) %\)$"), Stage.READING),
    (re.compile(r"^Read \d+ bytes"), Stage.READ),
    (re.compile(r"^Hash of data verified"), Stage.VERIFIED),
    (re.compile(r"^Hard resetting"), Stage.RESETTING),
    (re.compile(r"A fatal error occurred: (?P<detail>.+)$"), Stage.ERROR),
]


def parse_line(line: str) -> FlashEvent | None:
    line = line.strip()
    if not line:
        return None
    for pattern, stage in _RULES:
        m = pattern.search(line)
        if m is None:
            continue
        groups = m.groupdict()
        if stage in (Stage.WRITING, Stage.READING):
            return FlashEvent(stage, percent=max(0, min(100, int(groups["pct"]))))
        if stage in (Stage.WROTE, Stage.READ):
            return FlashEvent(stage, percent=100)
        return FlashEvent(stage, detail=(groups.get("detail") or "").strip())
    return None
