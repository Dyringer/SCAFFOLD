"""Medium-independent SMP (mcumgr) client.

Blocking: call from a worker thread, never the GUI thread. The transport moves
whole SMP packets; this module only builds/parses SMP packets.
"""
from __future__ import annotations

import hashlib
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.subapps.mcuboot import cbor
from app.subapps.mcuboot.transport.base import Transport

OP_READ, OP_READ_RSP, OP_WRITE, OP_WRITE_RSP = 0, 1, 2, 3
GROUP_OS, GROUP_IMAGE = 0, 1
OS_ECHO, OS_RESET = 0, 5
IMG_STATE, IMG_UPLOAD, IMG_ERASE = 0, 1, 5

SMP_VERSION = 1
HEADER_LEN = 8
_HEADER = struct.Struct(">BBHHBB")  # op, flags, len, group, seq, id

UPLOAD_RETRIES = 3

MGMT_ERRORS: dict[int, str] = {
    0: "OK",
    1: "EUNKNOWN",
    2: "ENOMEM",
    3: "EINVAL",
    4: "ETIMEOUT",
    5: "ENOENT",
    6: "EBADSTATE",
    7: "EMSGSIZE",
    8: "ENOTSUP",
    9: "ECORRUPT",
    10: "EBUSY",
}


class SmpError(Exception):
    """Device returned a non-zero SMP error code."""

    def __init__(self, rc: int, group: int | None = None, message: str = "") -> None:
        self.rc = rc
        self.group = group
        name = MGMT_ERRORS.get(rc, f"rc={rc}")
        self.message = message or name
        super().__init__(f"SMP error {rc} ({name})" + (
            f" in group {group}" if group is not None else ""))


class SmpCancelled(Exception):  # noqa: N818
    """Operation cancelled via the cancel event."""


@dataclass(frozen=True)
class SlotState:
    image: int
    slot: int
    version: str
    hash: bytes
    bootable: bool
    pending: bool
    confirmed: bool
    active: bool
    permanent: bool


def encode_packet(op: int, group: int, cmd_id: int, seq: int, payload: Any) -> bytes:
    body = cbor.dumps(payload)
    return _HEADER.pack(op | (SMP_VERSION << 3), 0, len(body), group, seq, cmd_id) + body


def decode_packet(packet: bytes) -> tuple[int, int, int, int, bytes]:
    """Return (op, group, seq, id, payload_bytes). Raises ValueError if short."""
    if len(packet) < HEADER_LEN:
        raise ValueError("short SMP packet")
    op, _flags, length, group, seq, cmd_id = _HEADER.unpack_from(packet)
    return op & 0x07, group, seq, cmd_id, packet[HEADER_LEN:HEADER_LEN + length]


def _cbor_hdr_len(n: int) -> int:
    return 1 if n < 24 else 2 if n < 0x100 else 3 if n < 0x10000 else 5


def _check_error(rsp: dict[Any, Any]) -> None:
    err = rsp.get("err")
    if isinstance(err, dict):
        rc = int(err.get("rc", 1))
        if rc != 0:
            raise SmpError(rc, err.get("group"))
    rc = rsp.get("rc")
    if isinstance(rc, int) and not isinstance(rc, bool) and rc != 0:
        raise SmpError(rc)


