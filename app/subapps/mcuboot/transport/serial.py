"""USB CDC / UART SMP transport using the mcumgr serial framing.

Frame: body = u16be(len(packet)+2) + packet + u16be(crc16_ccitt(packet)),
base64-encoded and split into lines of <=127 bytes (incl. 2-byte marker and
the trailing newline). First line starts 0x06 0x09, continuation lines 0x04 0x14.

I/O uses QSerialPort's blocking API and must be used from a single worker
thread (open/send/recv/close all on that thread), never the GUI thread.
"""
from __future__ import annotations

import base64
import binascii
import time
from typing import Any, ClassVar

from app.subapps.mcuboot.transport.base import Transport

START_MARK = b"\x06\x09"
CONT_MARK = b"\x04\x14"
MAX_LINE = 127
# base64 chars per line; multiple of 4 so each line decodes independently.
_B64_PER_LINE = ((MAX_LINE - len(START_MARK) - 1) // 4) * 4  # 124
_RAW_PER_LINE = _B64_PER_LINE // 4 * 3  # 93
_MAX_PARTIAL = 1024  # drop console junk longer than this without a newline


def crc16_ccitt(data: bytes, crc: int = 0) -> int:
    """CRC16-CCITT, poly 0x1021, init 0, no reflection."""
    return binascii.crc_hqx(data, crc)


def encode_frames(packet: bytes) -> bytes:
    packet = bytes(packet)
    body = (len(packet) + 2).to_bytes(2, "big") + packet \
        + crc16_ccitt(packet).to_bytes(2, "big")
    out = bytearray()
    for i in range(0, len(body), _RAW_PER_LINE):
        out += START_MARK if i == 0 else CONT_MARK
        out += base64.b64encode(body[i:i + _RAW_PER_LINE])
        out += b"\n"
    return bytes(out)


class FrameDecoder:
    """Incremental decoder. Frames with a bad CRC/base64/length are dropped
    and counted in ``errors``; other (console) text is ignored."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._acc: bytearray | None = None
        self.errors = 0

    def feed(self, data: bytes) -> list[bytes]:
        self._buf += data
        packets: list[bytes] = []
        while True:
            nl = self._buf.find(b"\n")
            if nl < 0:
                if len(self._buf) > _MAX_PARTIAL:
                    self._buf.clear()
                break
            line = bytes(self._buf[:nl]).rstrip(b"\r")
            del self._buf[:nl + 1]
            pkt = self._line(line)
            if pkt is not None:
                packets.append(pkt)
        return packets

    def _line(self, line: bytes) -> bytes | None:
        # Marker bytes never occur in base64, so search anywhere in the line
        # (console text may precede the frame on the same line).
        s = line.find(START_MARK)
        c = line.find(CONT_MARK)
        if s >= 0 and (c < 0 or s < c):
            self._acc = bytearray()
            payload = line[s + 2:]
        elif c >= 0:
            if self._acc is None:
                return None
            payload = line[c + 2:]
        else:
            return None
        acc = self._acc
        assert acc is not None
        try:
            acc += base64.b64decode(payload.strip(), validate=True)
        except (binascii.Error, ValueError):
            self.errors += 1
            self._acc = None
            return None
        if len(acc) < 2:
            return None
        total = int.from_bytes(acc[:2], "big")
        if total < 2:
            self.errors += 1
            self._acc = None
            return None
        if len(acc) < 2 + total:
            return None
        self._acc = None
        if len(acc) != 2 + total:
            self.errors += 1
            return None
        packet = bytes(acc[2:-2])
        if crc16_ccitt(packet) != int.from_bytes(acc[-2:], "big"):
            self.errors += 1
            return None
        return packet


class SerialTransport(Transport):
    key: ClassVar[str] = "usb"
    label: ClassVar[str] = "USB CDC (serial)"
    available: ClassVar[bool] = True

    def __init__(self, port: str, baud: int = 115200, mtu: int = 256) -> None:
        self.port = port
        self.baud = baud
        self.mtu = mtu
        self._sp: Any = None
        self._decoder = FrameDecoder()
        self._ready: list[bytes] = []

    @property
    def is_open(self) -> bool:
        return self._sp is not None and self._sp.isOpen()

    def open(self) -> None:
        from PySide6.QtSerialPort import QSerialPort

        sp = QSerialPort()
        sp.setPortName(self.port)
        sp.setBaudRate(int(self.baud))
        sp.setDataBits(QSerialPort.Data8)
        sp.setParity(QSerialPort.NoParity)
        sp.setStopBits(QSerialPort.OneStop)
        sp.setFlowControl(QSerialPort.NoFlowControl)
        if not sp.open(QSerialPort.ReadWrite):
            raise OSError(f"{self.port}: {sp.errorString() or 'failed to open'}")
        try:  # many CDC-ACM devices gate TX on DTR
            sp.setDataTerminalReady(True)
            sp.setRequestToSend(True)
        except Exception:
            pass
        sp.clear()
        self._sp = sp
        self._decoder = FrameDecoder()
        self._ready = []

    def close(self) -> None:
        sp, self._sp = self._sp, None
        if sp is None:
            return
        if sp.isOpen():
            try:
                sp.setDataTerminalReady(False)
                sp.setRequestToSend(False)
            except Exception:
                pass
            sp.close()

    def send(self, packet: bytes) -> None:
        sp = self._require()
        data = encode_frames(packet)
        sent = 0
        while sent < len(data):
            n = sp.write(data[sent:sent + 256])
            if n < 0:
                raise OSError(sp.errorString() or "serial write failed")
            sent += n
            if not sp.waitForBytesWritten(3000):
                raise OSError("serial write timed out")

    def recv(self, timeout: float) -> bytes:
        sp = self._require()
        deadline = time.monotonic() + timeout
        while True:
            if self._ready:
                return self._ready.pop(0)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no SMP response")
            if sp.bytesAvailable() > 0 or sp.waitForReadyRead(
                max(1, int(min(remaining, 0.25) * 1000))
            ):
                chunk = bytes(sp.readAll().data())
                if chunk:
                    self._ready.extend(self._decoder.feed(chunk))

    def _require(self) -> Any:
        if self._sp is None or not self._sp.isOpen():
            raise OSError("serial port is not open")
        return self._sp
