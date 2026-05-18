from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, Signal

from app.services.network import network_service
from app.services.network.types import Message


CHAT_NS = "chat"
EVERYONE = "everyone"   # virtual thread id for the group room


class Direction(str, Enum):
    INCOMING = "in"
    OUTGOING = "out"
    SYSTEM = "sys"      # join/leave/disconnect notices


@dataclass
class ChatLine:
    direction: Direction
    ts: float
    sender_id: str        # peer_id of sender (empty for outgoing system lines)
    sender_nick: str
    text: str
    thread_id: str        # "everyone" or a peer_id

    @property
    def time_str(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.ts))


class ChatModel(QObject):
    """Holds all chat threads and routes inbound chat messages to them.

    Threads are keyed by:
      "everyone" — the group broadcast room
      <peer_id>  — direct messages with that peer

    Outgoing messages are recorded immediately. Incoming messages arrive
    via the registered handler on the chat namespace.
    """

    line_added = Signal(str, object)        # (thread_id, ChatLine)
    thread_changed = Signal(str)            # thread_id — for re-rendering thread list

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._threads: dict[str, list[ChatLine]] = defaultdict(list)
        self._unread_per_thread: dict[str, int] = defaultdict(int)
        # Cached nick per thread so it survives the peer's disconnect-from-presence.
        self._thread_nicks: dict[str, str] = {EVERYONE: "Everyone"}
        # Make sure 'everyone' thread always exists
        self._threads[EVERYONE] = []
        network_service.register_namespace(CHAT_NS, self._on_inbound)
        network_service.peer_appeared.connect(self._on_peer_appeared)
        network_service.peer_updated.connect(self._on_peer_appeared)
        network_service.peer_connected.connect(self._on_peer_connected)
        network_service.peer_disconnected.connect(self._on_peer_disconnected)
        # Seed threads for any peers already known when we start up.
        for peer in network_service.peers():
            self._ensure_thread(peer.peer_id, peer.nick)

    def _on_peer_appeared(self, peer) -> None:
        # Seed a thread the moment a peer appears in presence, even before
        # the control-channel handshake completes.
        self._ensure_thread(peer.peer_id, peer.nick)

    # ------------------------------------------------------------------
    # public reads

    def thread_ids(self) -> list[str]:
        # everyone first, then peer threads sorted by most-recent activity
        # (or stable by nick for empty threads).
        peer_ids = [tid for tid in self._threads if tid != EVERYONE]
        peer_ids.sort(
            key=lambda tid: (
                self._threads[tid][-1].ts if self._threads[tid] else 0,
                self._thread_nicks.get(tid, ""),
            ),
            reverse=True,
        )
        return [EVERYONE] + peer_ids

    def lines(self, thread_id: str) -> list[ChatLine]:
        return list(self._threads.get(thread_id, []))

    def unread(self, thread_id: str) -> int:
        return self._unread_per_thread.get(thread_id, 0)

    def total_unread(self) -> int:
        return sum(self._unread_per_thread.values())

    def thread_display_name(self, thread_id: str) -> str:
        if thread_id == EVERYONE:
            return "Everyone"
        # Prefer live presence (handles nick changes), fall back to cache.
        peer = network_service.presence.get(thread_id)
        if peer is not None:
            self._thread_nicks[thread_id] = peer.nick
            return peer.nick
        return self._thread_nicks.get(thread_id, thread_id[:8])

    def has_thread(self, thread_id: str) -> bool:
        return thread_id in self._threads

    def ensure_dm_thread(self, peer_id: str) -> str:
        """Create a DM thread for this peer if it doesn't exist. Returns
        the thread id."""
        peer = network_service.presence.get(peer_id)
        nick = peer.nick if peer is not None else peer_id[:8]
        return self._ensure_thread(peer_id, nick)

    def _ensure_thread(self, thread_id: str, nick: str) -> str:
        if thread_id not in self._threads:
            self._threads[thread_id] = []
            self._thread_nicks[thread_id] = nick
            self.thread_changed.emit(thread_id)
        else:
            # refresh cached nick
            self._thread_nicks[thread_id] = nick
        return thread_id

    # ------------------------------------------------------------------
    # send

    def send_everyone(self, text: str) -> int:
        text = text.strip()
        if not text:
            return 0
        msg = Message(ns=CHAT_NS, type="msg", data={
            "text": text, "to": EVERYONE,
        })
        n = network_service.broadcast(msg)
        line = ChatLine(
            direction=Direction.OUTGOING,
            ts=time.time(),
            sender_id=network_service.peer_id,
            sender_nick=network_service.nick,
            text=text,
            thread_id=EVERYONE,
        )
        self._append(line)
        return n

    def send_direct(self, peer_id: str, text: str) -> bool:
        text = text.strip()
        if not text or not peer_id:
            return False
        msg = Message(ns=CHAT_NS, type="msg", data={
            "text": text, "to": peer_id,
        })
        ok = network_service.send(peer_id, msg)
        line = ChatLine(
            direction=Direction.OUTGOING,
            ts=time.time(),
            sender_id=network_service.peer_id,
            sender_nick=network_service.nick,
            text=text,
            thread_id=peer_id,
        )
        self._append(line)
        if not ok:
            self._append(ChatLine(
                direction=Direction.SYSTEM,
                ts=time.time(),
                sender_id="",
                sender_nick="",
                text="(not delivered — peer offline)",
                thread_id=peer_id,
            ))
        return ok

    # ------------------------------------------------------------------
    # inbound

    def _on_inbound(self, peer_id: str, msg: Message) -> None:
        if msg.type != "msg":
            return
        data = msg.data or {}
        text = str(data.get("text") or "").strip()
        if not text:
            return
        to = str(data.get("to") or "")
        thread_id = EVERYONE if to == EVERYONE else peer_id

        peer = network_service.presence.get(peer_id)
        sender_nick = peer.nick if peer is not None else peer_id[:8]

        line = ChatLine(
            direction=Direction.INCOMING,
            ts=time.time(),
            sender_id=peer_id,
            sender_nick=sender_nick,
            text=text,
            thread_id=thread_id,
        )
        self._append(line)
        self._unread_per_thread[thread_id] += 1
        self.thread_changed.emit(thread_id)

    def mark_read(self, thread_id: str) -> None:
        if self._unread_per_thread.get(thread_id):
            self._unread_per_thread[thread_id] = 0
            self.thread_changed.emit(thread_id)

    # ------------------------------------------------------------------
    # peer lifecycle → system lines

    def _on_peer_connected(self, peer) -> None:
        # Announce in 'everyone'.
        self._append(ChatLine(
            direction=Direction.SYSTEM, ts=time.time(),
            sender_id="", sender_nick="",
            text=f"— {peer.nick} connected —",
            thread_id=EVERYONE,
        ))
        # Make sure a DM thread exists so the user can click it without
        # having to send the first message blind.
        existed = peer.peer_id in self._threads
        self._ensure_thread(peer.peer_id, peer.nick)
        if existed:
            self._append(ChatLine(
                direction=Direction.SYSTEM, ts=time.time(),
                sender_id="", sender_nick="",
                text="— peer reconnected —",
                thread_id=peer.peer_id,
            ))

    def _on_peer_disconnected(self, peer_id: str) -> None:
        peer = network_service.presence.get(peer_id)
        nick = peer.nick if peer is not None else peer_id[:8]
        self._append(ChatLine(
            direction=Direction.SYSTEM, ts=time.time(),
            sender_id="", sender_nick="",
            text=f"— {nick} disconnected —",
            thread_id=EVERYONE,
        ))
        if peer_id in self._threads:
            self._append(ChatLine(
                direction=Direction.SYSTEM, ts=time.time(),
                sender_id="", sender_nick="",
                text="— peer disconnected —",
                thread_id=peer_id,
            ))

    # ------------------------------------------------------------------

    def _append(self, line: ChatLine) -> None:
        self._threads[line.thread_id].append(line)
        self.line_added.emit(line.thread_id, line)
        self.thread_changed.emit(line.thread_id)
