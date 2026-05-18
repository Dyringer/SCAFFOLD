from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, Signal

from app.services.network.types import PeerInfo, PeerKind

log = logging.getLogger(__name__)


class PresenceTable(QObject):
    """Canonical online-peer list.

    Receives raw sightings from DiscoveryAgent (and later from manual
    connect / control channel) and exposes a deduplicated peer view
    plus appeared/updated/left signals.
    """

    peer_appeared = Signal(object)   # PeerInfo
    peer_updated = Signal(object)    # PeerInfo
    peer_left = Signal(str)          # peer_id

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._peers: dict[str, PeerInfo] = {}

    # ------------------------------------------------------------------
    # queries

    def all(self) -> list[PeerInfo]:
        return list(self._peers.values())

    def get(self, peer_id: str) -> PeerInfo | None:
        return self._peers.get(peer_id)

    def __len__(self) -> int:
        return len(self._peers)

    # ------------------------------------------------------------------
    # mutations

    def on_peer_seen(self, peer: PeerInfo) -> None:
        existing = self._peers.get(peer.peer_id)
        if existing is None:
            self._peers[peer.peer_id] = peer
            log.info("peer appeared: %s (%s @ %s)", peer.nick, peer.peer_id[:8], peer.address)
            self.peer_appeared.emit(peer)
            return

        changed = (
            existing.nick != peer.nick
            or existing.host != peer.host
            or existing.control_port != peer.control_port
            or existing.proto_version != peer.proto_version
            or existing.kind != peer.kind
        )
        existing.nick = peer.nick
        existing.host = peer.host
        existing.control_port = peer.control_port
        existing.proto_version = peer.proto_version
        # Don't downgrade kind: a peer first seen as MANUAL stays MANUAL
        # even if its beacon later arrives.
        if existing.kind != PeerKind.MANUAL:
            existing.kind = peer.kind
        existing.last_seen = time.time()
        if changed:
            self.peer_updated.emit(existing)

    def on_peer_timeout(self, peer_id: str) -> None:
        peer = self._peers.pop(peer_id, None)
        if peer is None:
            return
        if peer.kind == PeerKind.MANUAL:
            # manual peers are sticky — re-insert so the test subapp keeps them
            self._peers[peer_id] = peer
            return
        log.info("peer left: %s (%s)", peer.nick, peer.peer_id[:8])
        self.peer_left.emit(peer_id)

    def remove(self, peer_id: str) -> None:
        peer = self._peers.pop(peer_id, None)
        if peer is not None:
            self.peer_left.emit(peer_id)
