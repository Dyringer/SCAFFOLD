from __future__ import annotations

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


PROTO_VERSION = 1

# Reserved namespace for the network layer itself.
NS_NET = "_net"


class PeerKind(str, Enum):
    LAN = "lan"
    LOOPBACK = "loopback"
    MANUAL = "manual"


class ConnState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class PeerInfo:
    peer_id: str
    nick: str
    host: str
    control_port: int
    proto_version: int = PROTO_VERSION
    kind: PeerKind = PeerKind.LAN
    last_seen: float = field(default_factory=time.time)
    rtt_history: deque[float] = field(default_factory=lambda: deque(maxlen=60))
    bytes_sent: int = 0
    bytes_received: int = 0
    conn_state: ConnState = ConnState.DISCONNECTED

    @property
    def address(self) -> str:
        return f"{self.host}:{self.control_port}"

    @property
    def age(self) -> float:
        return time.time() - self.last_seen

    @property
    def rtt_avg(self) -> float | None:
        if not self.rtt_history:
            return None
        return sum(self.rtt_history) / len(self.rtt_history)

    @property
    def rtt_last(self) -> float | None:
        if not self.rtt_history:
            return None
        return self.rtt_history[-1]


@dataclass
class Message:
    """Wire-format message. Encoded as length-prefixed JSON over WS text frame.

    Fields:
        ns:   namespace (e.g. "chat", "_net", "game.asteroids")
        type: message type within namespace
        id:   optional correlation id for request/response
        data: namespace-specific payload (must be JSON-serializable)
    """
    ns: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def to_json(self) -> str:
        d: dict[str, Any] = {"ns": self.ns, "type": self.type, "data": self.data}
        if self.id:
            d["id"] = self.id
        return json.dumps(d, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "Message":
        d = json.loads(raw)
        return cls(
            ns=str(d.get("ns") or ""),
            type=str(d.get("type") or ""),
            data=d.get("data") or {},
            id=str(d.get("id") or ""),
        )


def new_msg_id() -> str:
    return uuid.uuid4().hex[:12]
