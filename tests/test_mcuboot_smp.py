"""SMP client, CBOR codec and serial framing tests. No hardware."""
from __future__ import annotations

import hashlib
import math
import threading
from typing import Any

import pytest

from app.subapps.mcuboot import cbor
from app.subapps.mcuboot.cbor import CborError
from app.subapps.mcuboot.smp import (
    GROUP_IMAGE,
    GROUP_OS,
    IMG_ERASE,
    IMG_STATE,
    IMG_UPLOAD,
    OP_READ,
    OP_READ_RSP,
    OP_WRITE,
    OP_WRITE_RSP,
    OS_ECHO,
    OS_RESET,
    SlotState,
    SmpCancelled,
    SmpClient,
    SmpError,
    decode_packet,
    encode_packet,
)
from app.subapps.mcuboot.transport import DEFAULT_TRANSPORT, TRANSPORTS
from app.subapps.mcuboot.transport.base import Transport
from app.subapps.mcuboot.transport.serial import (
    FrameDecoder,
    SerialTransport,
    crc16_ccitt,
    encode_frames,
)

# ---------------------------------------------------------------- CBOR


@pytest.mark.parametrize("obj,hexs", [
    (0, "00"), (1, "01"), (23, "17"), (24, "1818"), (100, "1864"),
    (1000, "1903e8"), (1000000, "1a000f4240"),
    (1000000000000, "1b000000e8d4a51000"),
    (18446744073709551615, "1bffffffffffffffff"),
    (-1, "20"), (-10, "29"), (-100, "3863"), (-1000, "3903e7"),
    (False, "f4"), (True, "f5"), (None, "f6"),
    (b"", "40"), (b"\x01\x02\x03\x04", "4401020304"),
    ("", "60"), ("a", "6161"), ("IETF", "6449455446"), ("ü", "62c3bc"),
    ([], "80"), ([1, 2, 3], "83010203"), ([1, [2, 3]], "8201820203"),
    ({}, "a0"), ({1: 2, 3: 4}, "a201020304"),
    ({"a": 1, "b": [2, 3]}, "a26161016162820203"),
])
def test_cbor_vectors(obj: Any, hexs: str) -> None:
    assert cbor.dumps(obj).hex() == hexs
    assert cbor.loads(bytes.fromhex(hexs)) == obj


def test_cbor_roundtrip_nested() -> None:
    obj = {"images": [{"slot": 0, "hash": bytes(32), "ok": True, "x": None}],
           "n": -123456789, 7: "seven", "big": b"\xff" * 300}
    assert cbor.loads(cbor.dumps(obj)) == obj


def test_cbor_float_decode() -> None:
    assert cbor.loads(bytes.fromhex("f93c00")) == 1.0
    assert cbor.loads(bytes.fromhex("f9c400")) == -4.0
    assert cbor.loads(bytes.fromhex("fa47c35000")) == 100000.0
    assert cbor.loads(bytes.fromhex("fb3ff199999999999a")) == 1.1
    assert math.isinf(cbor.loads(bytes.fromhex("f97c00")))
    assert cbor.loads(cbor.dumps(1.5)) == 1.5


def test_cbor_indefinite() -> None:
    assert cbor.loads(bytes.fromhex("9f018202039f0405ffff")) == [1, [2, 3], [4, 5]]
    assert cbor.loads(bytes.fromhex("bf61610161629f0203ffff")) == {"a": 1, "b": [2, 3]}
    assert cbor.loads(bytes.fromhex("7f657374726561646d696e67ff")) == "streaming"
    assert cbor.loads(bytes.fromhex("5f42010243030405ff")) == b"\x01\x02\x03\x04\x05"


@pytest.mark.parametrize("bad", [
    "", "18", "1900", "5f", "ff", "62c328", "8301", "a1", "9f01", "1c",
    "a1ff01", "8201ff", "0000",  # truncated / break misuse / trailing
    "f8ff", "a1810101",
])
def test_cbor_garbage(bad: str) -> None:
    with pytest.raises(CborError):
        cbor.loads(bytes.fromhex(bad))


def test_cbor_encode_errors() -> None:
    with pytest.raises(CborError):
        cbor.dumps(object())
    with pytest.raises(CborError):
        cbor.dumps(1 << 64)
    assert issubclass(CborError, ValueError)


