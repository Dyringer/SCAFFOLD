from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.services.network import network_service
from app.services.network.types import ConnState, Message
from app.subapps.network_tools.benchmark_widget import BenchmarkWidget, NS_BENCH
from app.subapps.network_tools.custom_message_widget import CustomMessageWidget
from app.subapps.network_tools.sparkline import SparklineWidget


_STATE_COLOR = {
    ConnState.DISCONNECTED: "#888",
    ConnState.CONNECTING: "#d4a017",
    ConnState.HANDSHAKING: "#d4a017",
    ConnState.CONNECTED: "#3ba55c",
    ConnState.ERROR: "#d9534f",
}


class PeerDetailWidget(QFrame):
    """Live view of a single peer, with controls to connect/disconnect,
    benchmark, and send arbitrary messages."""

    custom_message_sent = Signal(str, object)   # (peer_id, Message)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self._peer_id = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # title row
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Selected peer")
        title.setStyleSheet("font-weight: 600;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self._state_dot = QLabel("●")
        self._state_dot.setStyleSheet("color: #888; font-weight: 700;")
        title_row.addWidget(self._state_dot)
        self._state_label = QLabel("—")
        self._state_label.setStyleSheet("color: #888;")
        title_row.addWidget(self._state_label)
        root.addLayout(title_row)

        # info block
        self._info = QLabel("Select a peer to see details.")
        self._info.setStyleSheet("font-family: 'Consolas','Menlo',monospace; color: #aaa;")
        self._info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._info.setWordWrap(True)
        self._info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(self._info)

        # rtt + bandwidth row
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.addWidget(QLabel("RTT"))
        self._sparkline = SparklineWidget(color="#5a8dee", width=200, height=24)
        stats_row.addWidget(self._sparkline)
        self._rtt_text = QLabel("—")
        self._rtt_text.setStyleSheet("color: #888;")
        stats_row.addWidget(self._rtt_text)
        stats_row.addStretch(1)
        self._bw = QLabel("↑ — ↓ —")
        self._bw.setStyleSheet("font-family: 'Consolas','Menlo',monospace; color: #888;")
        stats_row.addWidget(self._bw)
        root.addLayout(stats_row)

        # action buttons
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._on_connect)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        self._reconnect_btn = QPushButton("Reconnect")
        self._reconnect_btn.clicked.connect(self._on_reconnect)
        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._disconnect_btn)
        btn_row.addWidget(self._reconnect_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # benchmark
        self._bench = BenchmarkWidget()
        root.addWidget(self._bench)

        # custom send
        self._custom = CustomMessageWidget()
        self._custom.sent.connect(self.custom_message_sent)
        root.addWidget(self._custom)

        root.addStretch(1)

        # bandwidth deltas
        self._last_bytes_sent = 0
        self._last_bytes_received = 0
        self._last_sample_at = time.time()

        # wire service signals
        network_service.peer_connected.connect(self._on_peer_state_changed)
        network_service.peer_disconnected.connect(self._on_peer_state_changed_id)
        network_service.rtt_sample.connect(self._on_rtt_sample)
        # 1Hz refresh for info + bandwidth deltas
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._refresh)
        self._tick.start()

        # route inbound _bench messages to the runner so echo/match works
        network_service.message_received.connect(self._route_bench)

        self._update_buttons()

    # ------------------------------------------------------------------

    def set_peer(self, peer_id: str) -> None:
        self._peer_id = peer_id
        self._last_bytes_sent = 0
        self._last_bytes_received = 0
        self._last_sample_at = time.time()
        self._bench.set_peer(peer_id)
        self._custom.set_peer(peer_id)
        self._refresh()

    def clear(self) -> None:
        self.set_peer("")

    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        if not self._peer_id:
            self._info.setText("Select a peer to see details.")
            self._sparkline.set_values([])
            self._rtt_text.setText("—")
            self._bw.setText("↑ — ↓ —")
            self._update_buttons()
            return
        peer = network_service.presence.get(self._peer_id)
        if peer is None:
            self._info.setText("Peer no longer in presence.")
            self._update_buttons()
            return

        state = peer.conn_state
        color = _STATE_COLOR.get(state, "#888")
        self._state_dot.setStyleSheet(f"color: {color}; font-weight: 700;")
        self._state_label.setText(state.value)
        self._state_label.setStyleSheet(f"color: {color};")

        lines = [
            f"peer_id     {peer.peer_id}",
            f"nick        {peer.nick}",
            f"host        {peer.host}",
            f"control     {peer.control_port}",
            f"proto       {peer.proto_version}",
            f"kind        {peer.kind.value}",
            f"last seen   {peer.age:.1f}s ago",
        ]
        self._info.setText("\n".join(lines))

        # sparkline + rtt summary
        rtts_ms = [r * 1000 for r in peer.rtt_history]
        self._sparkline.set_values(rtts_ms)
        if rtts_ms:
            avg = sum(rtts_ms) / len(rtts_ms)
            self._rtt_text.setText(
                f"last {rtts_ms[-1]:.1f}ms   avg {avg:.1f}ms   n={len(rtts_ms)}"
            )
        else:
            self._rtt_text.setText("no samples")

        # bandwidth delta
        now = time.time()
        elapsed = max(now - self._last_sample_at, 0.001)
        d_sent = max(peer.bytes_sent - self._last_bytes_sent, 0)
        d_recv = max(peer.bytes_received - self._last_bytes_received, 0)
        up = d_sent / elapsed
        dn = d_recv / elapsed
        self._bw.setText(
            f"↑ {self._fmt_rate(up)}   ↓ {self._fmt_rate(dn)}   "
            f"total: ↑ {self._fmt_bytes(peer.bytes_sent)} ↓ {self._fmt_bytes(peer.bytes_received)}"
        )
        self._last_bytes_sent = peer.bytes_sent
        self._last_bytes_received = peer.bytes_received
        self._last_sample_at = now

        self._update_buttons()

    @staticmethod
    def _fmt_rate(bps: float) -> str:
        if bps < 1024:
            return f"{bps:.0f} B/s"
        if bps < 1024 * 1024:
            return f"{bps/1024:.1f} KB/s"
        return f"{bps/(1024*1024):.2f} MB/s"

    @staticmethod
    def _fmt_bytes(n: int) -> str:
        if n < 1024:
            return f"{n} B"
        if n < 1024 * 1024:
            return f"{n/1024:.1f} KB"
        return f"{n/(1024*1024):.2f} MB"

    def _update_buttons(self) -> None:
        has_peer = bool(self._peer_id)
        peer = network_service.presence.get(self._peer_id) if has_peer else None
        connected = bool(peer) and network_service.is_connected(self._peer_id)
        reachable = bool(peer) and peer.control_port > 0
        self._connect_btn.setEnabled(has_peer and not connected and reachable)
        self._disconnect_btn.setEnabled(connected)
        self._reconnect_btn.setEnabled(connected and reachable)
        # also gate bench/custom run controls — set_peer already handled but
        # state could change between selections
        self._bench.set_peer(self._peer_id if connected else "")
        self._custom.set_peer(self._peer_id if connected else "")

    # ------------------------------------------------------------------

    def _on_connect(self) -> None:
        peer = network_service.presence.get(self._peer_id)
        if peer is None or peer.control_port <= 0:
            return
        network_service.connect_manual(peer.host, peer.control_port)

    def _on_disconnect(self) -> None:
        if self._peer_id:
            network_service.disconnect_peer(self._peer_id, "user")

    def _on_reconnect(self) -> None:
        if self._peer_id:
            network_service.reconnect_peer(self._peer_id)

    def _on_peer_state_changed(self, peer) -> None:
        if peer.peer_id == self._peer_id:
            self._refresh()

    def _on_peer_state_changed_id(self, peer_id: str) -> None:
        if peer_id == self._peer_id:
            self._refresh()

    def _on_rtt_sample(self, peer_id: str, _rtt: float) -> None:
        if peer_id == self._peer_id:
            # don't wait for the 1Hz tick to refresh the sparkline
            peer = network_service.presence.get(peer_id)
            if peer is not None:
                self._sparkline.set_values([r * 1000 for r in peer.rtt_history])

    def _route_bench(self, peer_id: str, msg: Message) -> None:
        if msg.ns == NS_BENCH:
            self._bench.runner.on_inbound(peer_id, msg)
