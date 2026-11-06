"""HTTP OTA protocol for the ESP32-S3 http_panel — GUI-friendly version.

Wire contract (also used by the ota_push.py CLI kept alongside):
  * POST /ota/upload   raw image body, Content-Type application/octet-stream,
                       one Content-Length header, no multipart. The response
                       arrives after the device has run ota_finish() image
                       validation; HTTP 200 = image accepted.
  * GET  /ota/ws       WebSocket; one text frame {"action":"reboot"} reboots.
  * GET  /             200 when the http_panel is up (used as a liveness probe).

Progress goes to a callback, and an upload can be cancelled from another
thread. Stdlib only, no Qt — the Qt side lives in runner.py.
"""
from __future__ import annotations

import base64
import contextlib
import http.client
import os
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_PORT = 80
UPLOAD_PATH = "/ota/upload"
WS_PATH = "/ota/ws"
UPLOAD_TIMEOUT_S = 60
CHUNK_SIZE = 4096
PROBE_TIMEOUT_S = 2.0
# Liveness polling after a reboot (~15 s).
POLL_ATTEMPTS = 10
POLL_DELAY_S = 1.5


class Cancelled(Exception):  # noqa: N818 (a control-flow signal, not an error)
    """The operation was cancelled by the user."""


@dataclass(frozen=True)
class UploadResult:
    ok: bool
    status: int
    body: str
    sent_s: float     # time to hand all bytes to the OS socket buffer
    total_s: float    # ...plus drain to the device and its image validation


def parse_target(text: str) -> tuple[str, int] | None:
    """'192.168.1.42', 'cam.local:8080', 'http://10.0.0.5/' -> (host, port)."""
    t = text.strip()
    for prefix in ("http://", "https://"):
        if t.lower().startswith(prefix):
            t = t[len(prefix):]
    t = t.split("/", 1)[0].strip()
    if not t or " " in t:
        return None
    host, sep, port_s = t.rpartition(":")
    if not sep:
        return t, DEFAULT_PORT
    if not host or not port_s.isdigit() or not 0 < int(port_s) < 65536:
        return None
    return host, int(port_s)


class OtaUpload:
    """One streaming upload. run() blocks (call it from a worker thread);
    cancel() may be called from any thread and makes run() raise Cancelled."""

    def __init__(self, host: str, port: int, path: str, *,
                 timeout: float = UPLOAD_TIMEOUT_S, chunk_size: int = CHUNK_SIZE) -> None:
        self._host = host
        self._port = port
        self._path = path
        self._timeout = timeout
        self._chunk = chunk_size
        self._conn: http.client.HTTPConnection | None = None
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()
        # Closing the socket unblocks a send()/recv() stuck in the worker.
        conn = self._conn
        sock = conn.sock if conn is not None else None
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                sock.close()

    def run(self, on_progress: Callable[[int, int], None] | None = None,
            on_sent: Callable[[], None] | None = None) -> UploadResult:
        """Stream the file. `on_progress(sent, total)` fires per chunk;
        `on_sent()` once every byte is handed off (device now validating)."""
        size = os.path.getsize(self._path)
        conn = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)
        self._conn = conn
        t_start = time.monotonic()
        try:
            self._check_cancel()
            conn.putrequest("POST", UPLOAD_PATH)
            conn.putheader("Content-Type", "application/octet-stream")
            conn.putheader("Content-Length", str(size))
            conn.endheaders()

            sent = 0
            with open(self._path, "rb") as f:
                while chunk := f.read(self._chunk):
                    self._check_cancel()
                    conn.send(chunk)
                    sent += len(chunk)
                    if on_progress is not None:
                        on_progress(sent, size)
            t_sent = time.monotonic() - t_start
            if on_sent is not None:
                on_sent()

            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace").strip()
            return UploadResult(resp.status == 200, resp.status, body,
                                t_sent, time.monotonic() - t_start)
        except OSError:
            # A user cancel closes the socket under us — report that, not the
            # resulting socket error.
            self._check_cancel()
            raise
        finally:
            conn.close()
            self._conn = None

    def _check_cancel(self) -> None:
        if self._cancelled.is_set():
            raise Cancelled()


def send_reboot(host: str, port: int, timeout: float = 5.0) -> None:
    """Minimal RFC 6455 client: upgrade on /ota/ws, send one masked text
    frame {"action":"reboot"}, close. Raises OSError/RuntimeError on failure —
    though a dropped connection is the *expected* outcome of a reboot."""
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    try:
        request = (
            f"GET {WS_PATH} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = sock.recv(4096)
        if b"101" not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WebSocket handshake failed: {response[:120]!r}")
        payload = b'{"action":"reboot"}'
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        # FIN=1, opcode=1 (text); MASK=1, len < 126.
        sock.sendall(bytes([0x81, 0x80 | len(payload)]) + mask + masked)
    finally:
        sock.close()


def probe(host: str, port: int, timeout: float = PROBE_TIMEOUT_S) -> bool:
    """True if the device's http_panel answers GET / with 200."""
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("GET", "/")
            resp = conn.getresponse()
            resp.read()
            return resp.status == 200
        finally:
            conn.close()
    except OSError:
        return False