# ------------------------------------------------------------- framing


def test_crc_check_value() -> None:
    assert crc16_ccitt(b"123456789") == 0x31C3


@pytest.mark.parametrize("size", [0, 1, 10, 70, 91, 93, 94, 200, 1000])
def test_frame_roundtrip(size: int) -> None:
    pkt = bytes((i * 7) & 0xFF for i in range(size))
    wire = encode_frames(pkt)
    lines = wire.split(b"\n")[:-1]
    assert all(len(ln) + 1 <= 127 for ln in lines)
    assert lines[0].startswith(b"\x06\x09")
    assert all(ln.startswith(b"\x04\x14") for ln in lines[1:])
    assert wire.endswith(b"\n")
    if size > 100:
        assert len(lines) > 1
    assert FrameDecoder().feed(wire) == [pkt]


def test_frame_decoder_ignores_console_text() -> None:
    pkt1, pkt2 = b"hello" * 40, b"world"
    wire = (b"boot: Zephyr 3.6\r\n[00:00:01] <inf> app: x\r\n"
            + encode_frames(pkt1)
            + b"no newline log" + encode_frames(pkt2)
            + b"uart:~$ ")
    dec = FrameDecoder()
    assert dec.feed(wire) == [pkt1, pkt2]
    assert dec.errors == 0


def test_frame_decoder_byte_by_byte() -> None:
    pkts = [b"abc", bytes(range(256)), b"z"]
    wire = b"junk\r\n" + b"".join(encode_frames(p) for p in pkts)
    dec = FrameDecoder()
    got: list[bytes] = []
    for i in range(len(wire)):
        got += dec.feed(wire[i:i + 1])
    assert got == pkts


def test_frame_decoder_bad_crc_skipped_then_recovers() -> None:
    good = b"good packet"
    bad = bytearray(encode_frames(b"bad packet"))
    # corrupt a base64 char in the body (keep it valid base64)
    bad[4] = ord("A") if bad[4] != ord("A") else ord("B")
    dec = FrameDecoder()
    assert dec.feed(bytes(bad) + encode_frames(good)) == [good]
    assert dec.errors == 1


def test_frame_decoder_bad_base64_and_orphan_continuation() -> None:
    dec = FrameDecoder()
    assert dec.feed(b"\x04\x14AAAA\n") == []  # orphan continuation
    assert dec.feed(b"\x06\x09!!!!\n") == []
    assert dec.errors == 1
    assert dec.feed(encode_frames(b"ok")) == [b"ok"]


def test_frame_decoder_drops_endless_junk() -> None:
    dec = FrameDecoder()
    dec.feed(b"x" * 5000)
    assert dec.feed(encode_frames(b"ok")) == [b"ok"]


# --------------------------------------------------------- fake device


class FakeDevice:
    def __init__(self) -> None:
        self.stored = bytearray()
        self.image_len = 0
        self.sha = b""
        self.pre_off = 0          # simulated already-received prefix
        self.erased: list[int] = []
        self.reset_called = False
        self.v2_error: tuple[int, int] | None = None
        self.v1_rc: int | None = None
        self.images: list[dict[str, Any]] = [{
            "image": 0, "slot": 0, "version": "1.0.0", "hash": b"\x11" * 32,
            "bootable": True, "pending": False, "confirmed": True,
            "active": True, "permanent": False,
        }]

    def handle(self, op: int, group: int, cmd_id: int, req: dict[Any, Any]) -> dict[Any, Any]:
        if self.v1_rc is not None:
            return {"rc": self.v1_rc}
        if self.v2_error is not None:
            return {"err": {"group": self.v2_error[0], "rc": self.v2_error[1]}}
        if group == GROUP_OS and cmd_id == OS_ECHO:
            return {"r": req["d"]}
        if group == GROUP_OS and cmd_id == OS_RESET:
            self.reset_called = True
            return {"rc": 0}
        if group == GROUP_IMAGE and cmd_id == IMG_STATE:
            if op == OP_WRITE:
                if req.get("confirm") and "hash" not in req:
                    for im in self.images:
                        if im["slot"] == 0 or im["pending"]:
                            im["confirmed"] = True
                else:
                    for im in self.images:
                        if im["hash"] == req["hash"]:
                            if req["confirm"]:
                                im["confirmed"] = True
                            else:
                                im["pending"] = True
            return {"images": [dict(i) for i in self.images], "splitStatus": 0}
        if group == GROUP_IMAGE and cmd_id == IMG_ERASE:
            self.erased.append(req.get("slot", 1))
            return {"rc": 0}
        if group == GROUP_IMAGE and cmd_id == IMG_UPLOAD:
            off = req["off"]
            if off == 0 and "len" in req:
                self.image_len = req["len"]
                self.sha = req["sha"]
                if self.pre_off:
                    # device already holds a prefix: ask to resume there
                    self.stored = bytearray(b"\xaa" * self.pre_off)
                    return {"rc": 0, "off": self.pre_off}
                self.stored = bytearray()
            if off != len(self.stored):
                return {"rc": 0, "off": len(self.stored)}
            self.stored += req["data"]
            return {"rc": 0, "off": len(self.stored)}
        return {"rc": 8}


