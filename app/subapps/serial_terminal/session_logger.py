"""Capture a serial session to a file.

Two modes:

* RAW   — the received bytes, verbatim. Byte-identical to what arrived, so the
          file can later be re-fed to the plotter and reproduce the exact same
          series. RX only (TX would corrupt the byte stream).
* TRANSCRIPT — a human-readable record of both directions, line-assembled per
          direction and tagged `RX`/`TX`. No timestamps (yet). TX lines are the
          commands you sent; RX lines are device output, so a plot regex still
          matches the RX bodies if this file is re-fed.

The writer holds an open file handle and appends incrementally with a periodic
flush — the point of logging is to survive a crash, so we don't buffer the
whole session in memory, but we also don't fsync per write (that would throttle
a fast stream). Kept deliberately small and free of Qt so it's unit-testable
with a tmp file.
"""
from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)


class LogMode(Enum):
    RAW = "raw"               # verbatim RX bytes — re-feedable to the plotter
    TRANSCRIPT = "transcript"  # RX+TX, line-assembled, RX/TX tagged

    @property
    def default_suffix(self) -> str:
        return ".log.bin" if self is LogMode.RAW else ".log"


# Transcript line prefix per direction.
_DIRECTION_TAG = {"rx": b"RX ", "tx": b"TX "}


class SessionLogger:
    """Appends serial traffic to a file until stopped.

    Lifecycle: `start(path, mode)` opens the file; `write(direction, data)` is
    called for every chunk (both "rx" and "tx"); `stop()` flushes and closes.
    A logger that isn't started silently ignores writes, so the caller can tap
    it unconditionally.
    """

    def __init__(self) -> None:
        self._fh = None
        self._mode = LogMode.RAW
        self._path: Path | None = None
        # Per-direction partial-line carry for TRANSCRIPT mode: bytes arrive
        # unaligned to newlines, so we buffer until we have whole lines and
        # never split a line across a direction marker.
        self._carry: dict[str, bytes] = {"rx": b"", "tx": b""}
        self._written = 0
        self._lines = 0

    @property
    def is_logging(self) -> bool:
        return self._fh is not None

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def mode(self) -> LogMode:
        return self._mode

    @property
    def bytes_written(self) -> int:
        return self._written

    @property
    def lines_written(self) -> int:
        """Lines written so far. Meaningful only in TRANSCRIPT mode; 0 in RAW
        (a faithful byte capture has no line concept)."""
        return self._lines

    def start(self, path: str | Path, mode: LogMode) -> None:
        """Open `path` for logging in `mode`. Replaces any current session."""
        if self._fh is not None:
            self.stop()
        self._path = Path(path)
        self._mode = mode
        self._carry = {"rx": b"", "tx": b""}
        self._written = 0
        self._lines = 0
        # Binary append: RAW writes bytes directly; TRANSCRIPT writes UTF-8
        # encoded text, but using a binary handle keeps both paths uniform and
        # avoids newline translation mangling a faithful capture.
        self._fh = open(self._path, "wb")  # noqa: SIM115 (handle lives until stop)
        log.info("serial: logging to %s (%s)", self._path, mode.value)

    def write(self, direction: str, data: bytes) -> None:
        """Record one chunk. `direction` is "rx" or "tx". No-op when stopped."""
        if self._fh is None or not data:
            return
        if self._mode is LogMode.RAW:
            # Faithful capture is RX only — interleaving TX would corrupt the
            # byte stream we promise is replayable.
            if direction == "rx":
                self._fh.write(data)
                self._written += len(data)
        else:
            self._write_transcript(direction, data)
        # Periodic-ish durability without fsync: flushing the Python buffer to
        # the OS each chunk is cheap and means a crash loses at most the OS
        # page cache, not our in-process buffer.
        self._fh.flush()

    def _write_transcript(self, direction: str, data: bytes) -> None:
        # Assemble complete lines for this direction so a tag never lands
        # mid-line. Whatever has no newline yet is carried to the next chunk.
        buf = self._carry.get(direction, b"") + data
        *lines, tail = buf.split(b"\n")
        self._carry[direction] = tail
        tag = _DIRECTION_TAG[direction]
        for line in lines:
            line = line.rstrip(b"\r")
            out = tag + line + b"\n"
            self._fh.write(out)
            self._written += len(out)
            self._lines += 1

    def stop(self) -> None:
        """Flush carried partial lines and close the file."""
        if self._fh is None:
            return
        # In transcript mode, emit any trailing partial line so nothing is lost.
        if self._mode is LogMode.TRANSCRIPT:
            for direction in ("rx", "tx"):
                rest = self._carry.get(direction, b"")
                if rest:
                    self._fh.write(_DIRECTION_TAG[direction] + rest.rstrip(b"\r") + b"\n")
                    self._lines += 1
            self._carry = {"rx": b"", "tx": b""}
        try:
            self._fh.flush()
            self._fh.close()
        finally:
            self._fh = None
        log.info("serial: stopped logging %s (%d bytes)", self._path, self._written)