class SmpClient:
    def __init__(self, transport: Transport, timeout: float = 5.0) -> None:
        self.transport = transport
        self.timeout = timeout
        self._seq = 0

    # -- core ------------------------------------------------------------

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    def _send_request(self, op: int, group: int, cmd_id: int, seq: int,
                      payload: Any) -> None:
        self.transport.send(encode_packet(op, group, cmd_id, seq, payload))

    def _await_response(self, op: int, group: int, cmd_id: int, seq: int) -> dict[Any, Any]:
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no SMP response")
            pkt = self.transport.recv(remaining)
            try:
                rop, rgroup, rseq, rid, body = decode_packet(pkt)
            except ValueError:
                continue
            if rop != op + 1 or rseq != seq or rgroup != group or rid != cmd_id:
                continue  # stale / unrelated
            try:
                rsp = cbor.loads(body) if body else {}
            except cbor.CborError:
                continue
            if not isinstance(rsp, dict):
                continue
            _check_error(rsp)
            return rsp

    def request(self, op: int, group: int, cmd_id: int,
                payload: Any | None = None) -> dict[Any, Any]:
        """Send a request and return the decoded response map.

        Raises TimeoutError, SmpError."""
        seq = self._next_seq()
        self._send_request(op, group, cmd_id, seq, {} if payload is None else payload)
        return self._await_response(op, group, cmd_id, seq)

    # -- commands --------------------------------------------------------

    def echo(self, text: str) -> str:
        rsp = self.request(OP_WRITE, GROUP_OS, OS_ECHO, {"d": text})
        return str(rsp.get("r", ""))

    def image_state(self) -> list[SlotState]:
        return self._states(self.request(OP_READ, GROUP_IMAGE, IMG_STATE))

    def test(self, hash: bytes) -> list[SlotState]:
        return self._states(self.request(
            OP_WRITE, GROUP_IMAGE, IMG_STATE, {"hash": bytes(hash), "confirm": False}))

    def confirm(self, hash: bytes | None = None) -> list[SlotState]:
        payload: dict[str, Any] = {"confirm": True}
        if hash is not None:
            payload["hash"] = bytes(hash)
        return self._states(self.request(OP_WRITE, GROUP_IMAGE, IMG_STATE, payload))

    def erase(self, slot: int = 1) -> None:
        self.request(OP_WRITE, GROUP_IMAGE, IMG_ERASE, {"slot": slot})

    def reset(self) -> None:
        self.request(OP_WRITE, GROUP_OS, OS_RESET, {})

    @staticmethod
    def _states(rsp: dict[Any, Any]) -> list[SlotState]:
        out: list[SlotState] = []
        for im in rsp.get("images") or []:
            if not isinstance(im, dict):
                continue
            out.append(SlotState(
                image=int(im.get("image", 0)),
                slot=int(im.get("slot", 0)),
                version=str(im.get("version", "")),
                hash=bytes(im.get("hash", b"")),
                bootable=bool(im.get("bootable", False)),
                pending=bool(im.get("pending", False)),
                confirmed=bool(im.get("confirmed", False)),
                active=bool(im.get("active", False)),
                permanent=bool(im.get("permanent", False)),
            ))
        return out

    # -- upload ----------------------------------------------------------

    def _chunk_size(self, fields: dict[str, Any], remaining: int) -> int:
        """Largest data length so the whole packet is <= transport.mtu.

        base = header + CBOR map with an empty ``data`` bstr, minus that
        bstr's 1-byte header; the real data adds its own header + n bytes."""
        mtu = self.transport.mtu
        base = HEADER_LEN + len(cbor.dumps({**fields, "data": b""})) - 1
        n = min(remaining, mtu - base - 1)
        while n > 0 and base + _cbor_hdr_len(n) + n > mtu:
            n -= 1
        if n <= 0:
            raise ValueError(f"transport MTU {mtu} too small for SMP upload")
        return n

    def upload(self, data: bytes, progress: Callable[[int, int], None] | None = None,
               cancel: threading.Event | None = None, image: int = 0) -> None:
        data = bytes(data)
        total = len(data)
        if total == 0:
            raise ValueError("nothing to upload")
        sha = hashlib.sha256(data).digest()
        off = 0
        first = True
        stalls = 0
        while off < total:
            if cancel is not None and cancel.is_set():
                raise SmpCancelled("upload cancelled")
            fields: dict[str, Any] = (
                {"image": image, "off": 0, "len": total, "sha": sha} if first
                else {"off": off}
            )
            n = self._chunk_size(fields, total - off)
            payload = {**fields, "data": data[off:off + n]}
            rsp = self._upload_chunk(payload)
            new_off = rsp.get("off")
            if not isinstance(new_off, int) or isinstance(new_off, bool):
                raise SmpError(1, None, "upload response missing 'off'")
            if new_off > total or new_off < 0:
                raise SmpError(3, None, f"device returned invalid offset {new_off}")
            stalls = stalls + 1 if new_off == off else 0
            if stalls > UPLOAD_RETRIES:
                raise SmpError(1, None, "device made no upload progress")
            off = new_off
            first = False
            if progress is not None:
                progress(off, total)

    def _upload_chunk(self, payload: dict[str, Any]) -> dict[Any, Any]:
        last: TimeoutError | None = None
        for _ in range(UPLOAD_RETRIES + 1):
            try:
                return self.request(OP_WRITE, GROUP_IMAGE, IMG_UPLOAD, payload)
            except TimeoutError as e:
                last = e
        assert last is not None
        raise last