class FakeTransport(Transport):
    key = "fake"
    label = "Fake"

    def __init__(self, device: FakeDevice | None = None, mtu: int = 256) -> None:
        self.device = device or FakeDevice()
        self.mtu = mtu
        self.sent: list[bytes] = []
        self.rx: list[bytes] = []
        self.pre_rx: list[bytes] = []     # stale packets delivered before replies
        self.drop_next = 0                # swallow N replies (timeouts)
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def send(self, packet: bytes) -> None:
        self.sent.append(packet)
        op, group, seq, cmd_id, body = decode_packet(packet)
        req = cbor.loads(body)
        rsp = self.device.handle(op, group, cmd_id, req)
        if self.drop_next > 0:
            self.drop_next -= 1
            return
        self.rx += self.pre_rx
        self.pre_rx = []
        self.rx.append(encode_packet(op + 1, group, cmd_id, seq, rsp))

    def recv(self, timeout: float) -> bytes:
        if not self.rx:
            raise TimeoutError
        return self.rx.pop(0)


def make(mtu: int = 256, **kw: Any) -> tuple[SmpClient, FakeTransport, FakeDevice]:
    tr = FakeTransport(mtu=mtu, **kw)
    return SmpClient(tr, timeout=0.2), tr, tr.device


# -------------------------------------------------------------- client


def test_header_layout() -> None:
    pkt = encode_packet(OP_WRITE, GROUP_IMAGE, 1, 7, {})
    assert pkt[:8] == bytes([0x0A, 0, 0, 1, 0, 1, 7, 1])
    assert pkt[8:] == b"\xa0"
    assert decode_packet(pkt) == (OP_WRITE, GROUP_IMAGE, 7, 1, b"\xa0")
    assert OP_READ_RSP == 1 and OP_WRITE_RSP == 3 and OP_READ == 0


def test_echo_and_seq_increments() -> None:
    c, tr, _ = make()
    assert c.echo("hi") == "hi"
    assert c.echo("yo") == "yo"
    assert [decode_packet(p)[2] for p in tr.sent] == [1, 2]


def test_image_state_and_test_confirm() -> None:
    c, _, dev = make()
    dev.images.append({
        "image": 0, "slot": 1, "version": "2.0.0", "hash": b"\x22" * 32,
        "bootable": True, "pending": False, "confirmed": False,
        "active": False, "permanent": False,
    })
    st = c.image_state()
    assert st[0] == SlotState(0, 0, "1.0.0", b"\x11" * 32, True, False, True, True, False)
    assert len(st) == 2 and not st[1].pending
    st = c.test(b"\x22" * 32)
    assert st[1].pending and not st[1].confirmed
    st = c.confirm(b"\x22" * 32)
    assert st[1].confirmed
    c.confirm()


def test_reset_and_erase() -> None:
    c, _, dev = make()
    c.reset()
    assert dev.reset_called
    c.erase()
    c.erase(2)
    assert dev.erased == [1, 2]


