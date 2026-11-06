"""Qt glue: run an OTA job / device probes on worker threads, report via signals.

The protocol calls in client.py block (sockets), so each job runs on a plain
daemon thread. Signals emitted from that thread are delivered to the GUI
thread as queued connections automatically (the runner lives on the GUI
thread), so slots never touch widgets off-thread.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from app.subapps.esp_ota.client import (
    POLL_ATTEMPTS,
    POLL_DELAY_S,
    Cancelled,
    OtaUpload,
    probe,
    send_reboot,
)

log = logging.getLogger(__name__)

# Progress signals are throttled to this many per second; per-chunk (4 KiB)
# emission would flood the event loop for no visible gain.
_PROGRESS_HZ = 20
# Upload speed is measured over this trailing window; below the minimum span
# the rate is reported as 0 (unknown) rather than a meaningless spike.
_RATE_WINDOW_S = 2.0
_RATE_MIN_SPAN_S = 0.5

# Device probes run in parallel so one offline board (2 s timeout) doesn't
# delay the others.
_PROBE_WORKERS = 8


class OtaRunner(QObject):
    """One OTA job at a time: upload -> (reboot) -> (wait until back online).

    `finished(ok, summary)` fires exactly once per start().
    """

    stage = Signal(str, str)              # stage key, human text
    progress = Signal(int, int, float)    # bytes sent, total, bytes/s
    log_line = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._upload: OtaUpload | None = None
        self._cancel = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, host: str, port: int, firmware: str, *,
              reboot: bool = True, wait_online: bool = True) -> None:
        if self.is_running:
            raise RuntimeError("an OTA job is already running")
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run, args=(host, port, firmware, reboot, wait_online),
            name="esp-ota", daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()
        upload = self._upload
        if upload is not None:
            upload.cancel()

    def shutdown(self, timeout: float = 2.0) -> None:
        self.cancel()
        if self._thread is not None:
            self._thread.join(timeout)

    # ------------------------------------------------------------------
    # worker thread

    def _run(self, host: str, port: int, firmware: str, reboot: bool, wait: bool) -> None:
        try:
            ok, summary = self._job(host, port, firmware, reboot, wait)
        except Cancelled:
            ok, summary = False, "Cancelled"
        except Exception as exc:          # socket errors, timeouts, bad file …
            log.debug("OTA job failed", exc_info=True)
            ok, summary = False, _describe(exc)
        finally:
            self._upload = None
        self.log_line.emit(f"— {summary} —")
        self.finished.emit(ok, summary)

    def _job(self, host: str, port: int, firmware: str,
             reboot: bool, wait: bool) -> tuple[bool, str]:
        name = Path(firmware).name
        size = Path(firmware).stat().st_size
        self.stage.emit("upload", "Uploading…")
        self.log_line.emit(f"Uploading {name} ({size:,} bytes) to http://{host}:{port}/ota/upload")

        # Speed over a sliding window: the first ~100 KiB land in the OS socket
        # buffer instantly, so a whole-upload average starts absurdly high.
        samples: deque[tuple[float, int]] = deque()
        last_emit = 0.0

        def on_progress(sent: int, total: int) -> None:
            nonlocal last_emit
            now = time.monotonic()
            samples.append((now, sent))
            while len(samples) > 2 and now - samples[0][0] > _RATE_WINDOW_S:
                samples.popleft()
            if sent == total or now - last_emit >= 1 / _PROGRESS_HZ:
                last_emit = now
                t_old, s_old = samples[0]
                span = now - t_old
                rate = (sent - s_old) / span if span >= _RATE_MIN_SPAN_S else 0.0
                self.progress.emit(sent, total, rate)

        def on_sent() -> None:
            self.stage.emit("validate", "Validating image on device…")

        self._upload = OtaUpload(host, port, firmware)
        # A cancel() that landed before _upload existed only set the event.
        self._check_cancel()
        result = self._upload.run(on_progress, on_sent)
        self._upload = None
        self.log_line.emit(
            f"Sent in {result.sent_s:.2f} s, response after {result.total_s:.2f} s — "
            f"effective {size / max(result.total_s, 1e-6) / 1024:.1f} KB/s"
        )
        if not result.ok:
            detail = f": {result.body}" if result.body else ""
            return False, f"Upload rejected (HTTP {result.status}){detail}"
        self.log_line.emit(f"Upload OK: {result.body or 'HTTP 200'}")

        if not reboot:
            return True, "Uploaded — update staged, reboot when ready"
        self._check_cancel()

        self.stage.emit("reboot", "Rebooting…")
        try:
            send_reboot(host, port)
            self.log_line.emit("Reboot requested")
        except OSError as exc:
            # The device may drop the socket as it reboots — expected.
            self.log_line.emit(f"(connection dropped during reboot trigger: {exc} — expected)")

        if not wait:
            return True, "Uploaded and reboot requested"

        self.stage.emit("wait", "Waiting for device…")
        for attempt in range(1, POLL_ATTEMPTS + 1):
            if self._cancel.wait(POLL_DELAY_S):
                raise Cancelled()
            self.stage.emit("wait", f"Waiting for device… ({attempt}/{POLL_ATTEMPTS})")
            if probe(host, port, timeout=3.0):
                self.log_line.emit(f"Device is back up (attempt {attempt}/{POLL_ATTEMPTS})")
                return True, "Updated — device is back online"
        return False, f"Uploaded, but the device did not respond after {POLL_ATTEMPTS} attempts"

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()


def _describe(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):      # socket.timeout is an alias since 3.10
        return "Timed out talking to the device"
    if isinstance(exc, ConnectionRefusedError):
        return "Connection refused — is the http_panel running?"
    if isinstance(exc, OSError) and exc.strerror:
        return f"Network error: {exc.strerror}"
    return str(exc) or type(exc).__name__


class DeviceProber(QObject):
    """Periodically checks which saved devices answer GET / (online dots).

    One background sweep at a time; results arrive as {"host:port": bool}.
    Paused while an OTA job runs so it never competes with the upload.
    """

    results = Signal(dict)

    def __init__(self, interval_ms: int = 10_000, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._targets: list[tuple[str, int]] = []
        self._busy = False
        self._pending = False     # a check was requested mid-sweep: rerun after
        self._paused = False
        self.results.connect(self._on_sweep_done)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.check_now)

    def set_targets(self, targets: list[tuple[str, int]]) -> None:
        self._targets = list(targets)

    def start(self) -> None:
        self._timer.start()
        self.check_now()

    def stop(self) -> None:
        self._timer.stop()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def check_now(self) -> None:
        if self._paused or not self._targets:
            return
        if self._busy:
            # e.g. a device was just added: don't drop the request, queue it.
            self._pending = True
            return
        self._busy = True
        targets = list(self._targets)
        threading.Thread(target=self._sweep, args=(targets,), name="esp-ota-probe",
                         daemon=True).start()

    def _sweep(self, targets: list[tuple[str, int]]) -> None:
        out: dict[str, bool] = {}
        try:
            with ThreadPoolExecutor(max_workers=_PROBE_WORKERS) as pool:
                alive = pool.map(lambda t: probe(*t), targets)
                out = {f"{h}:{p}": ok for (h, p), ok in zip(targets, alive, strict=True)}
        finally:
            # _busy is cleared on the GUI thread (_on_sweep_done) so it can't
            # race with check_now(); emit even on failure to release it.
            self.results.emit(out)

    def _on_sweep_done(self, _results: dict) -> None:
        self._busy = False
        if self._pending:
            self._pending = False
            self.check_now()
