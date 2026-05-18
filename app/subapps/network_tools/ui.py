from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from app.services.network import network_service
from app.services.network.types import Message, PeerInfo
from app.subapps.network_tools.discovery_diagnostics_widget import (
    DiscoveryDiagnosticsWidget,
)
from app.subapps.network_tools.message_log_widget import MessageLogWidget
from app.subapps.network_tools.peer_detail_widget import PeerDetailWidget
from app.subapps.network_tools.peer_list_widget import (
    ManualConnectForm, PeerListWidget,
)
from app.subapps.network_tools.self_test_widget import SelfTestWidget


class _StatusStrip(QFrame):
    """Bottom strip: identity, peer count, beacon counters, total bandwidth."""

    def __init__(self, service=network_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("color: #888;")

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(16)

        self._identity = QLabel("")
        self._bw = QLabel("↑ 0 B/s   ↓ 0 B/s")
        self._bw.setStyleSheet(
            "font-family: 'Consolas','Menlo',monospace; color: #888;"
        )
        self._peer_count = QLabel("peers: 0")
        self._beacons = QLabel("beacons: 0/0")
        row.addWidget(self._identity)
        row.addStretch(1)
        row.addWidget(self._bw)
        row.addWidget(self._peer_count)
        row.addWidget(self._beacons)

        self._last_total_sent = 0
        self._last_total_recv = 0
        self._last_sample_at = time.time()

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self.refresh)
        self._tick.start()
        self.refresh()

    def refresh(self) -> None:
        s = self._service
        self._identity.setText(f"id={s.peer_id[:8]}  nick={s.nick}")

        # Sum bytes across all peers
        total_sent = sum(p.bytes_sent for p in s.peers())
        total_recv = sum(p.bytes_received for p in s.peers())
        now = time.time()
        elapsed = max(now - self._last_sample_at, 0.001)
        up = max(total_sent - self._last_total_sent, 0) / elapsed
        dn = max(total_recv - self._last_total_recv, 0) / elapsed
        self._bw.setText(f"↑ {self._fmt(up)}   ↓ {self._fmt(dn)}")
        self._last_total_sent = total_sent
        self._last_total_recv = total_recv
        self._last_sample_at = now

        connected = sum(1 for p in s.peers() if s.is_connected(p.peer_id))
        self._peer_count.setText(f"peers: {connected}/{len(s.presence)}")
        d = s.discovery
        if d is not None:
            t = d.telemetry
            self._beacons.setText(f"beacons: {t.beacons_sent}/{t.beacons_received}")

    @staticmethod
    def _fmt(bps: float) -> str:
        if bps < 1024:
            return f"{bps:.0f} B/s"
        if bps < 1024 * 1024:
            return f"{bps/1024:.1f} KB/s"
        return f"{bps/(1024*1024):.2f} MB/s"


class NetworkToolsPanel(QWidget):
    """Top-level panel for the Network Tools subapp.

    3-column splitter:
      left   — self-test, peer list, manual connect, diagnostics
      middle — selected peer detail (info, bw, sparkline, bench, custom send)
      right  — message log
    Bottom: status strip.
    """

    def __init__(self, service=network_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)

        # --- left column ---
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)

        self._self_test = SelfTestWidget(service)
        self._peer_list = PeerListWidget(service)
        self._manual = ManualConnectForm()
        self._diagnostics = DiscoveryDiagnosticsWidget(service)

        ll.addWidget(self._self_test)
        ll.addWidget(self._peer_list, 1)
        ll.addWidget(self._manual)

        diag_scroll = QScrollArea()
        diag_scroll.setWidget(self._diagnostics)
        diag_scroll.setWidgetResizable(True)
        diag_scroll.setFrameShape(QFrame.NoFrame)
        diag_scroll.setMaximumHeight(320)
        ll.addWidget(diag_scroll)

        splitter.addWidget(left)

        # --- middle column ---
        self._detail = PeerDetailWidget()
        detail_scroll = QScrollArea()
        detail_scroll.setWidget(self._detail)
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.NoFrame)
        splitter.addWidget(detail_scroll)

        # --- right column ---
        self._log = MessageLogWidget()
        splitter.addWidget(self._log)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 4)
        splitter.setSizes([360, 360, 420])
        outer.addWidget(splitter, 1)

        self._status = _StatusStrip(service)
        outer.addWidget(self._status)

        # wiring
        self._peer_list.peer_selected.connect(self._on_peer_selected)
        self._manual.connect_requested.connect(self._on_manual_connect)
        self._detail.custom_message_sent.connect(self._on_custom_sent)

        service.peer_appeared.connect(self._on_peer_appeared_log)
        service.peer_left.connect(self._on_peer_left_log)
        service.peer_connected.connect(self._on_peer_connected_log)
        service.peer_disconnected.connect(self._on_peer_disconnected_log)
        service.message_received.connect(self._on_msg_received_log)
        service.message_sent.connect(self._on_msg_sent_log)

        self._log.append(
            "info", f"network_tools ready  id={service.peer_id[:8]}  nick={service.nick}"
        )

    # ------------------------------------------------------------------

    def _on_peer_selected(self, peer_id: str) -> None:
        self._detail.set_peer(peer_id)

    def _on_manual_connect(self, host: str, port: int) -> None:
        ok = self._service.connect_manual(host, port)
        if ok:
            self._log.append("conn", f"dialing {host}:{port} …")
        else:
            self._log.append("warn", f"manual connect rejected: {host}:{port}")

    def _on_custom_sent(self, peer_id: str, msg: Message) -> None:
        # message_sent signal will also log it; nothing extra needed.
        pass

    def _on_peer_appeared_log(self, peer: PeerInfo) -> None:
        self._log.append(
            "peer", f"appeared  {peer.nick}  [{peer.peer_id[:8]}]  "
                    f"{peer.address}  ({peer.kind.value})"
        )

    def _on_peer_left_log(self, peer_id: str) -> None:
        self._log.append("peer", f"left      [{peer_id[:8]}]")

    def _on_peer_connected_log(self, peer: PeerInfo) -> None:
        self._log.append(
            "conn", f"connected [{peer.peer_id[:8]}]  proto={peer.proto_version}"
        )

    def _on_peer_disconnected_log(self, peer_id: str) -> None:
        self._log.append("conn", f"disconnected [{peer_id[:8]}]")

    def _on_msg_received_log(self, peer_id: str, msg: Message) -> None:
        if msg.ns == "_net" or msg.ns == "_bench":
            return  # too chatty for the log
        self._log.append("←", f"[{peer_id[:8]}]  {msg.ns}/{msg.type}  {self._fmt_data(msg)}")

    def _on_msg_sent_log(self, peer_id: str, msg: Message) -> None:
        if msg.ns == "_net" or msg.ns == "_bench":
            return
        self._log.append("→", f"[{peer_id[:8]}]  {msg.ns}/{msg.type}  {self._fmt_data(msg)}")

    @staticmethod
    def _fmt_data(msg: Message) -> str:
        import json
        s = json.dumps(msg.data, separators=(",", ":"))
        return s if len(s) <= 120 else s[:117] + "…"