@pytest.mark.parametrize("mtu", [96, 128, 256, 512, 2048])
def test_upload_exact_and_respects_mtu(mtu: int) -> None:
    c, tr, dev = make(mtu=mtu)
    data = bytes((i * 31) & 0xFF for i in range(10_000))
    c.upload(data)
    assert bytes(dev.stored) == data
    assert dev.sha == hashlib.sha256(data).digest()
    assert dev.image_len == len(data)
    assert all(len(p) <= mtu for p in tr.sent)
    # chunks are as large as they can be: all but the last are within a few
    # bytes of the MTU (CBOR header width rounding only)
    assert all(mtu - len(p) <= 4 for p in tr.sent[:-1])
    first = cbor.loads(decode_packet(tr.sent[0])[4])
    assert first["off"] == 0 and first["len"] == len(data) and first["image"] == 0
    later = cbor.loads(decode_packet(tr.sent[1])[4])
    assert set(later) == {"off", "data"}


def test_upload_mtu_boundary_sizes() -> None:
    # sizes where the bstr header width changes (23/24, 255/256)
    for mtu in range(96, 400, 7):
        c, tr, dev = make(mtu=mtu)
        data = bytes(range(256)) * 3
        c.upload(data)
        assert bytes(dev.stored) == data
        assert max(len(p) for p in tr.sent) <= mtu


def test_upload_mtu_too_small() -> None:
    c, _, _ = make(mtu=20)
    with pytest.raises(ValueError):
        c.upload(b"abc")


