"""A file-backed serial source — replays a captured file as if it were a device.

`FileSerialPort` presents the same interface the session uses on a real
`SerialPort` (signals + open/close/write/is_open/port_name), but `open()` reads
a file from disk and emits its bytes through `data_received` instead of talking
to hardware. Feeding the bytes through the normal RX path means the console and
the plotter render a loaded file exactly as they would a live session — so a
`.log.bin` raw capture replays to the identical plot.

Bytes are emitted in bounded chunks (not one giant signal) so the line
assembler and coalesced renderer behave as with streamed data and a large file
never hitches the UI with a single multi-MB emit. After the whole file is sent
the port stays "open" but idle (no more data) until the user disconnects.

The path is supplied by the UI (which owns the file dialog) via `set_path`
before `connect()` calls `open()`.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

# The magic port name that selects this source, and its list description.
FILE_PORT_NAME = "FILE"
FILE_PORT_DESC = "replay a captured file"

# Emit the file in chunks this size so the RX path sees streamed data, not one
# enormous signal. 64 KB is large enough to be "instant" yet bounds each emit.
_CHUNK = 64 * 1024


class FileSerialPort(QObject):
    """Drop-in stand-in for SerialPort that replays a file's bytes."""

    # Same signal surface as SerialPort — the session connects these by name.
    data_received = Signal(bytes)
    opened = Signal(str)
    closed = Signal(str)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._open = False
        self._name = FILE_PORT_NAME
        self._path: Path | None = None

    # ------------------------------------------------------------------
    # interface mirrored from SerialPort

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def port_name(self) -> str:
        return self._name

    def set_path(self, path: str | Path) -> None:
        """Choose the file to replay on the next open(). Set by the UI before
        connect(), since the file dialog lives in the UI layer."""
        self._path = Path(path)

    def open(self, port_name: str, baud: int, **_kwargs) -> bool:
        """Load the chosen file and emit its bytes. `baud`/line settings are
        accepted and ignored — there's nothing to configure on a file.

        Returns False (and emits `error`) if no path was set or the file can't
        be read, mirroring SerialPort.open's failure contract.
        """
        if self._open:
            self.close("reopening")
        if self._path is None:
            self.error.emit("no file selected")
            return False
        try:
            data = self._path.read_bytes()
        except OSError as exc:
            log.warning("file: cannot read %s: %s", self._path, exc)
            self.error.emit(f"{self._path}: {exc}")
            return False

        self._name = port_name or FILE_PORT_NAME
        self._open = True
        log.info("file: opened %s (%d bytes)", self._path, len(data))
        self.opened.emit(self._name)

        # Emit in bounded chunks so the line assembler / coalesced renderer see
        # streamed input. No inter-chunk delay — the load is effectively instant.
        for start in range(0, len(data), _CHUNK):
            self.data_received.emit(data[start:start + _CHUNK])
        # EOF: stay open but idle. The data is on screen; the user disconnects
        # to free the source (close() below).
        return True

    def close(self, reason: str = "closed") -> None:
        if not self._open:
            return
        self._open = False
        log.info("file: closed %s (%s)", self._name, reason)
        self.closed.emit(reason)

    def write(self, data: bytes) -> int:
        """A file can't receive input — accept nothing. Returning 0 makes the
        session's write-failure check behave as with a closed port."""
        return 0
