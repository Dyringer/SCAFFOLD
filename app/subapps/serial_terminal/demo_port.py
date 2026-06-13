"""A synthetic serial source — no hardware, pure Python.

`DemoSerialPort` presents the exact public surface the terminal session uses on
a real `SerialPort` (the same signals, `open`/`close`/`write`/`is_open`), so the
session can open it as if it were a device. It emits plottable telemetry on a
timer, echoes whatever you send, and can be told to misbehave (go silent, or
drop the link) so the freeze-hardening and watchdog paths can be exercised
deliberately without unplugging anything.

Open it from the port list as the "DEMO" entry. While connected, send these
in-band commands (type + Enter, or in raw mode) to drive it:

    :silent       stop emitting (trips the RX-silence watchdog)
    :resume       start emitting again
    :disconnect   fire a synthetic error + close (trips auto-reconnect)
    :fast / :slow change the emit rate

The telemetry is a pure function of the sample index — sine / random-walk /
sawtooth — so it's smooth on the plotter and exactly reproducible in tests
(no wall-clock, no RNG).
"""
from __future__ import annotations

import logging
import math

from PySide6.QtCore import QObject, QTimer, Signal

from app.subapps.serial_terminal.ansi import decode_serial

log = logging.getLogger(__name__)

# The magic port name that selects this source instead of a real COM port.
DEMO_PORT_NAME = "DEMO"
DEMO_PORT_DESC = "synthetic test source"

# The plotter's default series-builder config, matching the demo output out of
# the box so opening DEMO + the Plot tab graphs immediately with no typing.
# X is empty → elapsed-time axis (the demo emits no timestamp, like real
# firmware that just prints readings). Each Y series is its own simple regex
# whose first group is the value; they live on separate demo lines and the
# plotter stitches them onto the shared time axis. Kept next to the line
# formats below so config and data never drift apart.
DEMO_PLOT_CONFIG = {
    "x": "",
    "x_label": "time (s)",
    "series": [
        r"volt=([\d.]+)",
        r"temp=([\d.]+)",
        r"hum=([\d.]+)",
    ],
}

# Emit cadence. Fast/slow commands nudge it between these bounds.
_DEFAULT_INTERVAL_MS = 50
_FAST_INTERVAL_MS = 10
_SLOW_INTERVAL_MS = 250

# Inject a log line every Nth telemetry sample, so the plot data is peppered
# with realistic noise the way a real firmware mixes logs into its UART. The
# plotter must skip these (its unmatched counter ticks up) while the console
# still renders them — a good end-to-end exercise of "telemetry + logs share
# one port".
_LOG_EVERY = 7

# Canned log lines, chosen by index so the sequence is deterministic (no RNG).
# A couple carry ANSI SGR color so the console's ANSI parser is exercised too;
# none of them match the demo plot config's series regexes, by design.
_LOG_LINES: tuple[str, ...] = (
    "[INFO] sensor sampling nominal",
    "\x1b[33m[WARN]\x1b[0m i2c retry on bus 0",
    "[INFO] heap free: 18324 bytes",
    "[DEBUG] adc calibration drift 0.3%",
    "\x1b[31m[ERR]\x1b[0m dropped 1 frame on uart1",
    "[INFO] wifi rssi -64 dBm",
)


def volt_line(index: int) -> str:
    """The voltage reading for sample `index` — its own line, no timestamp.

    A sawtooth ramping 3.00 → 3.98 V over 50 samples then wrapping. Real
    firmware often prints one reading per line like this, with no time field.
    """
    volt = 3.0 + (index % 50) / 50.0
    return f"volt={volt:.3f}"


def env_line(index: int) -> str:
    """The temperature + humidity reading for sample `index` — a separate line.

    temp is a smooth sine; hum is a slow sine plus deterministic jitter (low
    bits of a hash, so it's repeatable without RNG state). Two series on ONE
    line, which together with volt_line's separate line exercises the plotter
    stitching series from different lines onto the shared (time) X axis.
    """
    temp = 25.0 + 5.0 * math.sin(index / 20.0)
    jitter = ((index * 2654435761) & 0xFF) / 255.0  # 0..1, repeatable
    hum = 40.0 + 8.0 * math.sin(index / 53.0) + jitter * 2.0
    return f"temp={temp:.2f} hum={hum:.2f}"


def log_line(index: int) -> str:
    """A canned log line for the given log counter — pure, deterministic.

    Cycles through _LOG_LINES so the sequence is reproducible. None of these
    match the demo plot config's series regexes; they're the realistic noise
    interleaved with the data.
    """
    return _LOG_LINES[index % len(_LOG_LINES)]


