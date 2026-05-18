from __future__ import annotations

import ipaddress
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import (
    QAbstractSocket,
    QHostAddress,
    QNetworkInterface,
    QUdpSocket,
)

from app.services.network.types import PROTO_VERSION, PeerInfo, PeerKind

log = logging.getLogger(__name__)


MULTICAST_GROUP = "239.10.20.30"
MULTICAST_PORT = 45454
BEACON_INTERVAL_MS = 2000
PEER_TIMEOUT_S = 10.0
PRUNE_INTERVAL_MS = 1000

AUTO = "auto"


class AddrClass(Enum):
    """Address kind for selection priority. Lower value = higher priority."""
    PRIVATE_192 = 1   # 192.168.0.0/16
    PRIVATE_10 = 2    # 10.0.0.0/8
    PRIVATE_172 = 3   # 172.16.0.0/12
    CGNAT = 4         # 100.64.0.0/10  (Tailscale, carrier NAT) — skipped by default
    LINK_LOCAL = 5    # 169.254.0.0/16 — skipped
    LOOPBACK = 6      # 127.0.0.0/8
    OTHER = 7         # public, anything else


_RFC1918_CLASSES = {AddrClass.PRIVATE_192, AddrClass.PRIVATE_10, AddrClass.PRIVATE_172}


def classify(addr: str) -> AddrClass:
    try:
        ip = ipaddress.IPv4Address(addr)
    except (ipaddress.AddressValueError, ValueError):
        return AddrClass.OTHER
    if ip in ipaddress.IPv4Network("192.168.0.0/16"):
        return AddrClass.PRIVATE_192
    if ip in ipaddress.IPv4Network("10.0.0.0/8"):
        return AddrClass.PRIVATE_10
    if ip in ipaddress.IPv4Network("172.16.0.0/12"):
        return AddrClass.PRIVATE_172
    if ip in ipaddress.IPv4Network("100.64.0.0/10"):
        return AddrClass.CGNAT
    if ip in ipaddress.IPv4Network("169.254.0.0/16"):
        return AddrClass.LINK_LOCAL
    if ip.is_loopback:
        return AddrClass.LOOPBACK
    return AddrClass.OTHER


@dataclass
class InterfaceInfo:
    name: str
    addresses: list[str]
    is_up: bool
    is_loopback: bool
    supports_multicast: bool

    def primary_address(self) -> str | None:
        if not self.addresses:
            return None
        # prefer RFC1918-class address inside this interface
        sorted_addrs = sorted(self.addresses, key=lambda a: classify(a).value)
        return sorted_addrs[0]


@dataclass
class DiscoveryTelemetry:
    multicast_group: str = MULTICAST_GROUP
    multicast_port: int = MULTICAST_PORT
    advertised_host: str = ""
    control_port: int = 0
    interface_pref: str = AUTO       # "auto" or specific IPv4 string
    interface_resolved: str = ""     # actual IP we ended up using
    beacons_sent: int = 0
    beacons_received: int = 0
    beacons_received_from_self: int = 0
    last_beacon_sent_at: float = 0.0
    last_beacon_received_at: float = 0.0
    bind_error: str = ""


