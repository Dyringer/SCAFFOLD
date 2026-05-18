from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from app.services.network import network_service
from app.services.network.types import ConnState, PeerInfo, PeerKind


_KIND_TAG = {
    PeerKind.LAN: "",
    PeerKind.LOOPBACK: "loopback",
    PeerKind.MANUAL: "manual",
}


class PeerListWidget(QWidget):
    """Live list of discovered peers. Selecting one emits peer_selected(peer_id)."""

    peer_selected = Signal(str)   # peer_id

    def __init__(self, service=network_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Discovered peers")
        title.setStyleSheet("font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedHeight(24)
        self._refresh_btn.clicked.connect(self._rebuild)
        self._beacon_btn = QPushButton("Force beacon")
        self._beacon_btn.setFixedHeight(24)
        self._beacon_btn.clicked.connect(self._service.force_beacon)
        header.addWidget(self._refresh_btn)
        header.addWidget(self._beacon_btn)
        root.addLayout(header)

        self._list = QListWidget()
        self._list.itemSelectionChanged.connect(self._on_selection)
        root.addWidget(self._list, 1)

        self._empty_hint = QLabel("No peers visible yet. Beacons go out every 2s.")
        self._empty_hint.setStyleSheet("color: #888; font-style: italic;")
        self._empty_hint.setAlignment(Qt.AlignCenter)
        root.addWidget(self._empty_hint)

        # bindings
        self._service.peer_appeared.connect(self._on_peer_change)
        self._service.peer_updated.connect(self._on_peer_change)
        self._service.peer_left.connect(self._on_peer_left)
        self._service.peer_connected.connect(self._on_peer_change)
        self._service.peer_disconnected.connect(self._on_peer_state_id)

        # refresh "age" text every second
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._refresh_age)
        self._tick.start()

        self._rebuild()

    # ------------------------------------------------------------------
    # rebuild / update

    def _rebuild(self) -> None:
        selected = self.current_peer_id()
        self._list.clear()
        for peer in self._service.peers():
            self._list.addItem(self._make_item(peer))
        self._update_empty_hint()
        if selected:
            self.select_peer(selected)

    def _make_item(self, peer: PeerInfo) -> QListWidgetItem:
        item = QListWidgetItem(self._format_row(peer))
        item.setData(Qt.UserRole, peer.peer_id)
        return item

    def _format_row(self, peer: PeerInfo) -> str:
        # Glyph by connection state, with kind/age suffixes
        if peer.conn_state == ConnState.CONNECTED:
            dot = "●"   # filled — fully connected
        elif peer.conn_state in (ConnState.CONNECTING, ConnState.HANDSHAKING):
            dot = "◐"   # half-filled — in progress
        else:
            dot = "○"   # outline — known but not connected
        tag = _KIND_TAG.get(peer.kind, "")
        suffix = f"  ({tag})" if tag else ""
        age_str = f"  −{int(peer.age)}s" if peer.age > 5 else ""
        return f"{dot}  {peer.nick}   [{peer.peer_id[:8]}]   {peer.address}{suffix}{age_str}"

    def _on_peer_change(self, peer: PeerInfo) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == peer.peer_id:
                item.setText(self._format_row(peer))
                self._update_empty_hint()
                return
        self._list.addItem(self._make_item(peer))
        self._update_empty_hint()

    def _on_peer_left(self, peer_id: str) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == peer_id:
                self._list.takeItem(i)
                break
        self._update_empty_hint()

    def _on_peer_state_id(self, peer_id: str) -> None:
        peer = self._service.presence.get(peer_id)
        if peer is not None:
            self._on_peer_change(peer)

    def _refresh_age(self) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            pid = item.data(Qt.UserRole)
            peer = self._service.presence.get(pid)
            if peer is not None:
                item.setText(self._format_row(peer))

    def _update_empty_hint(self) -> None:
        self._empty_hint.setVisible(self._list.count() == 0)

    # ------------------------------------------------------------------
    # selection

    def _on_selection(self) -> None:
        pid = self.current_peer_id()
        if pid:
            self.peer_selected.emit(pid)

    def current_peer_id(self) -> str | None:
        items = self._list.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.UserRole)

    def select_peer(self, peer_id: str) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == peer_id:
                self._list.setCurrentRow(i)
                return


class ManualConnectForm(QFrame):
    """Dial a peer by host:port, bypassing discovery."""

    connect_requested = Signal(str, int)   # host, port

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)

        from PySide6.QtWidgets import QFormLayout, QLineEdit, QSpinBox

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        title = QLabel("Manual connect")
        title.setStyleSheet("font-weight: 600;")
        root.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self._host = QLineEdit()
        self._host.setPlaceholderText("192.168.1.42 or 127.0.0.1")
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(45455)
        form.addRow("Host", self._host)
        form.addRow("Port", self._port)
        root.addLayout(form)

        self._btn = QPushButton("Connect")
        self._btn.clicked.connect(self._emit)
        self._btn.setToolTip(
            "Open a control channel to host:port, bypassing discovery."
        )
        root.addWidget(self._btn)

    def _emit(self) -> None:
        host = self._host.text().strip()
        if host:
            self.connect_requested.emit(host, self._port.value())