class DemoSerialPort(QObject):
    """Drop-in stand-in for SerialPort backed by generated data."""

    # Same signal surface as SerialPort — the session connects these by name.
    data_received = Signal(bytes)
    opened = Signal(str)
    closed = Signal(str)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._open = False
        self._name = DEMO_PORT_NAME
        self._index = 0       # telemetry sample counter (the plot's X)
        self._log_index = 0   # log-line counter, advances independently
        self._silent = False
        self._interval = _DEFAULT_INTERVAL_MS

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._emit_tick)
        # Echo is deferred one event-loop turn so it arrives *after* the local
        # send, like a real device's round-trip rather than synchronously.
        self._echo_queue: list[bytes] = []

    # ------------------------------------------------------------------
    # interface mirrored from SerialPort

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def port_name(self) -> str:
        return self._name

    def open(self, port_name: str, baud: int, **_kwargs) -> bool:
        """Open the synthetic port. `baud` and line settings are accepted and
        ignored — there's no real link to configure."""
        if self._open:
            self.close("reopening")
        self._name = port_name or DEMO_PORT_NAME
        self._open = True
        self._index = 0
        self._log_index = 0
        self._silent = False
        self._interval = _DEFAULT_INTERVAL_MS
        log.info("demo: opened %s", self._name)
        self.opened.emit(self._name)
        self._timer.start(self._interval)
        return True

    def close(self, reason: str = "closed") -> None:
        if not self._open:
            return
        self._timer.stop()
        self._open = False
        log.info("demo: closed %s (%s)", self._name, reason)
        self.closed.emit(reason)

    def write(self, data: bytes) -> int:
        """Accept bytes: interpret in-band commands, otherwise echo them back.

        Returns the byte count (like SerialPort.write) so the session's
        write-failure check (`<= 0`) behaves identically.
        """
        if not self._open or not data:
            return 0
        text = decode_serial(data).strip()
        if text.startswith(":") and self._handle_command(text):
            return len(data)
        # Not a command → behave like a device that echoes its input. Defer so
        # the echo lands after the caller's local echo, as a real one would.
        self._echo_queue.append(data)
        QTimer.singleShot(20, self._flush_echo)
        return len(data)

    # ------------------------------------------------------------------
    # synthetic behaviour

    def _emit_tick(self) -> None:
        if not self._open or self._silent:
            return
        # Every Nth sample, interleave a log line so the stream mixes telemetry
        # with realistic noise — the plotter skips it, the console shows it.
        if self._index and self._index % _LOG_EVERY == 0:
            note = log_line(self._log_index) + "\n"
            self._log_index += 1
            self.data_received.emit(note.encode("utf-8"))

        # Emit the two telemetry lines separately, like firmware printing each
        # reading on its own line. The plotter stitches volt / temp / hum onto
        # the shared time axis even though they arrive on different lines.
        self.data_received.emit((volt_line(self._index) + "\n").encode("utf-8"))
        self.data_received.emit((env_line(self._index) + "\n").encode("utf-8"))
        self._index += 1

    def _flush_echo(self) -> None:
        if not self._open:
            self._echo_queue.clear()
            return
        while self._echo_queue:
            self.data_received.emit(self._echo_queue.pop(0))

    def _handle_command(self, text: str) -> bool:
        """Apply a `:command`. Returns True if it was a recognised command."""
        cmd = text.lower()
        if cmd == ":silent":
            self._silent = True
            self._note("going silent — RX-silence watchdog should fire")
            return True
        if cmd == ":resume":
            self._silent = False
            self._note("resuming telemetry")
            return True
        if cmd == ":disconnect":
            self._note("simulating a device drop")
            # Mirror a real fatal error: surface it, then close on the next
            # turn so we never tear down from inside the write() call.
            self.error.emit("demo: simulated device disconnect")
            QTimer.singleShot(0, lambda: self.close("demo disconnect"))
            return True
        if cmd == ":fast":
            self._interval = _FAST_INTERVAL_MS
            self._timer.start(self._interval)
            self._note("emit rate → fast")
            return True
        if cmd == ":slow":
            self._interval = _SLOW_INTERVAL_MS
            self._timer.start(self._interval)
            self._note("emit rate → slow")
            return True
        # Unrecognised ':' token — let it fall through and echo, so it's visible.
        return False

    def _note(self, msg: str) -> None:
        """Echo an italicised note back through the data stream so it shows up
        in the console like device output."""
        self.data_received.emit(f"[demo] {msg}\n".encode())