class DiscoveryAgent(QObject):
    """UDP multicast beacon for SCAFFOLD peer discovery.

    Beacons on a single chosen interface (RFC1918 by default, user-overridable).
    Joins the multicast group only on that interface so we don't leak traffic
    out over VPNs.
    """

    peer_seen = Signal(object)         # PeerInfo
    peer_timeout = Signal(str)         # peer_id

    def __init__(
        self,
        peer_id: str,
        nick: str,
        control_port: int = 0,
        interface_pref: str = AUTO,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.peer_id = peer_id
        self.nick = nick
        self.telemetry = DiscoveryTelemetry(
            control_port=control_port, interface_pref=interface_pref,
        )
        self._control_port = control_port
        self._interface_pref = interface_pref
        self._socket: QUdpSocket | None = None
        self._chosen_iface: QNetworkInterface | None = None
        self._beacon_timer = QTimer(self)
        self._beacon_timer.setInterval(BEACON_INTERVAL_MS)
        self._beacon_timer.timeout.connect(self._send_beacon)
        self._prune_timer = QTimer(self)
        self._prune_timer.setInterval(PRUNE_INTERVAL_MS)
        self._prune_timer.timeout.connect(self._prune_stale)
        self._known: dict[str, float] = {}

    # ------------------------------------------------------------------
    # lifecycle

    def start(self) -> bool:
        chosen_iface, chosen_addr = self._resolve_interface()
        if chosen_addr is None:
            err = "No suitable interface found (no RFC1918 address available)"
            log.error(err)
            self.telemetry.bind_error = err
            self.telemetry.advertised_host = "127.0.0.1"
            self.telemetry.interface_resolved = "127.0.0.1"
            return False

        sock = QUdpSocket(self)
        bind_flags = (
            QUdpSocket.BindFlag.ShareAddress
            | QUdpSocket.BindFlag.ReuseAddressHint
        )
        # Bind to AnyIPv4 so any interface can receive; outbound is scoped via
        # MulticastInterfaceOption below.
        if not sock.bind(QHostAddress.SpecialAddress.AnyIPv4, MULTICAST_PORT, bind_flags):
            err = sock.errorString()
            log.error("DiscoveryAgent bind failed: %s", err)
            self.telemetry.bind_error = err
            return False

        group = QHostAddress(MULTICAST_GROUP)
        joined = False
        if chosen_iface is not None:
            joined = sock.joinMulticastGroup(group, chosen_iface)
        # Also join on loopback so two instances on this PC see each other
        # regardless of which physical interface is chosen — but skip if
        # the user explicitly chose loopback (already joined above).
        chosen_is_loopback = (
            chosen_iface is not None
            and bool(chosen_iface.flags() & QNetworkInterface.InterfaceFlag.IsLoopBack)
        )
        if not chosen_is_loopback:
            for iface in QNetworkInterface.allInterfaces():
                if iface.flags() & QNetworkInterface.InterfaceFlag.IsLoopBack:
                    sock.joinMulticastGroup(group, iface)
                    break
        if not joined and chosen_iface is None:
            sock.joinMulticastGroup(group)

        # Scope outbound multicast to the chosen interface (or loopback if 127.x).
        if chosen_iface is not None:
            sock.setMulticastInterface(chosen_iface)

        sock.setSocketOption(QAbstractSocket.SocketOption.MulticastLoopbackOption, 1)
        sock.setSocketOption(QAbstractSocket.SocketOption.MulticastTtlOption, 1)
        sock.readyRead.connect(self._on_ready_read)

        self._socket = sock
        self._chosen_iface = chosen_iface
        self.telemetry.advertised_host = chosen_addr
        self.telemetry.interface_resolved = chosen_addr
        self.telemetry.bind_error = ""
        log.info(
            "DiscoveryAgent listening on %s:%d, advertised=%s (iface=%s), control_port=%d",
            MULTICAST_GROUP, MULTICAST_PORT,
            chosen_addr,
            chosen_iface.humanReadableName() if chosen_iface else "default",
            self._control_port,
        )

        self._beacon_timer.start()
        self._prune_timer.start()
        self._send_beacon()
        return True

    def stop(self) -> None:
        self._beacon_timer.stop()
        self._prune_timer.stop()
        if self._socket is not None:
            try:
                self._socket.leaveMulticastGroup(QHostAddress(MULTICAST_GROUP))
            except Exception:
                pass
            self._socket.close()
            self._socket = None
            self._chosen_iface = None

    def restart(self) -> bool:
        """Stop + start. Used when interface preference changes."""
        self.stop()
        return self.start()

    # ------------------------------------------------------------------
    # public API

    def set_control_port(self, port: int) -> None:
        self._control_port = port
        self.telemetry.control_port = port

    def set_nick(self, nick: str) -> None:
        self.nick = nick

    def set_interface_pref(self, pref: str) -> None:
        """Set 'auto' or a specific IPv4 address. Caller should restart()."""
        self._interface_pref = pref or AUTO
        self.telemetry.interface_pref = self._interface_pref

    def force_beacon(self) -> None:
        self._send_beacon()

    def network_interfaces(self) -> list[InterfaceInfo]:
        out: list[InterfaceInfo] = []
        for iface in QNetworkInterface.allInterfaces():
            flags = iface.flags()
            addrs = [
                e.ip().toString()
                for e in iface.addressEntries()
                if e.ip().protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol
            ]
            out.append(InterfaceInfo(
                name=iface.humanReadableName(),
                addresses=addrs,
                is_up=bool(flags & QNetworkInterface.InterfaceFlag.IsUp),
                is_loopback=bool(flags & QNetworkInterface.InterfaceFlag.IsLoopBack),
                supports_multicast=bool(flags & QNetworkInterface.InterfaceFlag.CanMulticast),
            ))
        return out

    def candidate_addresses(self, strict: bool = True) -> list[tuple[str, str, AddrClass]]:
        """Return [(ip, iface_name, addr_class)] for selection UIs.

        strict=True (default): only RFC1918, no loopback.
        strict=False: include loopback, CGNAT, public — but still skip
        link-local and non-multicast interfaces.

        Sorted by priority then by name for stable ordering.
        """
        result: list[tuple[str, str, AddrClass]] = []
        for iface in QNetworkInterface.allInterfaces():
            flags = iface.flags()
            if not (flags & QNetworkInterface.InterfaceFlag.IsRunning):
                continue
            is_loopback = bool(flags & QNetworkInterface.InterfaceFlag.IsLoopBack)
            if strict and is_loopback:
                continue
            if not (flags & QNetworkInterface.InterfaceFlag.CanMulticast):
                continue
            for entry in iface.addressEntries():
                ip = entry.ip()
                if ip.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                    continue
                s = ip.toString()
                cls = classify(s)
                if strict and cls not in _RFC1918_CLASSES:
                    continue
                if cls == AddrClass.LINK_LOCAL:
                    continue
                result.append((s, iface.humanReadableName(), cls))
        result.sort(key=lambda t: (t[2].value, t[1]))
        return result

    # ------------------------------------------------------------------
    # internals

    def _resolve_interface(self) -> tuple[QNetworkInterface | None, str | None]:
        """Return (QNetworkInterface, ipv4_string) for the bound interface.

        If pref is a specific IP, look it up. Otherwise auto-pick the
        highest-priority RFC1918 address available.
        """
        pref = self._interface_pref
        candidates = self.candidate_addresses(strict=True)

        if pref != AUTO:
            for iface in QNetworkInterface.allInterfaces():
                for entry in iface.addressEntries():
                    if entry.ip().toString() == pref:
                        return iface, pref
            log.warning(
                "configured interface %s not found, falling back to auto", pref
            )

        if not candidates:
            # No RFC1918 available — fall back to any non-loopback, non-CGNAT, non-link-local
            for iface in QNetworkInterface.allInterfaces():
                flags = iface.flags()
                if flags & QNetworkInterface.InterfaceFlag.IsLoopBack:
                    continue
                if not (flags & QNetworkInterface.InterfaceFlag.IsRunning):
                    continue
                if not (flags & QNetworkInterface.InterfaceFlag.CanMulticast):
                    continue
                for entry in iface.addressEntries():
                    ip = entry.ip()
                    if ip.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                        continue
                    s = ip.toString()
                    cls = classify(s)
                    if cls in (AddrClass.LINK_LOCAL, AddrClass.LOOPBACK):
                        continue
                    return iface, s
            return None, None

        chosen_addr, chosen_name, _ = candidates[0]
        for iface in QNetworkInterface.allInterfaces():
            if iface.humanReadableName() == chosen_name:
                return iface, chosen_addr
        return None, chosen_addr

    def _send_beacon(self) -> None:
        if self._socket is None:
            return
        payload = json.dumps({
            "t": "beacon",
            "peer_id": self.peer_id,
            "nick": self.nick,
            "host": self.telemetry.advertised_host,
            "control_port": self._control_port,
            "proto": PROTO_VERSION,
        }).encode("utf-8")
        n = self._socket.writeDatagram(payload, QHostAddress(MULTICAST_GROUP), MULTICAST_PORT)
        if n < 0:
            log.warning("beacon write failed: %s", self._socket.errorString())
            return
        self.telemetry.beacons_sent += 1
        self.telemetry.last_beacon_sent_at = time.time()

    def _on_ready_read(self) -> None:
        sock = self._socket
        if sock is None:
            return
        while sock.hasPendingDatagrams():
            dgram = sock.receiveDatagram()
            data = bytes(dgram.data())
            self.telemetry.beacons_received += 1
            self.telemetry.last_beacon_received_at = time.time()
            try:
                msg = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                log.debug("dropped malformed beacon from %s", dgram.senderAddress().toString())
                continue
            if msg.get("t") != "beacon":
                continue
            peer_id = msg.get("peer_id")
            if not peer_id:
                continue
            if peer_id == self.peer_id:
                self.telemetry.beacons_received_from_self += 1
                continue

            sender_host = dgram.senderAddress().toString()
            if sender_host.startswith("::ffff:"):
                sender_host = sender_host[7:]
            advertised = msg.get("host") or sender_host
            host = sender_host if sender_host and sender_host != "0.0.0.0" else advertised

            kind = PeerKind.LOOPBACK if host in ("127.0.0.1", "::1") else PeerKind.LAN

            peer = PeerInfo(
                peer_id=peer_id,
                nick=str(msg.get("nick") or "peer"),
                host=host,
                control_port=int(msg.get("control_port") or 0),
                proto_version=int(msg.get("proto") or 0),
                kind=kind,
            )
            self._known[peer_id] = time.time()
            self.peer_seen.emit(peer)

    def _prune_stale(self) -> None:
        now = time.time()
        dead = [pid for pid, ts in self._known.items() if now - ts > PEER_TIMEOUT_S]
        for pid in dead:
            del self._known[pid]
            self.peer_timeout.emit(pid)


def generate_peer_id() -> str:
    return uuid.uuid4().hex
