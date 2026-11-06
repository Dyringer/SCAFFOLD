"""ESP OTA: protocol client + runner against an in-process fake http_panel."""
from __future__ import annotations

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.subapps.esp_ota import runner as runner_mod
from app.subapps.esp_ota.client import Cancelled, OtaUpload, parse_target, probe, send_reboot
from app.subapps.esp_ota.runner import OtaRunner
from app.subapps.esp_ota.ui import firmware_warning


class FakeDevice:
    """Implements the three endpoints the firmware's http_panel exposes."""

    def __init__(self) -> None:
        self.received = b""
        self.reboot_frames: list[bytes] = []
        self.upload_status = 200
        self.upload_body = b"OK"
        self.read_delay = 0.0          # per 4 KiB read, to make uploads slow
        dev = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_a) -> None:
                pass

            def do_GET(self) -> None:
                if self.path == "/ota/ws":
                    self.wfile.write(
                        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                        b"Connection: Upgrade\r\nSec-WebSocket-Accept: x\r\n\r\n")
                    self.wfile.flush()
                    head = self.rfile.read(2)
                    n = head[1] & 0x7F
                    mask = self.rfile.read(4)
                    data = self.rfile.read(n)
                    dev.reboot_frames.append(bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
                    self.close_connection = True
                    return
                body = b"<html>panel</html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                assert self.path == "/ota/upload"
                assert self.headers["Content-Type"] == "application/octet-stream"
                remaining = int(self.headers["Content-Length"])
                buf = bytearray()
                try:
                    while remaining:
                        chunk = self.rfile.read(min(4096, remaining))
                        if not chunk:
                            return
                        buf += chunk
                        remaining -= len(chunk)
                        if dev.read_delay:
                            time.sleep(dev.read_delay)
                except OSError:
                    return
                dev.received = bytes(buf)
                self.send_response(dev.upload_status)
                self.send_header("Content-Length", str(len(dev.upload_body)))
                self.end_headers()
                self.wfile.write(dev.upload_body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def device():
    dev = FakeDevice()
    yield dev
    dev.close()


@pytest.fixture
def firmware(tmp_path):
    f = tmp_path / "app.bin"
    f.write_bytes(b"\xe9" + bytes(range(256)) * 400)   # ~100 KiB app image
    return f


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# client


@pytest.mark.parametrize("text, expected", [
    ("192.168.1.42", ("192.168.1.42", 80)),
    ("cam.local:8080", ("cam.local", 8080)),
    ("http://10.0.0.5/", ("10.0.0.5", 80)),
    ("  10.0.0.5:81  ", ("10.0.0.5", 81)),
    ("", None),
    ("10.0.0.5:abc", None),
    ("10.0.0.5:70000", None),
    ("two words", None),
])
def test_parse_target(text, expected):
    assert parse_target(text) == expected


def test_upload_streams_raw_body(device, firmware):
    progress: list[tuple[int, int]] = []
    sent_called: list[bool] = []
    result = OtaUpload("127.0.0.1", device.port, str(firmware)).run(
        lambda s, t: progress.append((s, t)), lambda: sent_called.append(True))
    assert result.ok and result.status == 200 and result.body == "OK"
    assert device.received == firmware.read_bytes()
    assert progress[-1] == (firmware.stat().st_size, firmware.stat().st_size)
    assert sent_called == [True]


def test_upload_rejected(device, firmware):
    device.upload_status = 400
    device.upload_body = b"image validation failed"
    result = OtaUpload("127.0.0.1", device.port, str(firmware)).run()
    assert not result.ok
    assert result.status == 400
    assert result.body == "image validation failed"


def test_upload_cancel_from_other_thread(device, tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"\xe9" * (3 * 1024 * 1024))
    device.read_delay = 0.01
    up = OtaUpload("127.0.0.1", device.port, str(big))
    threading.Timer(0.3, up.cancel).start()
    with pytest.raises(Cancelled):
        up.run()


def test_send_reboot_frame(device):
    send_reboot("127.0.0.1", device.port)
    deadline = time.time() + 2
    while not device.reboot_frames and time.time() < deadline:
        time.sleep(0.01)
    assert device.reboot_frames == [b'{"action":"reboot"}']


def test_probe(device):
    assert probe("127.0.0.1", device.port) is True
    assert probe("127.0.0.1", _free_port(), timeout=0.5) is False


def test_firmware_warning(tmp_path):
    app = tmp_path / "app.bin"
    app.write_bytes(b"\xe9" + b"\0" * 0x20000)
    merged = bytearray(b"\xff" * 0x20000)
    merged[0] = 0xE9
    merged[0x8000:0x8002] = b"\xaa\x50"
    merged_f = tmp_path / "merged.bin"
    merged_f.write_bytes(bytes(merged))
    junk = tmp_path / "zephyr_signed.bin"
    junk.write_bytes(b"\x3d\xb8\xf3\x96" + b"\0" * 0x20000)   # MCUboot magic
    assert firmware_warning(app) == ""
    assert "merged" in firmware_warning(merged_f)
    assert "0xE9" in firmware_warning(junk)


# ---------------------------------------------------------------------------
# runner (Qt)


def test_runner_full_flow(qtbot, device, firmware, monkeypatch):
    monkeypatch.setattr(runner_mod, "POLL_DELAY_S", 0.05)
    r = OtaRunner()
    stages: list[str] = []
    r.stage.connect(lambda key, _t: stages.append(key))
    with qtbot.waitSignal(r.finished, timeout=10000) as blocker:
        r.start("127.0.0.1", device.port, str(firmware), reboot=True, wait_online=True)
    assert blocker.args == [True, "Updated — device is back online"]
    assert device.received == firmware.read_bytes()
    assert device.reboot_frames == [b'{"action":"reboot"}']
    assert stages[:3] == ["upload", "validate", "reboot"] and stages[-1] == "wait"


def test_runner_no_reboot(qtbot, device, firmware):
    r = OtaRunner()
    with qtbot.waitSignal(r.finished, timeout=10000) as blocker:
        r.start("127.0.0.1", device.port, str(firmware), reboot=False)
    assert blocker.args[0] is True
    assert "staged" in blocker.args[1]
    assert device.reboot_frames == []


def test_runner_connection_refused(qtbot, firmware):
    r = OtaRunner()
    with qtbot.waitSignal(r.finished, timeout=10000) as blocker:
        r.start("127.0.0.1", _free_port(), str(firmware))
    ok, summary = blocker.args
    assert ok is False
    assert summary   # human-readable reason, not empty


def test_runner_cancel(qtbot, device, tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"\xe9" * (3 * 1024 * 1024))
    device.read_delay = 0.01
    r = OtaRunner()
    with qtbot.waitSignal(r.progress, timeout=10000):
        r.start("127.0.0.1", device.port, str(big))
    with qtbot.waitSignal(r.finished, timeout=10000) as blocker:
        r.cancel()
    assert blocker.args == [False, "Cancelled"]


# ---------------------------------------------------------------------------
# panel smoke


def test_panel_add_device_and_ready(qtbot, device, firmware):
    from app.core.settings_store import settings_store
    from app.subapps.esp_ota.ui import EspOtaPanel

    panel = EspOtaPanel()
    qtbot.addWidget(panel)
    assert not panel._hero.start_btn.isEnabled()          # no device, no firmware
    panel._addr_edit.setText(f"127.0.0.1:{device.port}")
    panel._name_edit.setText("CAM")
    panel._add_device()
    assert settings_store.get("esp_ota.devices") == [
        {"name": "CAM", "host": "127.0.0.1", "port": device.port}]
    panel._fw_row.set_path(str(firmware))
    assert panel._hero.start_btn.isEnabled()
    # The background prober marks the fake device online.
    qtbot.waitUntil(lambda: panel._online.get(f"127.0.0.1:{device.port}") is True,
                    timeout=5000)
    panel.shutdown()
