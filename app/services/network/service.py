from __future__ import annotations

import logging
import socket
from typing import Callable

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebSockets import QWebSocket

from app.core.settings_store import settings_store
from app.services.network.control import (
    ControlChannel, ControlServer, MessageRouter, NamespaceHandler,
)
from app.services.network.discovery import AUTO, DiscoveryAgent, generate_peer_id
from app.services.network.presence import PresenceTable
from app.services.network.types import (
    ConnState, Message, NS_NET, PeerInfo, PeerKind,
)

log = logging.getLogger(__name__)


class NetworkService(QObject):
    """Facade over discovery + presence + control channel.

    Public surface:
      start() / stop()                       — lifecycle
      send(peer_id, msg)                     — unicast to one peer
      broadcast(msg, exclude=...)            — send to all CONNECTED peers
      register_namespace(ns, handler)        — subscribe to inbound messages
      connect_manual(host, port)             — bypass discovery
      peers() / presence                     — live peer list
      message_received / message_sent        — signals tapping all traffic
    """

    started = Signal()
    stopped = Signal()
    restarted = Signal()
    peer_appeared = Signal(object)   # PeerInfo
    peer_updated = Signal(object)
    peer_left = Signal(str)
    peer_connected = Signal(object)    # PeerInfo — handshake completed
    peer_disconnected = Signal(str)    # peer_id
    message_received = Signal(str, object)  # (peer_id, Message)
    message_sent = Signal(str, object)      # (peer_id, Message)
    rtt_sample = Signal(str, float)         # (peer_id, rtt_seconds)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._peer_id: str = self._load_or_create_peer_id()
        self._nick: str = self._load_or_create_nick()
        self._interface_pref: str = str(settings_store.get("network.interface", AUTO))
        self._presence = PresenceTable(self)
        self._discovery: DiscoveryAgent | None = None
        self._server: ControlServer | None = None
        self._router = MessageRouter()
        self._channels: dict[str, ControlChannel] = {}     # peer_id -> channel (post-handshake)
        self._pending: list[ControlChannel] = []            # channels in HANDSHAKING (no peer_id yet)
        self._running = False
        self._shutting_down = False

        self._presence.peer_appeared.connect(self.peer_appeared)
        self._presence.peer_updated.connect(self.peer_updated)
        self._presence.peer_left.connect(self.peer_left)
        # opportunistic dial when a peer beacon arrives
        self._presence.peer_appeared.connect(self._maybe_dial_peer)
        self._presence.peer_updated.connect(self._maybe_dial_peer)

        settings_store.changed.connect(self._on_setting_changed)

    def _on_setting_changed(self, key: str, value) -> None:
        if key == "network.nick":
            self.set_nick(str(value or ""))
        elif key == "network.interface":
            self.set_interface(str(value or AUTO))

    # ------------------------------------------------------------------
    # identity

    @property
    def peer_id(self) -> str:
        return self._peer_id

    @property
    def nick(self) -> str:
        return self._nick

    def set_nick(self, nick: str) -> None:
        nick = (nick or "").strip() or self._default_nick()
        if nick == self._nick:
            return
        self._nick = nick
        settings_store.set("network.nick", nick)
        if self._discovery is not None:
            self._discovery.set_nick(nick)
            self._discovery.force_beacon()

    # ------------------------------------------------------------------
    # interface selection

    @property
    def interface_pref(self) -> str:
        return self._interface_pref

    def set_interface(self, pref: str) -> None:
        pref = (pref or AUTO).strip() or AUTO
        if pref == self._interface_pref and self._running:
            return
        self._interface_pref = pref
        settings_store.set("network.interface", pref)
        if self._discovery is not None:
            # tear down all channels — old peers may be unreachable on new iface
            for ch in list(self._channels.values()):
                ch.close("interface switched")
            for ch in list(self._pending):
                ch.close("interface switched")
            self._channels.clear()
            self._pending.clear()
            for peer_id in [p.peer_id for p in self._presence.all()]:
                self._presence.remove(peer_id)
            self._discovery.set_interface_pref(pref)
            self._discovery.restart()
            self.restarted.emit()

    def _load_or_create_peer_id(self) -> str:
        pid = settings_store.get("network.peer_id")
        if pid:
            return str(pid)
        pid = generate_peer_id()
        settings_store.set("network.peer_id", pid)
        return pid

    def _load_or_create_nick(self) -> str:
        nick = settings_store.get("network.nick")
        if nick:
            return str(nick)
        nick = self._default_nick()
        settings_store.set("network.nick", nick)
        return nick

    @staticmethod
    def _default_nick() -> str:
        try:
            return socket.gethostname() or "scaffold-peer"
        except Exception:
            return "scaffold-peer"

    # ------------------------------------------------------------------
    # lifecycle

    def start(self) -> None:
        if self._running:
            return
        # Register built-in echo handler for the benchmark namespace so any
        # peer can run a benchmark against any other peer without the
        # network_tools subapp being open on the receiver.
        self._router.register("_bench", self._handle_bench)
        # 1. Start control server first so we know the port to advertise.
        self._server = ControlServer(self)
        self._server.incoming_socket.connect(self._on_incoming_socket)
        if not self._server.start():
            log.error("NetworkService: control server failed to start")
            self._server = None
            return

        # 2. Start discovery, advertising the control port.
        self._discovery = DiscoveryAgent(
            peer_id=self._peer_id,
            nick=self._nick,
            control_port=self._server.port,
            interface_pref=self._interface_pref,
            parent=self,
        )
        self._discovery.peer_seen.connect(self._presence.on_peer_seen)
        self._discovery.peer_timeout.connect(self._presence.on_peer_timeout)
        if not self._discovery.start():
            log.error("NetworkService: discovery failed to start")
            self._server.stop()
            self._server = None
            self._discovery = None
            return

        self._running = True
        log.info(
            "NetworkService started — peer_id=%s nick=%s control_port=%d",
            self._peer_id[:8], self._nick, self._server.port,
        )
        self.started.emit()

    def stop(self) -> None:
        if not self._running:
            return
        log.info("NetworkService stopping")
        self._shutting_down = True
        # Abort (don't gracefully close) all sockets — we're shutting down
        # and don't want the WS close handshake to delay app exit.
        for ch in list(self._channels.values()):
            ch.close("service stopping", abort=True)
        for ch in list(self._pending):
            ch.close("service stopping", abort=True)
        self._channels.clear()
        self._pending.clear()
        if self._discovery is not None:
            self._discovery.stop()
            self._discovery = None
        if self._server is not None:
            self._server.stop()
            self._server = None
        self._running = False
        log.info("NetworkService stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # control channel: connection management

    def _on_incoming_socket(self, sock: QWebSocket) -> None:
        ch = self._wrap_socket(sock, outbound=False)
        self._pending.append(ch)
        ch.start()

    def _maybe_dial_peer(self, peer: PeerInfo) -> None:
        if peer.peer_id == self._peer_id:
            return
        if peer.control_port <= 0:
            return
        if peer.peer_id in self._channels:
            return
        # tie-break: only the peer with the lower id dials out.
        if self._peer_id >= peer.peer_id:
            return
        self._dial(peer.host, peer.control_port, expected_peer_id=peer.peer_id)

    def _dial(self, host: str, port: int, expected_peer_id: str = "") -> ControlChannel:
        sock = QWebSocket()
        url = QUrl()
        url.setScheme("ws")
        url.setHost(host)
        url.setPort(port)
        ch = self._wrap_socket(
            sock, outbound=True, remote_peer_id=expected_peer_id,
        )
        self._pending.append(ch)
        # send hello as soon as the WS handshake completes
        sock.connected.connect(ch.start)
        sock.open(url)
        return ch

    def _wrap_socket(
        self, sock: QWebSocket, outbound: bool, remote_peer_id: str = "",
    ) -> ControlChannel:
        port = self._server.port if self._server else 0
        ch = ControlChannel(
            socket=sock,
            local_peer_id=self._peer_id,
            local_nick=self._nick,
            local_control_port=port,
            outbound=outbound,
            remote_peer_id=remote_peer_id,
            parent=self,
        )
        ch.handshaked.connect(self._on_channel_handshaked)
        ch.closed.connect(self._on_channel_closed)
        ch.message_received.connect(self._on_message_received)
        ch.message_sent.connect(self._on_message_sent)
        ch.rtt_sample.connect(self._on_rtt_sample)
        ch.bytes_changed.connect(self._on_bytes_changed)
        return ch

    def _on_channel_handshaked(self, info: PeerInfo) -> None:
        ch = self.sender()
        if not isinstance(ch, ControlChannel):
            return
        peer_id = info.peer_id
        # Dual-connection collision: if we already have a channel to this
        # peer, keep the older one and drop this. (The tie-break should
        # have prevented this; this is a safety net.)
        if peer_id in self._channels:
            log.info("dropping duplicate channel to %s", peer_id[:8])
            ch.close("duplicate")
            return
        if ch in self._pending:
            self._pending.remove(ch)
        self._channels[peer_id] = ch
        # Update presence with the data from hello (more authoritative than beacon).
        is_manual = bool(ch.property("manual"))
        if is_manual:
            info.kind = PeerKind.MANUAL
        existing = self._presence.get(peer_id)
        if existing is None:
            self._presence.on_peer_seen(info)
            existing = self._presence.get(peer_id)
        if existing is not None:
            existing.nick = info.nick
            existing.control_port = info.control_port or existing.control_port
            existing.proto_version = info.proto_version or existing.proto_version
            existing.conn_state = ConnState.CONNECTED
            if is_manual:
                existing.kind = PeerKind.MANUAL
        self.peer_connected.emit(existing or info)
        log.info("connected to %s (%s)", info.nick, peer_id[:8])

    def _on_channel_closed(self, peer_id: str, reason: str) -> None:
        ch = self.sender()
        if isinstance(ch, ControlChannel):
            if ch in self._pending:
                self._pending.remove(ch)
            if peer_id and self._channels.get(peer_id) is ch:
                del self._channels[peer_id]
                p = self._presence.get(peer_id)
                if p is not None:
                    p.conn_state = ConnState.DISCONNECTED
                self.peer_disconnected.emit(peer_id)
                log.info("disconnected from %s (%s)", peer_id[:8], reason)

    def _on_message_received(self, peer_id: str, msg: Message) -> None:
        self.message_received.emit(peer_id, msg)
        self._router.dispatch(peer_id, msg)

    def _handle_bench(self, peer_id: str, msg: Message) -> None:
        """Default receiver-side handler for the _bench namespace."""
        if msg.type == "ping":
            self.send(peer_id, Message(
                ns="_bench", type="pong", id=msg.id, data=msg.data,
            ))
        elif msg.type == "tp_data":
            if msg.data.get("final"):
                self.send(peer_id, Message(
                    ns="_bench", type="tp_ack", id=msg.id, data={},
                ))

    def _on_message_sent(self, peer_id: str, msg: Message) -> None:
        if peer_id:
            self.message_sent.emit(peer_id, msg)

    def _on_rtt_sample(self, peer_id: str, rtt: float) -> None:
        p = self._presence.get(peer_id)
        if p is not None:
            p.rtt_history.append(rtt)
        self.rtt_sample.emit(peer_id, rtt)

    def _on_bytes_changed(self, peer_id: str, sent: int, received: int) -> None:
        p = self._presence.get(peer_id)
        if p is not None:
            p.bytes_sent = sent
            p.bytes_received = received

    # ------------------------------------------------------------------
    # public messaging API

    def send(self, peer_id: str, msg: Message) -> bool:
        ch = self._channels.get(peer_id)
        if ch is None:
            return False
        ch.send(msg)
        return True

    def broadcast(self, msg: Message, exclude: set[str] | None = None) -> int:
        exclude = exclude or set()
        n = 0
        for pid, ch in self._channels.items():
            if pid in exclude:
                continue
            ch.send(msg)
            n += 1
        return n

    def register_namespace(self, namespace: str, handler: NamespaceHandler) -> None:
        self._router.register(namespace, handler)

    def unregister_namespace(self, namespace: str) -> None:
        self._router.unregister(namespace)

    def registered_namespaces(self) -> list[str]:
        return self._router.namespaces()

    def connect_manual(self, host: str, port: int) -> bool:
        """Open an outbound channel bypassing discovery. Peer joins presence
        as a MANUAL peer after handshake."""
        if not host or port <= 0:
            return False
        ch = self._dial(host, port, expected_peer_id="")
        # Tag this channel as manual so we can mark presence accordingly
        # once the handshake completes.
        ch.setProperty("manual", True)
        return True

    def disconnect_peer(self, peer_id: str, reason: str = "manual") -> bool:
        ch = self._channels.get(peer_id)
        if ch is None:
            return False
        ch.close(reason)
        return True

    def reconnect_peer(self, peer_id: str) -> bool:
        peer = self._presence.get(peer_id)
        if peer is None or peer.control_port <= 0:
            return False
        self.disconnect_peer(peer_id, "reconnect")
        self._dial(peer.host, peer.control_port, expected_peer_id=peer_id)
        return True

    def is_connected(self, peer_id: str) -> bool:
        return peer_id in self._channels

    # ------------------------------------------------------------------
    # accessors

    @property
    def presence(self) -> PresenceTable:
        return self._presence

    @property
    def discovery(self) -> DiscoveryAgent | None:
        return self._discovery

    @property
    def server(self) -> ControlServer | None:
        return self._server

    def peers(self) -> list[PeerInfo]:
        return self._presence.all()

    def force_beacon(self) -> None:
        if self._discovery is not None:
            self._discovery.force_beacon()


network_service = NetworkService()
