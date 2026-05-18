from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.services.network import network_service


_PENDING = "·"
_PASS = "✓"
_FAIL = "✗"


class _Check(QWidget):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._status = QLabel(_PENDING)
        self._status.setFixedWidth(14)
        self._status.setStyleSheet("font-weight: 700; color: #888;")
        self._label = QLabel(label)
        self._detail = QLabel("")
        self._detail.setStyleSheet("color: #888;")
        row.addWidget(self._status)
        row.addWidget(self._label)
        row.addStretch(1)
        row.addWidget(self._detail)

    def reset(self) -> None:
        self._status.setText(_PENDING)
        self._status.setStyleSheet("font-weight: 700; color: #888;")
        self._detail.setText("")

    def pass_(self, detail: str = "") -> None:
        self._status.setText(_PASS)
        self._status.setStyleSheet("font-weight: 700; color: #3ba55c;")
        self._detail.setText(detail)

    def fail(self, detail: str = "") -> None:
        self._status.setText(_FAIL)
        self._status.setStyleSheet("font-weight: 700; color: #d9534f;")
        self._detail.setText(detail)


class SelfTestWidget(QFrame):
    """Runs a sequence of network self-checks. Phase A version covers
    discovery only; Phase B adds the control-channel ping check.
    """

    def __init__(self, service=network_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.setFrameShape(QFrame.NoFrame)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("Self-test")
        title.setStyleSheet("font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        self._run_btn = QPushButton("Run")
        self._run_btn.setFixedHeight(24)
        self._run_btn.clicked.connect(self.run)
        header.addWidget(self._run_btn)
        root.addLayout(header)

        self._service_running = _Check("Network service running")
        self._control_server = _Check("Control server listening")
        self._beacon_sent = _Check("Discovery beacon sent")
        self._beacon_received = _Check("Own beacon received (loopback)")
        self._ping = _Check("Control-channel ping (any connected peer)")

        root.addWidget(self._service_running)
        root.addWidget(self._control_server)
        root.addWidget(self._beacon_sent)
        root.addWidget(self._beacon_received)
        root.addWidget(self._ping)

    # ------------------------------------------------------------------

    def run(self) -> None:
        for c in (self._service_running, self._control_server,
                  self._beacon_sent, self._beacon_received, self._ping):
            c.reset()

        if not self._service.is_running:
            self._service_running.fail("call network_service.start()")
            return
        self._service_running.pass_()

        srv = self._service.server
        if srv is None or srv.port <= 0:
            self._control_server.fail("no control server")
        else:
            self._control_server.pass_(f"port {srv.port}")

        disc = self._service.discovery
        if disc is None:
            self._beacon_sent.fail("no discovery agent")
            return
        before_sent = disc.telemetry.beacons_sent
        before_self = disc.telemetry.beacons_received_from_self
        disc.force_beacon()
        QTimer.singleShot(50, lambda: self._check_sent(before_sent, before_self))

    def _check_sent(self, before_sent: int, before_self: int) -> None:
        disc = self._service.discovery
        t = disc.telemetry
        if t.beacons_sent > before_sent:
            self._beacon_sent.pass_(f"#{t.beacons_sent}")
        else:
            self._beacon_sent.fail(f"counter did not advance ({t.bind_error or 'unknown'})")
            return
        QTimer.singleShot(500, lambda: self._check_self_received(before_self))

    def _check_self_received(self, before_self: int) -> None:
        disc = self._service.discovery
        t = disc.telemetry
        if t.beacons_received_from_self > before_self:
            self._beacon_received.pass_(f"loopback OK (#{t.beacons_received_from_self})")
        else:
            self._beacon_received.fail(
                "no self-beacon — multicast loopback may be disabled"
            )
        # Now ping check
        self._check_ping()

    def _check_ping(self) -> None:
        """Verify control-channel round-trip with any connected peer."""
        connected_peers = [
            p for p in self._service.peers()
            if self._service.is_connected(p.peer_id)
        ]
        if not connected_peers:
            self._ping._status.setText("—")
            self._ping._status.setStyleSheet("font-weight: 700; color: #888;")
            self._ping._detail.setText("no connected peers")
            return
        # Use the most recent rtt sample if available (ping is already
        # running on a 2s timer for every connected channel)
        recent = [p for p in connected_peers if p.rtt_history]
        if recent:
            p = recent[0]
            rtt_ms = p.rtt_last * 1000
            self._ping.pass_(f"{p.nick}: last RTT {rtt_ms:.1f} ms")
            return
        # Wait a beat — first ping fires immediately after handshake but
        # may not have completed yet.
        QTimer.singleShot(2200, self._recheck_ping)

    def _recheck_ping(self) -> None:
        for p in self._service.peers():
            if self._service.is_connected(p.peer_id) and p.rtt_history:
                rtt_ms = p.rtt_last * 1000
                self._ping.pass_(f"{p.nick}: last RTT {rtt_ms:.1f} ms")
                return
        self._ping.fail("ping sent but no pong within 2s")
