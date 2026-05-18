from __future__ import annotations

import logging
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress
from PySide6.QtWebSockets import QWebSocket, QWebSocketServer

from app.services.network.types import (
    NS_NET, PROTO_VERSION, ConnState, Message, PeerInfo, new_msg_id,
)

log = logging.getLogger(__name__)


PING_INTERVAL_MS = 2000
PING_TIMEOUT_S = 10.0
HANDSHAKE_TIMEOUT_S = 5.0


# ============================================================================
# MessageRouter
# ============================================================================

NamespaceHandler = Callable[[str, Message], None]  # (sender_peer_id, msg) -> None


class MessageRouter:
    """Routes inbound messages to namespace handlers.

    Subapps call NetworkService.register_namespace("chat", handler) and
    receive every message arriving on that namespace, along with the
    sender peer_id.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, NamespaceHandler] = {}

    def register(self, namespace: str, handler: NamespaceHandler) -> None:
        if namespace in self._handlers and self._handlers[namespace] is not handler:
            log.warning("overriding handler for namespace %r", namespace)
        self._handlers[namespace] = handler

    def unregister(self, namespace: str) -> None:
        self._handlers.pop(namespace, None)

    def namespaces(self) -> list[str]:
        return sorted(self._handlers.keys())

    def dispatch(self, peer_id: str, msg: Message) -> bool:
        handler = self._handlers.get(msg.ns)
        if handler is None:
            return False
        try:
            handler(peer_id, msg)
        except Exception:
            log.exception("handler for %r raised on %s", msg.ns, msg.type)
        return True


# ============================================================================
# ControlChannel — one per peer
# ============================================================================


class ControlChannel(QObject):
    """One persistent WS connection to a single peer.

    Owns: the QWebSocket, hello handshake, ping/pong RTT tracking, byte
    counters. The socket can be either:
      - INBOUND  (we accepted it from a QWebSocketServer)
      - OUTBOUND (we created QWebSocket and called open())

    Lifecycle states (ConnState):
      CONNECTING   -> socket opened (outbound) or accepted (inbound)
      HANDSHAKING  -> connected, waiting for _net.hello from peer
      CONNECTED    -> hello exchanged, peer_id known, ready for traffic
      ERROR        -> failure; channel will be torn down by owner
    """

    state_changed = Signal(object)         # ConnState
    handshaked = Signal(object)            # PeerInfo (synthesised from hello)
    message_received = Signal(str, object) # (peer_id, Message)
    message_sent = Signal(str, object)     # (peer_id, Message)  — peer_id may be "" pre-hello
    rtt_sample = Signal(str, float)        # (peer_id, rtt_seconds)
    bytes_changed = Signal(str, int, int)  # (peer_id, sent, received)
    closed = Signal(str, str)              # (peer_id, reason)

    def __init__(
        self,
        socket: QWebSocket,
        local_peer_id: str,
        local_nick: str,
        local_control_port: int,
        outbound: bool,
        remote_peer_id: str = "",   # known up front for outbound dial via discovery
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._socket = socket
        self._socket.setParent(self)
        self._local_peer_id = local_peer_id
        self._local_nick = local_nick
        self._local_control_port = local_control_port
        self._outbound = outbound
        self._peer_id = remote_peer_id
        self._peer_nick = ""
        self._state = ConnState.CONNECTING
        self._bytes_sent = 0
        self._bytes_received = 0
        self._pending_pings: dict[str, float] = {}   # msg_id -> send time
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(PING_INTERVAL_MS)
        self._ping_timer.timeout.connect(self._send_ping)
        self._handshake_timer = QTimer(self)
        self._handshake_timer.setSingleShot(True)
        self._handshake_timer.timeout.connect(self._on_handshake_timeout)

        self._socket.textMessageReceived.connect(self._on_text)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.errorOccurred.connect(self._on_error)

    # ------------------------------------------------------------------
    # public

    @property
    def peer_id(self) -> str:
        return self._peer_id

    @property
    def state(self) -> ConnState:
        return self._state

    @property
    def outbound(self) -> bool:
        return self._outbound

    @property
    def bytes_sent(self) -> int:
        return self._bytes_sent

    @property
    def bytes_received(self) -> int:
        return self._bytes_received

    def start(self) -> None:
        """Called after construction. Sends the hello immediately so both
        sides converge regardless of who connected first."""
        self._set_state(ConnState.HANDSHAKING)
        self._handshake_timer.start(int(HANDSHAKE_TIMEOUT_S * 1000))
        self._send(Message(
            ns=NS_NET, type="hello",
            data={
                "peer_id": self._local_peer_id,
                "nick": self._local_nick,
                "control_port": self._local_control_port,
                "proto": PROTO_VERSION,
            },
        ))

    def send(self, msg: Message) -> None:
        if self._state != ConnState.CONNECTED:
            log.debug("dropping send to %s in state %s", self._peer_id[:8], self._state)
            return
        self._send(msg)

    def close(self, reason: str = "", abort: bool = False) -> None:
        if self._socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            if abort:
                self._socket.abort()
            else:
                self._socket.close()
        self._cleanup(reason or "closed by local")

    # ------------------------------------------------------------------
    # internal

    def _send(self, msg: Message) -> None:
        raw = msg.to_json()
        n = self._socket.sendTextMessage(raw)
        if n <= 0:
            return
        self._bytes_sent += n
        self.bytes_changed.emit(self._peer_id, self._bytes_sent, self._bytes_received)
        self.message_sent.emit(self._peer_id, msg)

    def _set_state(self, state: ConnState) -> None:
        if state == self._state:
            return
        self._state = state
        self.state_changed.emit(state)

    def _on_text(self, raw: str) -> None:
        self._bytes_received += len(raw.encode("utf-8"))
        self.bytes_changed.emit(self._peer_id, self._bytes_sent, self._bytes_received)
        try:
            msg = Message.from_json(raw)
        except Exception:
            log.debug("malformed message from %s, dropping", self._peer_id[:8])
            return
        # _net traffic is handled here directly; everything else gets emitted up.
        if msg.ns == NS_NET:
            self._handle_net(msg)
            return
        if self._state != ConnState.CONNECTED:
            log.debug("dropping pre-handshake message on ns=%s", msg.ns)
            return
        self.message_received.emit(self._peer_id, msg)

    def _handle_net(self, msg: Message) -> None:
        if msg.type == "hello":
            self._handle_hello(msg)
        elif msg.type == "ping":
            # echo back as pong with same id
            self._send(Message(
                ns=NS_NET, type="pong", id=msg.id, data={},
            ))
        elif msg.type == "pong":
            sent_at = self._pending_pings.pop(msg.id, None)
            if sent_at is not None:
                rtt = time.time() - sent_at
                self.rtt_sample.emit(self._peer_id, rtt)
        elif msg.type == "bye":
            self.close(reason=str(msg.data.get("reason") or "bye"))

    def _handle_hello(self, msg: Message) -> None:
        data = msg.data
        peer_id = str(data.get("peer_id") or "")
        if not peer_id:
            log.warning("hello without peer_id, closing")
            self.close("bad hello")
            return
        if peer_id == self._local_peer_id:
            log.info("self-connection detected, closing")
            self.close("self-connection")
            return
        # Reconcile: outbound channels may have a hint already
        if self._peer_id and self._peer_id != peer_id:
            log.warning("peer_id mismatch (expected %s, got %s) — accepting reported id",
                        self._peer_id[:8], peer_id[:8])
        self._peer_id = peer_id
        self._peer_nick = str(data.get("nick") or "peer")
        self._handshake_timer.stop()
        self._set_state(ConnState.CONNECTED)
        # Synthesise PeerInfo for owner
        info = PeerInfo(
            peer_id=peer_id,
            nick=self._peer_nick,
            host=self._socket.peerAddress().toString() or "0.0.0.0",
            control_port=int(data.get("control_port") or 0),
            proto_version=int(data.get("proto") or 0),
        )
        self.handshaked.emit(info)
        self._ping_timer.start()
        # send first ping immediately for a fast initial RTT sample
        self._send_ping()

    def _send_ping(self) -> None:
        if self._state != ConnState.CONNECTED:
            return
        # reap stale pings
        now = time.time()
        for pid, ts in list(self._pending_pings.items()):
            if now - ts > PING_TIMEOUT_S:
                self._pending_pings.pop(pid, None)
        pid = new_msg_id()
        self._pending_pings[pid] = now
        self._send(Message(ns=NS_NET, type="ping", id=pid, data={}))

    def _on_disconnected(self) -> None:
        self._cleanup("peer disconnected")

    def _on_error(self, _err) -> None:
        log.debug("socket error on %s: %s", self._peer_id[:8], self._socket.errorString())

    def _on_handshake_timeout(self) -> None:
        if self._state == ConnState.HANDSHAKING:
            log.info("handshake timeout for %s", self._peer_id[:8] if self._peer_id else "?")
            self.close("handshake timeout")

    def _cleanup(self, reason: str) -> None:
        if self._state == ConnState.DISCONNECTED:
            return
        self._ping_timer.stop()
        self._handshake_timer.stop()
        self._set_state(ConnState.DISCONNECTED)
        self.closed.emit(self._peer_id, reason)


# ============================================================================
# ControlServer — accepts inbound peers
# ============================================================================


class ControlServer(QObject):
    """QWebSocketServer wrapper. Emits incoming_socket(QWebSocket) for the
    NetworkService to wrap in a ControlChannel."""

    incoming_socket = Signal(object)   # QWebSocket
    started_on_port = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server: QWebSocketServer | None = None
        self._port = 0

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> bool:
        srv = QWebSocketServer(
            "SCAFFOLD-control",
            QWebSocketServer.SslMode.NonSecureMode,
            self,
        )
        if not srv.listen(QHostAddress.SpecialAddress.Any, 0):
            log.error("ControlServer listen failed: %s", srv.errorString())
            return False
        self._server = srv
        self._port = srv.serverPort()
        srv.newConnection.connect(self._on_new)
        log.info("ControlServer listening on port %d", self._port)
        self.started_on_port.emit(self._port)
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
            self._port = 0

    def _on_new(self) -> None:
        srv = self._server
        if srv is None:
            return
        while True:
            sock = srv.nextPendingConnection()
            if sock is None:
                return
            self.incoming_socket.emit(sock)
