from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

from app.subapps.serial_terminal.win_ports import bus_reported_names

log = logging.getLogger(__name__)


# Standard baud rates offered in the toolbar. 115200 is the embedded default.
BAUD_RATES: list[int] = [
    1200, 2400, 4800, 9600, 19200, 38400, 57600,
    115200, 230400, 460800, 921600,
]

# If bytes are queued for transmit and *none* drain within this many ms, the
# device has stopped accepting data (firmware hung, CDC TX path wedged). write()
# only queues into QSerialPort's buffer and returns immediately, so without this
# a dead device produces no error — bytes just pile up silently forever. On a
# stall we raise it as a ResourceError-equivalent so the normal fatal-error path
# (close + optional auto-reconnect) recovers it. 3 s is far longer than any real
# drain at the supported baud rates, so a healthy-but-busy link never trips it.
_TX_STALL_MS = 3000


class SerialPort(QObject):
    """Thin, event-driven wrapper around QSerialPort.

    QtSerialPort is fully asynchronous — `readyRead` fires on the Qt event
    loop whenever bytes arrive, so there is no background read thread to
    manage or join on shutdown. The owner just connects to `data_received`.
    """

    data_received = Signal(bytes)
    opened = Signal(str)        # port name
    closed = Signal(str)        # reason
    error = Signal(str)         # human-readable message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._port = QSerialPort(self)
        self._port.readyRead.connect(self._on_ready_read)
        self._port.errorOccurred.connect(self._on_error)
        self._port.bytesWritten.connect(self._on_bytes_written)
        # Guards re-entrancy: closing a QSerialPort during surprise-removal can
        # synchronously fire errorOccurred again before close() returns.
        self._closing = False

        # TX-stall watchdog: outstanding (queued-but-not-yet-drained) bytes and
        # a single-shot timer that fires if they don't drain within _TX_STALL_MS.
        self._tx_outstanding = 0
        self._tx_timer = QTimer(self)
        self._tx_timer.setSingleShot(True)
        self._tx_timer.setInterval(_TX_STALL_MS)
        self._tx_timer.timeout.connect(self._on_tx_stall)

    # ------------------------------------------------------------------
    # enumeration

    @staticmethod
    def _is_real_device(info: QSerialPortInfo) -> bool:
        """Whether a port is a device a user would actually connect to.

        Linux exposes every legacy 8250/16550 platform UART as `/dev/ttyS0..N`
        (often 4-32 of them) whether or not anything is attached — pure noise
        that buries the one USB adapter the user cares about. We drop those.

        The discriminator is a USB identity, NOT a non-empty description:
        cheap-but-real USB-serial chips (CH340, some CP210x/FTDI clones) often
        report blank manufacturer/description strings, so filtering on text
        alone would hide exactly the bargain adapters an embedded dev plugs in.
        A genuine USB-serial device always exposes a USB vendor id; a platform
        `ttyS*` never does. So: keep anything with a vendor id, and keep
        anything that isn't a bare `ttyS*` (covers Windows COM*, ttyACM*,
        ttyUSB*, virtual/PTY ports, and any future non-USB transport).
        """
        if info.hasVendorIdentifier():
            return True
        return not info.portName().startswith("ttyS")

    @staticmethod
    def available_ports() -> list[tuple[str, str]]:
        """Return [(port_name, description)] for all detected serial ports.

        On Windows these are `COM*`; on Linux QtSerialPort surfaces
        `/dev/ttyACM*` and `/dev/ttyUSB*` (and others) automatically. Legacy
        platform UARTs (`/dev/ttyS*` with no USB identity) are filtered out —
        see _is_real_device.

        The description is enriched with the per-interface "bus reported"
        name when available (Windows), so the two CDC interfaces of a
        composite device that share one product name can be told apart —
        e.g. "PICO_CORE - Console" vs "PICO_CORE - DCP". Qt doesn't expose
        this; see win_ports.bus_reported_names().
        """
        bus = bus_reported_names()
        out: list[tuple[str, str]] = []
        for info in QSerialPortInfo.availablePorts():
            if not SerialPort._is_real_device(info):
                continue
            name = info.portName()
            desc = info.description() or info.manufacturer() or ""
            iface = bus.get(name, "")
            if iface and iface != desc:
                desc = f"{desc} - {iface}" if desc else iface
            out.append((name, desc))
        return out

    # ------------------------------------------------------------------
    # lifecycle

    @property
    def is_open(self) -> bool:
        return self._port.isOpen()

    @property
    def port_name(self) -> str:
        return self._port.portName()

    def open(
        self,
        port_name: str,
        baud: int,
        *,
        data_bits: QSerialPort.DataBits = QSerialPort.Data8,
        parity: QSerialPort.Parity = QSerialPort.NoParity,
        stop_bits: QSerialPort.StopBits = QSerialPort.OneStop,
    ) -> bool:
        """Open `port_name` at `baud` (8N1 by default). Returns success."""
        if self._port.isOpen():
            self.close("reopening")

        self._port.setPortName(port_name)
        self._port.setBaudRate(int(baud))
        self._port.setDataBits(data_bits)
        self._port.setParity(parity)
        self._port.setStopBits(stop_bits)
        self._port.setFlowControl(QSerialPort.NoFlowControl)

        if not self._port.open(QSerialPort.ReadWrite):
            msg = self._port.errorString() or "failed to open"
            log.warning("serial: open %s @ %d failed: %s", port_name, baud, msg)
            self.error.emit(f"{port_name}: {msg}")
            return False

        # Assert DTR (and RTS) like a real terminal (PuTTY/MobaXterm do this on
        # open). Many USB CDC-ACM devices (Pico, STM32 USB CDC, …) gate their
        # TX on the host raising DTR — without this they stay silent until some
        # other app opens the port and raises it. With NoFlowControl QSerialPort
        # leaves both lines low, so we set them explicitly. Guard in case the
        # device vanishes between open() and here.
        try:
            self._port.setDataTerminalReady(True)
            self._port.setRequestToSend(True)
        except Exception:
            pass

        log.info("serial: opened %s @ %d (DTR/RTS asserted)", port_name, baud)
        self.opened.emit(port_name)
        return True

    def close(self, reason: str = "closed") -> None:
        # Re-entrancy guard: QSerialPort.close() can synchronously re-emit
        # errorOccurred (NotOpen/Resource) on a surprise-removal, which would
        # land us back in _on_error -> close() while we're mid-teardown.
        if self._closing or not self._port.isOpen():
            return
        self._closing = True
        try:
            name = self._port.portName()
            # Stop the TX watchdog and forget any outstanding bytes — the
            # handle is going away, so a pending stall timer must not fire.
            self._reset_tx()
            # Drop DTR/RTS before closing; ignore failures on a dead handle.
            try:
                self._port.setDataTerminalReady(False)
                self._port.setRequestToSend(False)
            except Exception:
                pass
            self._port.clearError()
            self._port.close()
            log.info("serial: closed %s (%s)", name, reason)
        finally:
            self._closing = False
        self.closed.emit(reason)

    # ------------------------------------------------------------------
    # io

    def write(self, data: bytes) -> int:
        """Queue raw bytes for transmit. Returns bytes accepted (0 if closed).

        QSerialPort.write() buffers and returns immediately; the bytes drain
        asynchronously and bytesWritten reports progress. We track the
        outstanding count and arm the stall watchdog so a device that stops
        draining is detected instead of silently swallowing writes forever.
        """
        if not self._port.isOpen() or not data:
            return 0
        n = self._port.write(data)
        written = int(n) if n is not None else 0
        if written > 0:
            self._tx_outstanding += written
            # (Re)arm the watchdog: there are now unflushed bytes. Each
            # bytesWritten that doesn't fully drain restarts it from here.
            self._tx_timer.start()
        return written

    def _on_bytes_written(self, count: int) -> None:
        # Bytes drained: decrement and either disarm (all flushed) or restart
        # the countdown (progress was made, give the rest a fresh window).
        self._tx_outstanding = max(0, self._tx_outstanding - int(count))
        if self._tx_outstanding == 0:
            self._tx_timer.stop()
        else:
            self._tx_timer.start()

    def _on_tx_stall(self) -> None:
        # Queued bytes never drained: the device has stopped accepting data.
        # Treat it exactly like a resource error so the owner's fatal-error
        # path (close + optional auto-reconnect) recovers the connection.
        if self._closing or not self._port.isOpen() or self._tx_outstanding == 0:
            return
        log.warning(
            "serial: TX stalled on %s — %d byte(s) undrained after %d ms",
            self._port.portName(), self._tx_outstanding, _TX_STALL_MS,
        )
        self._reset_tx()
        self.error.emit("transmit stalled — device not accepting data")
        if self._port.isOpen():
            QTimer.singleShot(0, lambda: self.close("transmit stalled"))

    def _reset_tx(self) -> None:
        self._tx_timer.stop()
        self._tx_outstanding = 0

    def _on_ready_read(self) -> None:
        # The device may vanish between the readyRead signal and this call;
        # reading a dead handle is a no-op but guard it anyway.
        if not self._port.isOpen():
            return
        chunk = self._port.readAll()
        if chunk:
            self.data_received.emit(bytes(chunk.data()))

    def _on_error(self, err: QSerialPort.SerialPortError) -> None:
        if err == QSerialPort.NoError or self._closing:
            return
        msg = self._port.errorString() or str(err)
        log.warning("serial: error on %s: %s", self._port.portName(), msg)
        self.error.emit(msg)
        # ResourceError = device pulled / driver gone. Also treat any error
        # while the port is open as fatal to the connection. Defer the close
        # to the next event-loop turn so we never tear the port down from
        # *inside* its own errorOccurred handler (that re-entrancy is what
        # faults on Windows surprise-removal).
        fatal = err in (
            QSerialPort.ResourceError,
            QSerialPort.PermissionError,
            QSerialPort.DeviceNotFoundError,
        )
        if fatal and self._port.isOpen() and not self._closing:
            QTimer.singleShot(0, lambda: self.close("device disconnected"))
