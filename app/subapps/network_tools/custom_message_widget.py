from __future__ import annotations

import json

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from app.services.network import network_service
from app.services.network.types import Message


class CustomMessageWidget(QFrame):
    """Compose and send an arbitrary Message to the selected peer."""

    sent = Signal(str, object)   # (peer_id, Message) — for log integration

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self._peer_id = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        title = QLabel("Send custom message")
        title.setStyleSheet("font-weight: 600;")
        root.addWidget(title)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.addWidget(QLabel("ns"))
        self._ns = QComboBox()
        self._ns.setEditable(True)
        row1.addWidget(self._ns, 1)
        row1.addSpacing(4)
        row1.addWidget(QLabel("type"))
        self._type = QLineEdit()
        self._type.setText("msg")
        row1.addWidget(self._type, 1)
        root.addLayout(row1)

        self._data = QPlainTextEdit()
        self._data.setFont(QFont("Consolas", 9))
        self._data.setPlainText('{"text": "hello"}')
        self._data.setMaximumHeight(80)
        root.addWidget(self._data)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        self._status = QLabel("")
        self._status.setStyleSheet("color: #888;")
        row2.addWidget(self._status, 1)
        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._on_send)
        row2.addWidget(self._send_btn)
        root.addLayout(row2)

        self._refresh_namespaces()

    def set_peer(self, peer_id: str) -> None:
        self._peer_id = peer_id
        self._send_btn.setEnabled(
            bool(peer_id) and network_service.is_connected(peer_id)
        )
        self._refresh_namespaces()

    def _refresh_namespaces(self) -> None:
        current = self._ns.currentText()
        self._ns.clear()
        registered = network_service.registered_namespaces()
        # Always allow custom — combo is editable. Provide common shortcuts.
        for ns in ["chat", "_bench", "_net"] + [r for r in registered if r not in ("chat", "_bench", "_net")]:
            self._ns.addItem(ns)
        if current:
            self._ns.setEditText(current)
        else:
            self._ns.setEditText("chat")

    def _on_send(self) -> None:
        if not self._peer_id:
            self._status.setText("no peer selected")
            return
        ns = self._ns.currentText().strip()
        msg_type = self._type.text().strip()
        if not ns or not msg_type:
            self._status.setText("ns and type required")
            return
        raw = self._data.toPlainText().strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._status.setText(f"bad JSON: {exc.msg}")
                return
            if not isinstance(data, dict):
                self._status.setText("data must be a JSON object")
                return
        else:
            data = {}
        msg = Message(ns=ns, type=msg_type, data=data)
        if not network_service.send(self._peer_id, msg):
            self._status.setText("not connected")
            return
        self._status.setText("sent")
        self.sent.emit(self._peer_id, msg)
