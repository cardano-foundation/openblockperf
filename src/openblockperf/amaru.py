"""Amaru (Rust node) INFO log → peer session actions.

v0: peer open / local_use temperature / close / node generation only.
Blocksamples are out of scope until Amaru logs header/fetch/adopt-with-peer.

Match key is ``fields.message``. See docs/amaru-log-parsing.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from ipaddress import ip_address
from typing import Any

from openblockperf.logging import logger
from openblockperf.models.peer import CloseReason, PeerState
from openblockperf.peer_tracker import PeerReport, PeerTracker

# fields.message values we act on for peer sessions
MSG_HANDSHAKE = "manager.peer.handshake_completed"
MSG_LOCAL_USE_APPLIED = "manager.peer.local_use_applied"
MSG_SET_LOCAL_USE = "manager.peer.set_local_use"
MSG_CONNECT = "manager.peer.connect"
MSG_CONNECTED = "manager.peer.connected"
MSG_DIED_HANDLED = "manager.peer.connection_died_handled"
MSG_CHILD_DIED = "connection.child_died"
MSG_DEMOTED = "peer_selection.peer.demoted"
MSG_LISTEN = "manager.listen.started"
MSG_CONNECT_INITIAL = "peer_selection.connect_initial"
# build.version is a useful replay marker but fires ~18s before diffusion;
# do not bump node_generation on it (would double-count with connect_initial).

_PEER_MESSAGES = frozenset(
    {
        MSG_HANDSHAKE,
        MSG_LOCAL_USE_APPLIED,
        MSG_SET_LOCAL_USE,
        MSG_CONNECT,
        MSG_CONNECTED,
        MSG_DIED_HANDLED,
        MSG_CHILD_DIED,
        MSG_DEMOTED,
        MSG_LISTEN,
        MSG_CONNECT_INITIAL,
    }
)


class AmaruActionKind(Enum):
    IGNORE = "ignore"
    NODE_START = "node_start"
    LISTEN = "listen"
    DIAL_HINT = "dial_hint"
    OPEN = "open"
    TEMPERATURE = "temperature"
    CLOSE = "close"


@dataclass(frozen=True)
class AmaruPeerAction:
    """One normalized peer step from an Amaru log line."""

    kind: AmaruActionKind
    at: datetime
    ns: str  # fields.message (audit / last_ns)
    remote_addr: str | None = None
    remote_port: int | None = None
    conn_id: int | None = None
    local_use: str | None = None
    role: str | None = None  # initiator | responder
    child: str | None = None  # Mux | Handshake | ChainSync | ...
    listen_addr: str | None = None
    listen_port: int | None = None
    we_dialed_hint: bool = False
    demoted: bool = False


def is_amaru_message(message: dict[str, Any]) -> bool:
    """True when the dict looks like Amaru JSON tracing (not cardano-tracer ns)."""
    if "ns" in message:
        return False
    fields = message.get("fields")
    return isinstance(fields, dict) and isinstance(fields.get("message"), str)


def parse_peer_hostport(peer: str) -> tuple[str, int]:
    """Parse ``ip:port`` or ``[ipv6]:port`` into address + port."""
    peer = peer.strip()
    if peer.startswith("["):
        end = peer.rfind("]")
        if end < 0 or end + 1 >= len(peer) or peer[end + 1] != ":":
            raise ValueError(f"Invalid IPv6 peer string: {peer!r}")
        addr = peer[1:end]
        port = int(peer[end + 2 :])
    else:
        if ":" not in peer:
            raise ValueError(f"Invalid peer string (no port): {peer!r}")
        addr, port_s = peer.rsplit(":", 1)
        port = int(port_s)
    ip_address(addr)  # validate
    return addr, port


def _normalize_local_use(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().lower()


def parse_amaru_peer_action(message: dict[str, Any]) -> AmaruPeerAction | None:
    """Parse one Amaru log dict into a peer action, or None if not peer-relevant."""
    if not is_amaru_message(message):
        return None
    fields: dict[str, Any] = message["fields"]
    msg = fields.get("message")
    if msg not in _PEER_MESSAGES:
        return None

    ts = message.get("timestamp")
    if not isinstance(ts, str):
        raise ValueError(f"Amaru line missing timestamp: {msg}")
    at = datetime.fromisoformat(ts.replace("Z", "+00:00"))

    remote_addr = remote_port = None
    peer = fields.get("peer")
    if isinstance(peer, str) and peer:
        try:
            remote_addr, remote_port = parse_peer_hostport(peer)
        except ValueError as e:
            logger.warning("Amaru peer parse failed", message=msg, peer=peer, error=str(e))
            return None

    conn_id = fields.get("conn_id")
    if conn_id is not None:
        try:
            conn_id = int(conn_id)
        except (TypeError, ValueError):
            conn_id = None

    if msg == MSG_CONNECT_INITIAL:
        return AmaruPeerAction(kind=AmaruActionKind.NODE_START, at=at, ns=msg)

    if msg == MSG_LISTEN:
        listen_addr = listen_port = None
        raw = fields.get("listen_addr")
        if isinstance(raw, str) and raw:
            try:
                listen_addr, listen_port = parse_peer_hostport(raw)
            except ValueError as e:
                logger.warning("Amaru listen_addr parse failed", listen_addr=raw, error=str(e))
        return AmaruPeerAction(
            kind=AmaruActionKind.LISTEN,
            at=at,
            ns=msg,
            listen_addr=listen_addr,
            listen_port=listen_port,
        )

    if msg in (MSG_CONNECT, MSG_CONNECTED):
        if remote_addr is None:
            return None
        return AmaruPeerAction(
            kind=AmaruActionKind.DIAL_HINT,
            at=at,
            ns=msg,
            remote_addr=remote_addr,
            remote_port=remote_port,
            conn_id=conn_id,
            we_dialed_hint=True,
        )

    if msg == MSG_HANDSHAKE:
        if remote_addr is None:
            return None
        return AmaruPeerAction(
            kind=AmaruActionKind.OPEN,
            at=at,
            ns=msg,
            remote_addr=remote_addr,
            remote_port=remote_port,
            conn_id=conn_id,
        )

    if msg in (MSG_LOCAL_USE_APPLIED, MSG_SET_LOCAL_USE):
        # Applied is preferred by the bridge; set_local_use is intent-only backup.
        if remote_addr is None:
            return None
        return AmaruPeerAction(
            kind=AmaruActionKind.TEMPERATURE,
            at=at,
            ns=msg,
            remote_addr=remote_addr,
            remote_port=remote_port,
            conn_id=conn_id,
            local_use=_normalize_local_use(fields.get("local_use")),
        )

    if msg == MSG_DEMOTED:
        if remote_addr is None:
            return None
        return AmaruPeerAction(
            kind=AmaruActionKind.TEMPERATURE,
            at=at,
            ns=msg,
            remote_addr=remote_addr,
            remote_port=remote_port,
            conn_id=conn_id,
            local_use="maintenance",
            demoted=True,
        )

    if msg == MSG_DIED_HANDLED:
        if remote_addr is None:
            return None
        role = fields.get("role")
        return AmaruPeerAction(
            kind=AmaruActionKind.CLOSE,
            at=at,
            ns=msg,
            remote_addr=remote_addr,
            remote_port=remote_port,
            conn_id=conn_id,
            role=str(role) if role is not None else None,
            we_dialed_hint=str(role).lower() == "initiator",
        )

    if msg == MSG_CHILD_DIED:
        if remote_addr is None:
            return None
        child = fields.get("child")
        return AmaruPeerAction(
            kind=AmaruActionKind.CLOSE,
            at=at,
            ns=msg,
            remote_addr=remote_addr,
            remote_port=remote_port,
            conn_id=conn_id,
            child=str(child) if child is not None else None,
        )

    return AmaruPeerAction(kind=AmaruActionKind.IGNORE, at=at, ns=str(msg))


@dataclass
class AmaruPeerBridge:
    """Stateful Amaru → PeerTracker adapter (listen addr, dial hints, demotes)."""

    tracker: PeerTracker
    default_local_addr: str = "0.0.0.0"
    default_local_port: int = 3001
    listen_addr: str | None = None
    listen_port: int | None = None
    _dialed: set[str] = field(default_factory=set)
    _demoted: set[str] = field(default_factory=set)
    _seen_conn: set[int] = field(default_factory=set)
    # Prefer died_handled over child_died for the same peer key shortly after.
    _closed_keys: set[str] = field(default_factory=set)

    def _local(self) -> tuple[str, int]:
        addr = self.listen_addr if self.listen_addr is not None else self.default_local_addr
        port = self.listen_port if self.listen_port is not None else self.default_local_port
        return addr, port

    @staticmethod
    def _peer_key(remote_addr: str, remote_port: int) -> str:
        return f"{remote_addr}:{remote_port}"

    def apply_message(self, message: dict[str, Any]) -> list[PeerReport]:
        """Parse and apply one Amaru log line. Empty list if ignored."""
        try:
            action = parse_amaru_peer_action(message)
        except ValueError as e:
            logger.warning("Amaru peer action parse error", error=str(e))
            return []
        if action is None or action.kind == AmaruActionKind.IGNORE:
            return []
        return self.apply_action(action)

    def apply_action(self, action: AmaruPeerAction) -> list[PeerReport]:
        if action.kind == AmaruActionKind.NODE_START:
            return self.tracker.on_network_start(action.at, ns=action.ns)

        if action.kind == AmaruActionKind.LISTEN:
            if action.listen_addr is not None and action.listen_port is not None:
                self.listen_addr = action.listen_addr
                self.listen_port = action.listen_port
            # Same start burst as connect_initial; PeerTracker debounces.
            return self.tracker.on_network_start(action.at, ns=action.ns)

        if action.kind == AmaruActionKind.DIAL_HINT:
            assert action.remote_addr is not None and action.remote_port is not None
            self._dialed.add(self._peer_key(action.remote_addr, action.remote_port))
            if action.conn_id is not None:
                self._seen_conn.add(action.conn_id)
            return []

        if action.kind == AmaruActionKind.OPEN:
            return self._open(action)

        if action.kind == AmaruActionKind.TEMPERATURE:
            return self._temperature(action)

        if action.kind == AmaruActionKind.CLOSE:
            return self._close(action)

        return []

    def _open(self, action: AmaruPeerAction) -> list[PeerReport]:
        assert action.remote_addr is not None and action.remote_port is not None
        local_addr, local_port = self._local()
        key = self._peer_key(action.remote_addr, action.remote_port)
        we_dialed = key in self._dialed
        if action.conn_id is not None:
            self._seen_conn.add(action.conn_id)
        self._closed_keys.discard(key)
        reports = self.tracker.open_handshake(
            local_addr=local_addr,
            local_port=local_port,
            remote_addr=action.remote_addr,
            remote_port=action.remote_port,
            n2n_version=None,
            diffusion_mode=None,
            peer_sharing=None,
            peras_support=None,
            at=action.at,
            ns=action.ns,
        )
        if we_dialed:
            session = self.tracker._find_open(
                local_addr, local_port, action.remote_addr, action.remote_port
            )
            if session is not None:
                session.we_dialed = True
        return reports

    def _temperature(self, action: AmaruPeerAction) -> list[PeerReport]:
        assert action.remote_addr is not None and action.remote_port is not None
        # Prefer local_use_applied; ignore set_local_use (intent) to avoid doubles.
        if action.ns == MSG_SET_LOCAL_USE:
            return []

        local_addr, local_port = self._local()
        key = self._peer_key(action.remote_addr, action.remote_port)
        we_dialed = True if key in self._dialed else None

        if action.demoted or action.local_use == "maintenance":
            self._demoted.add(key)
            return self.tracker.set_outbound_temperature(
                local_addr=local_addr,
                local_port=local_port,
                remote_addr=action.remote_addr,
                remote_port=action.remote_port,
                state=PeerState.WARM,
                at=action.at,
                ns=action.ns,
                we_dialed=we_dialed,
            )

        if action.local_use == "diffusion":
            return self.tracker.set_outbound_temperature(
                local_addr=local_addr,
                local_port=local_port,
                remote_addr=action.remote_addr,
                remote_port=action.remote_port,
                state=PeerState.HOT,
                at=action.at,
                ns=action.ns,
                we_dialed=we_dialed,
            )

        if action.local_use == "none":
            # Idle after HS: no temperature submit. If we were Hot, demote to Warm.
            session = self.tracker._find_open(
                local_addr, local_port, action.remote_addr, action.remote_port
            )
            if session is not None and session.outbound_temperature == PeerState.HOT:
                return self.tracker.set_outbound_temperature(
                    local_addr=local_addr,
                    local_port=local_port,
                    remote_addr=action.remote_addr,
                    remote_port=action.remote_port,
                    state=PeerState.WARM,
                    at=action.at,
                    ns=action.ns,
                    we_dialed=we_dialed,
                )
            if session is not None:
                self.tracker.touch_signal(action.remote_addr, action.at)
            return []

        return []

    def _close(self, action: AmaruPeerAction) -> list[PeerReport]:
        assert action.remote_addr is not None and action.remote_port is not None
        local_addr, local_port = self._local()
        key = self._peer_key(action.remote_addr, action.remote_port)

        # Handshake child died without a prior open → failed attempt, skip.
        if action.ns == MSG_CHILD_DIED and action.child == "Handshake":
            session = self.tracker._find_open(
                local_addr, local_port, action.remote_addr, action.remote_port
            )
            if session is None:
                return []

        # child_died often precedes died_handled; skip duplicate close.
        if key in self._closed_keys:
            return []

        session = self.tracker._find_open(
            local_addr, local_port, action.remote_addr, action.remote_port
        )
        if session is None:
            return []

        we_dialed = None
        if action.we_dialed_hint or key in self._dialed:
            we_dialed = True
        elif action.role and action.role.lower() == "responder":
            we_dialed = False

        if key in self._demoted:
            reason = CloseReason.DEMOTED_COLD
        else:
            reason = CloseReason.IG_MUX_ERROR

        reports = self.tracker.close_connection(
            local_addr=local_addr,
            local_port=local_port,
            remote_addr=action.remote_addr,
            remote_port=action.remote_port,
            at=action.at,
            ns=action.ns,
            reason=reason,
            we_dialed=we_dialed,
        )
        if reports:
            self._closed_keys.add(key)
            self._demoted.discard(key)
            self._dialed.discard(key)
        return reports
