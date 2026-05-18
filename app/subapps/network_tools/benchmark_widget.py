from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from app.services.network import network_service
from app.services.network.types import Message, new_msg_id

log = logging.getLogger(__name__)


# Reserved namespace for the in-app benchmark protocol.
# Not _net so subapps can also wire 'echo' tests if they want.
NS_BENCH = "_bench"


class BenchmarkRunner(QObject):
    """Runs ping or throughput against one peer.

    Ping mode: sends N small messages, matches replies by id, records RTTs.
    Throughput mode: streams N messages of size S, peer acks final; measures
    sender->receiver bandwidth from total bytes / elapsed.

    Both modes use the _bench namespace. Receiving side echoes pings as-is
    and acks throughput tests with the final id.
    """

    progress = Signal(int, int)        # (done, total)
    finished = Signal(dict)            # result dict
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._peer_id = ""
        self._mode = "ping"
        self._count = 0
        self._size = 0
        self._sent: dict[str, float] = {}     # msg_id -> sent_at
        self._rtts: list[float] = []
        self._tp_total_bytes = 0
        self._tp_start_at = 0.0
        self._tp_final_id = ""
        self._done = 0
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)

    @property
    def busy(self) -> bool:
        return self._done < self._count if self._count else False

    def run_ping(self, peer_id: str, count: int) -> None:
        self._reset(peer_id, "ping", count, size=0)
        self._step_ping()

    def run_throughput(self, peer_id: str, count: int, size: int) -> None:
        self._reset(peer_id, "throughput", count, size=size)
        self._tp_start_at = time.time()
        self._step_throughput()

    def _reset(self, peer_id: str, mode: str, count: int, size: int) -> None:
        self._peer_id = peer_id
        self._mode = mode
        self._count = max(1, count)
        self._size = max(1, size)
        self._sent.clear()
        self._rtts.clear()
        self._done = 0
        self._tp_total_bytes = 0
        self._tp_final_id = ""
        self._timeout_timer.start(max(5_000, count * 50))

    # ------------------------------------------------------------------

    def on_inbound(self, peer_id: str, msg: Message) -> None:
        """Match pong/ack against our outstanding requests.

        Receiver-side echo is handled by NetworkService directly, so this
        runner only cares about messages that correspond to a benchmark
        WE initiated.
        """
        if msg.ns != NS_BENCH:
            return
        if peer_id != self._peer_id:
            return
        if msg.type == "pong" and self._mode == "ping":
            sent_at = self._sent.pop(msg.id, None)
            if sent_at is not None:
                rtt = time.time() - sent_at
                self._rtts.append(rtt)
                self._done += 1
                self.progress.emit(self._done, self._count)
                if self._done >= self._count:
                    self._finish_ping()
                else:
                    self._step_ping()
        elif msg.type == "tp_ack" and self._mode == "throughput":
            if msg.id == self._tp_final_id:
                self._finish_throughput()

    # ------------------------------------------------------------------

    def _step_ping(self) -> None:
        msg_id = new_msg_id()
        self._sent[msg_id] = time.time()
        ok = network_service.send(self._peer_id, Message(
            ns=NS_BENCH, type="ping", id=msg_id, data={},
        ))
        if not ok:
            self._fail("peer not connected")

    def _step_throughput(self) -> None:
        # Build payload of approximately self._size bytes.
        # Use a string of 'x' characters; JSON overhead is small.
        payload = "x" * self._size
        for i in range(self._count):
            msg_id = new_msg_id()
            is_final = (i == self._count - 1)
            if is_final:
                self._tp_final_id = msg_id
            msg = Message(
                ns=NS_BENCH, type="tp_data", id=msg_id,
                data={"i": i, "p": payload, "final": is_final},
            )
            ok = network_service.send(self._peer_id, msg)
            if not ok:
                self._fail("peer not connected")
                return
            self._tp_total_bytes += len(payload) + 64  # rough json overhead
            self._done = i + 1
            self.progress.emit(self._done, self._count)

    def _finish_ping(self) -> None:
        self._timeout_timer.stop()
        rtts_ms = [r * 1000 for r in self._rtts]
        rtts_ms.sort()
        n = len(rtts_ms)
        if n == 0:
            self._fail("no pongs")
            return
        result = {
            "mode": "ping",
            "count": n,
            "loss": self._count - n,
            "avg_ms": sum(rtts_ms) / n,
            "min_ms": rtts_ms[0],
            "max_ms": rtts_ms[-1],
            "p50_ms": rtts_ms[n // 2],
            "p99_ms": rtts_ms[min(n - 1, int(n * 0.99))],
        }
        self.finished.emit(result)

    def _finish_throughput(self) -> None:
        self._timeout_timer.stop()
        elapsed = max(time.time() - self._tp_start_at, 0.001)
        result = {
            "mode": "throughput",
            "count": self._count,
            "bytes": self._tp_total_bytes,
            "elapsed_s": elapsed,
            "mbps": (self._tp_total_bytes / elapsed) / (1024 * 1024),
        }
        self.finished.emit(result)

    def _on_timeout(self) -> None:
        self._fail("timed out")

    def _fail(self, reason: str) -> None:
        self._timeout_timer.stop()
        self.failed.emit(reason)


class BenchmarkWidget(QFrame):
    """UI around BenchmarkRunner. Used inside the peer-detail pane."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self._peer_id = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        title = QLabel("Benchmark")
        title.setStyleSheet("font-weight: 600;")
        root.addWidget(title)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.addWidget(QLabel("Mode"))
        self._mode = QComboBox()
        self._mode.addItem("Ping", "ping")
        self._mode.addItem("Throughput", "throughput")
        self._mode.currentIndexChanged.connect(self._on_mode_changed)
        row1.addWidget(self._mode)
        row1.addSpacing(8)
        row1.addWidget(QLabel("Count"))
        self._count = QSpinBox()
        self._count.setRange(1, 100000)
        self._count.setValue(100)
        row1.addWidget(self._count)
        self._size_label = QLabel("Size (B)")
        self._size = QSpinBox()
        self._size.setRange(1, 1_000_000)
        self._size.setValue(1024)
        self._size_label.hide()
        self._size.hide()
        row1.addWidget(self._size_label)
        row1.addWidget(self._size)
        row1.addStretch(1)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        self._run_btn = QPushButton("Run")
        self._run_btn.clicked.connect(self._on_run)
        row2.addWidget(self._run_btn)
        self._progress = QProgressBar()
        self._progress.setFixedHeight(16)
        self._progress.setTextVisible(False)
        row2.addWidget(self._progress, 1)
        root.addLayout(row2)

        self._result = QLabel("")
        self._result.setStyleSheet("font-family: 'Consolas','Menlo',monospace;")
        self._result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._result.setWordWrap(True)
        root.addWidget(self._result)

        self._runner = BenchmarkRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)

    @property
    def runner(self) -> BenchmarkRunner:
        return self._runner

    def set_peer(self, peer_id: str) -> None:
        self._peer_id = peer_id
        self._run_btn.setEnabled(
            bool(peer_id) and network_service.is_connected(peer_id)
        )

    # ------------------------------------------------------------------

    def _on_mode_changed(self) -> None:
        is_tp = self._mode.currentData() == "throughput"
        self._size_label.setVisible(is_tp)
        self._size.setVisible(is_tp)
        if is_tp:
            self._count.setValue(min(self._count.value(), 5000))

    def _on_run(self) -> None:
        if not self._peer_id or not network_service.is_connected(self._peer_id):
            self._result.setText("Not connected to peer.")
            return
        self._progress.setMaximum(self._count.value())
        self._progress.setValue(0)
        self._result.setText("running…")
        mode = self._mode.currentData()
        if mode == "ping":
            self._runner.run_ping(self._peer_id, self._count.value())
        else:
            self._runner.run_throughput(
                self._peer_id, self._count.value(), self._size.value(),
            )

    def _on_progress(self, done: int, total: int) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(done)

    def _on_finished(self, result: dict) -> None:
        if result["mode"] == "ping":
            self._result.setText(
                f"avg {result['avg_ms']:.1f} ms   "
                f"min {result['min_ms']:.1f}   "
                f"p50 {result['p50_ms']:.1f}   "
                f"p99 {result['p99_ms']:.1f}   "
                f"max {result['max_ms']:.1f}   "
                f"loss {result['loss']}/{result['count'] + result['loss']}"
            )
        else:
            self._result.setText(
                f"{result['mbps']:.2f} MB/s  "
                f"({result['bytes']} bytes in {result['elapsed_s']:.2f}s, "
                f"{result['count']} msgs)"
            )

    def _on_failed(self, reason: str) -> None:
        self._result.setText(f"failed: {reason}")