def test_upload_progress() -> None:
    c, _, _ = make(mtu=128)
    data = b"\x55" * 1000
    calls: list[tuple[int, int]] = []
    c.upload(data, progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (1000, 1000)
    assert all(t == 1000 for _, t in calls)
    assert [d for d, _ in calls] == sorted(d for d, _ in calls)
    assert len(calls) > 5


def test_upload_cancel() -> None:
    c, tr, dev = make(mtu=128)
    ev = threading.Event()

    def prog(done: int, total: int) -> None:
        if done > 300:
            ev.set()

    with pytest.raises(SmpCancelled):
        c.upload(b"\x01" * 5000, progress=prog, cancel=ev)
    assert 300 < len(dev.stored) < 5000
    n = len(tr.sent)
    ev2 = threading.Event()
    ev2.set()
    with pytest.raises(SmpCancelled):
        c.upload(b"\x01" * 100, cancel=ev2)
    assert len(tr.sent) == n


def test_upload_resume_from_device_offset() -> None:
    dev = FakeDevice()
    dev.pre_off = 600
    c, tr, _ = make(device=dev, mtu=128)
    data = bytes((i * 3) & 0xFF for i in range(2000))
    calls: list[int] = []
    c.upload(data, progress=lambda d, t: calls.append(d))
    assert calls[0] == 600
    assert bytes(dev.stored[600:]) == data[600:]
    sent_data = sum(len(cbor.loads(decode_packet(p)[4])["data"]) for p in tr.sent)
    assert sent_data < len(data) + 128  # the first 600 bytes were not resent


def test_upload_retries_after_timeout() -> None:
    c, tr, dev = make(mtu=128)
    tr.drop_next = 3
    data = b"\x07" * 300
    c.upload(data)
    assert bytes(dev.stored[:0]) == b""  # device handled duplicates via offset
    assert len(dev.stored) == 300


def test_upload_gives_up_after_retries() -> None:
    c, tr, _ = make(mtu=128)
    tr.drop_next = 100
    with pytest.raises(TimeoutError):
        c.upload(b"\x07" * 300)
    assert len(tr.sent) == 4  # 1 try + 3 retries


def test_upload_empty_rejected() -> None:
    c, _, _ = make()
    with pytest.raises(ValueError):
        c.upload(b"")


def test_error_v1_rc() -> None:
    c, _, dev = make()
    dev.v1_rc = 6
    with pytest.raises(SmpError) as ei:
        c.image_state()
    assert ei.value.rc == 6 and ei.value.group is None
    assert ei.value.message == "EBADSTATE"


def test_error_v2_err() -> None:
    c, _, dev = make()
    dev.v2_error = (1, 3)
    with pytest.raises(SmpError) as ei:
        c.reset()
    assert ei.value.rc == 3 and ei.value.group == 1
    assert "EINVAL" in ei.value.message


def test_error_unknown_rc_name() -> None:
    assert "99" in SmpError(99).message


def test_upload_error_propagates() -> None:
    c, _, dev = make()
    dev.v1_rc = 2
    with pytest.raises(SmpError) as ei:
        c.upload(b"abc")
    assert ei.value.rc == 2


def test_stale_and_mismatched_packets_skipped() -> None:
    c, tr, _ = make()
    stale = [
        encode_packet(OP_WRITE_RSP, GROUP_OS, OS_ECHO, 99, {"r": "stale-seq"}),
        encode_packet(OP_WRITE_RSP, GROUP_IMAGE, IMG_STATE, 1, {"r": "wrong-group"}),
        encode_packet(OP_WRITE_RSP, GROUP_OS, OS_RESET, 1, {"r": "wrong-id"}),
        encode_packet(OP_WRITE, GROUP_OS, OS_ECHO, 1, {"r": "not-a-response"}),
        b"\x00\x01",  # short garbage
        encode_packet(OP_WRITE_RSP, GROUP_OS, OS_ECHO, 1, {"r": "x"})[:10],  # truncated cbor
    ]
    tr.pre_rx = stale
    assert c.echo("real") == "real"


def test_stale_error_response_does_not_raise() -> None:
    c, tr, _ = make()
    tr.pre_rx = [encode_packet(OP_WRITE_RSP, GROUP_OS, OS_ECHO, 42, {"rc": 5})]
    assert c.echo("ok") == "ok"


def test_timeout_when_only_stale() -> None:
    c, tr, _ = make()
    tr.drop_next = 1
    with pytest.raises(TimeoutError):
        c.echo("x")


# ------------------------------------------------------------ registry


def test_registry() -> None:
    assert next(iter(TRANSPORTS)) == "usb" == DEFAULT_TRANSPORT
    assert TRANSPORTS["usb"].available is True
    assert TRANSPORTS["usb"].factory is SerialTransport
    assert TRANSPORTS["usb"].label == "USB CDC (serial)"


def test_ble_stub() -> None:
    info = TRANSPORTS["ble"]
    assert info.available is False
    assert info.label == "Bluetooth LE"
    t = info.factory("AA:BB:CC:DD:EE:FF")  # type: ignore[call-arg]
    assert not t.is_open
    with pytest.raises(NotImplementedError, match="not implemented yet"):
        t.open()


# ----------------------------------------- serial framing over a fake stream


class _FakeSerialPort:
    """Duck-typed QSerialPort: loops requests through a FakeDevice."""

    def __init__(self, device: FakeDevice) -> None:
        self.device = device
        self.dec = FrameDecoder()
        self.rx = bytearray()
        self.open_ = True

    def close(self) -> None:
        self.open_ = False

    def isOpen(self) -> bool:  # noqa: N802
        return self.open_

    def write(self, data: bytes) -> int:
        for pkt in self.dec.feed(data):
            op, group, seq, cmd_id, body = decode_packet(pkt)
            rsp = self.device.handle(op, group, cmd_id, cbor.loads(body))
            self.rx += b"log line\r\n"
            self.rx += encode_frames(encode_packet(op + 1, group, cmd_id, seq, rsp))
        return len(data)

    def waitForBytesWritten(self, ms: int) -> bool:  # noqa: N802
        return True

    def bytesAvailable(self) -> int:  # noqa: N802
        return len(self.rx)

    def waitForReadyRead(self, ms: int) -> bool:  # noqa: N802
        return bool(self.rx)

    def readAll(self) -> Any:  # noqa: N802
        data, self.rx = bytes(self.rx[:7]), self.rx[7:]  # small reads
        return type("B", (), {"data": lambda s: data})()


def test_serial_transport_end_to_end_fake_stream() -> None:
    dev = FakeDevice()
    t = SerialTransport("FAKE", mtu=200)
    t._sp = _FakeSerialPort(dev)
    c = SmpClient(t, timeout=0.5)
    assert c.echo("serial") == "serial"
    data = bytes(range(256)) * 8
    c.upload(data)
    assert bytes(dev.stored) == data
    with pytest.raises(TimeoutError):
        t.recv(0.05)
    t.close()
    assert not t.is_open
