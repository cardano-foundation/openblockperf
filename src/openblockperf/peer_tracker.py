"""Connection-session tracking from Net.* logs.

A session is one TCP connectionId (local+remote addr/port) in one node
generation (cardano-node / diffusion start). HandshakeSuccess opens it.
IG Remote, PeerSelection StatusChanged, and Selection Promote/Demote *Done
fill temperatures. ChainSync/BlockFetch client lines mark we-dialed outbound
Hot. MuxErrored / demote / CoolingToCold / node restart close it.

Useful is a local-list flag (Hot, or Warm held for stable_seconds). Backend
always gets open/close so short handshakes still count as signs of life.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from openblockperf.logging import logger
from openblockperf.models.events import (
    PEER_SELECTION_DEMOTE_WARM_NAMESPACES,
    PEER_SELECTION_DONE_NAMESPACES,
    PeerEvent,
    PeerEventChangeType,
)
from openblockperf.models.peer import (
    CloseReason,
    EventRole,
    Peer,
    PeerDirection,
    PeerState,
    is_ephemeral_port,
)

_ACTIVE = {PeerState.WARM, PeerState.HOT}
_GENERATION_DEBOUNCE = timedelta(seconds=2)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def connection_key(local_addr: str, local_port: int, remote_addr: str, remote_port: int) -> str:
    return f"{local_addr}|{local_port}|{remote_addr}|{remote_port}"


def submit_port(port: int) -> int:
    """Listen port for backend identity; ephemeral becomes 0."""
    return 0 if is_ephemeral_port(port) else port


@dataclass
class PeerSession:
    """One remote TCP session in the current (or just-closed) node generation."""

    node_generation: int
    session_id: str
    local_addr: str
    local_port: int
    remote_addr: str
    remote_port: int
    opened_at: datetime
    last_ns: str | None = None
    we_dialed: bool | None = None
    n2n_version: int | None = None
    diffusion_mode: str | None = None
    peer_sharing: str | None = None
    peras_support: str | None = None
    ig_temperature: PeerState = PeerState.UNCONNECTED
    outbound_temperature: PeerState = PeerState.UNCONNECTED
    useful: bool = False
    warm_since: datetime | None = None
    last_signal: datetime | None = None
    closed_at: datetime | None = None
    close_reason: CloseReason | None = None
    opened_submitted: bool = False
    ig_submitted: PeerState | None = None
    out_submitted: PeerState | None = None

    @property
    def conn_key(self) -> str:
        return connection_key(
            self.local_addr, self.local_port, self.remote_addr, self.remote_port
        )

    @property
    def open(self) -> bool:
        return self.closed_at is None

    def as_peer(self) -> Peer:
        return Peer(
            ns=self.last_ns,
            local_addr=self.local_addr,
            local_port=self.local_port,
            remote_addr=self.remote_addr,
            remote_port=submit_port(self.remote_port),
            state_inbound=self.ig_temperature,
            state_outbound=self.outbound_temperature,
            n2n_version=self.n2n_version,
            diffusion_mode=self.diffusion_mode,
            peer_sharing=self.peer_sharing,
            peras_support=self.peras_support,
            first_seen=self.opened_at,
            last_signal=self.last_signal or self.opened_at,
            last_updated=self.last_signal or self.opened_at,
        )


@dataclass
class PeerReport:
    """Payload the handler turns into an API submit."""

    peer: Peer
    direction: PeerDirection
    change_type: PeerEventChangeType
    state: str
    at: datetime
    remote_port: int
    event_role: EventRole
    node_generation: int
    session_id: str | None = None
    close_reason: CloseReason | None = None
    we_dialed: bool | None = None


@dataclass
class PeerHandshakeInfo:
    """Latest HandshakeSuccess fields for a remote IP (debug / tests)."""

    remote_addr: str
    remote_port: int
    n2n_version: int | None
    diffusion_mode: str | None
    peer_sharing: str | None
    peras_support: str | None
    at: datetime


@dataclass
class _CloseCounts:
    by_reason: dict[str, int] = field(default_factory=dict)

    def add(self, reason: CloseReason) -> None:
        key = reason.value
        self.by_reason[key] = self.by_reason.get(key, 0) + 1


class PeerTracker:
    """Owns connection sessions and decides what to submit."""

    def __init__(
        self,
        peers: dict[str, Peer],
        *,
        stable_seconds: int = 15,
        signal_ttl_seconds: int = 1800,
        traceroute_enabled: bool = False,
    ):
        self.peers = peers
        self.stable_seconds = max(0, stable_seconds)
        self.signal_ttl_seconds = max(0, signal_ttl_seconds)
        self.traceroute_enabled = traceroute_enabled
        self.node_generation = 0
        self._open: dict[str, PeerSession] = {}
        self._closed: dict[str, PeerSession] = {}
        self._opened_count = 0
        self._close_counts = _CloseCounts()
        self._last_generation_at: datetime | None = None
        self._stopped = False

    def enabled(self) -> bool:
        return True

    def peer_key(self, remote_addr: str) -> str:
        return remote_addr

    def handshake_for(self, remote_addr: str) -> PeerHandshakeInfo | None:
        """Latest handshake on any session for this IP (open preferred)."""
        found: PeerSession | None = None
        for session in self._open.values():
            if session.remote_addr == remote_addr and session.n2n_version is not None:
                if found is None or (session.last_signal or session.opened_at) >= (
                    found.last_signal or found.opened_at
                ):
                    found = session
        if found is None:
            for session in self._closed.values():
                if session.remote_addr == remote_addr and session.n2n_version is not None:
                    if found is None or (session.last_signal or session.opened_at) >= (
                        found.last_signal or found.opened_at
                    ):
                        found = session
        if found is None:
            return None
        return PeerHandshakeInfo(
            remote_addr=found.remote_addr,
            remote_port=submit_port(found.remote_port),
            n2n_version=found.n2n_version,
            diffusion_mode=found.diffusion_mode,
            peer_sharing=found.peer_sharing,
            peras_support=found.peras_support,
            at=found.last_signal or found.opened_at,
        )

    def record_handshake(
        self,
        *,
        remote_addr: str,
        remote_port: int,
        n2n_version: int | None,
        diffusion_mode: str | None,
        peer_sharing: str | None,
        peras_support: str | None,
        at: datetime,
        local_addr: str = "0.0.0.0",
        local_port: int = 0,
        ns: str = "Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess",
    ) -> PeerHandshakeInfo:
        """Open (or enrich) a session from HandshakeSuccess. Returns HS cache view."""
        reports = self.open_handshake(
            local_addr=local_addr,
            local_port=local_port,
            remote_addr=remote_addr,
            remote_port=remote_port,
            n2n_version=n2n_version,
            diffusion_mode=diffusion_mode,
            peer_sharing=peer_sharing,
            peras_support=peras_support,
            at=at,
            ns=ns,
        )
        # Caller that only wanted the cache (legacy) still works; handler uses
        # open_handshake directly when it needs reports.
        _ = reports
        info = self.handshake_for(remote_addr)
        assert info is not None
        return info

    def open_handshake(
        self,
        *,
        local_addr: str,
        local_port: int,
        remote_addr: str,
        remote_port: int,
        n2n_version: int | None,
        diffusion_mode: str | None,
        peer_sharing: str | None,
        peras_support: str | None,
        at: datetime,
        ns: str,
    ) -> list[PeerReport]:
        """Open a session on HandshakeSuccess (sign of life). Always submits open."""
        at = _as_aware(at)
        existing = self._find_open(local_addr, local_port, remote_addr, remote_port)
        if existing is not None:
            self._rekey_local(existing, local_addr, local_port)
            existing.n2n_version = n2n_version
            existing.diffusion_mode = diffusion_mode
            existing.peer_sharing = peer_sharing
            existing.peras_support = peras_support
            existing.last_ns = ns
            self._touch_session(existing, at)
            self._sync_ip_peer(existing)
            return []

        session = self._new_session(
            local_addr=local_addr,
            local_port=local_port,
            remote_addr=remote_addr,
            remote_port=remote_port,
            at=at,
            ns=ns,
        )
        session.n2n_version = n2n_version
        session.diffusion_mode = diffusion_mode
        session.peer_sharing = peer_sharing
        session.peras_support = peras_support
        self._open[session.conn_key] = session
        self._opened_count += 1
        self._touch_session(session, at)
        self._maybe_mark_useful(session, at)
        self._sync_ip_peer(session)
        if self.traceroute_enabled:
            logger.debug("peer traceroute enabled but not implemented yet", peer=remote_addr)
        return [self._open_report(session, at)]

    def apply_event(self, event: PeerEvent) -> list[PeerReport]:
        """Update a session from an IG / PeerSelection / death PeerEvent."""
        at = _as_aware(event.at)
        direction = (
            event.direction
            if isinstance(event.direction, PeerDirection)
            else PeerDirection(event.direction)
        )
        new_state = PeerState(event.state) if not isinstance(event.state, PeerState) else event.state
        is_close = self._is_close_event(event, new_state)
        existing = self._find_open(
            event.local_addr, event.local_port, event.remote_addr, event.remote_port
        )
        if existing is None and is_close:
            return []
        session = self._session_for_event(event, at)
        session.last_ns = event.ns
        self._touch_session(session, at)

        reports: list[PeerReport] = []
        if not session.opened_submitted:
            reports.append(self._open_report(session, session.opened_at))

        if direction == PeerDirection.OUTBOUND:
            reports.extend(self._apply_outbound(session, new_state, event, at))
        else:
            reports.extend(self._apply_inbound(session, new_state, event, at))

        self._maybe_mark_useful(session, at)
        self._sync_ip_peer(session)
        return reports

    def flush_stable(self, now: datetime | None = None) -> list[PeerReport]:
        """Mark useful when Warm has been held long enough. No API reports."""
        now = _as_aware(now or _now())
        for session in self._open.values():
            self._maybe_mark_useful(session, now)
        return []

    def expire_stale(self, now: datetime | None = None) -> list[PeerReport]:
        """Close open sessions whose last_signal is older than signal_ttl_seconds."""
        if self.signal_ttl_seconds <= 0:
            return []
        now = _as_aware(now or _now())
        ttl = timedelta(seconds=self.signal_ttl_seconds)
        reports: list[PeerReport] = []
        for session in list(self._open.values()):
            last = session.last_signal or session.opened_at
            if now - _as_aware(last) < ttl:
                continue
            reports.extend(self._close_session(session, now, CloseReason.TTL))
        return reports

    def prune_cold(self, max_idle_seconds: int = 600) -> int:
        """Drop closed sessions and idle fully-cold IP rollups. Returns removed IP count."""
        now = _now()
        cutoff = timedelta(seconds=max_idle_seconds)
        for sid, session in list(self._closed.items()):
            closed_at = session.closed_at or session.last_signal or session.opened_at
            if now - _as_aware(closed_at) >= cutoff:
                del self._closed[sid]

        removed = 0
        for key in list(self.peers.keys()):
            if any(s.remote_addr == key for s in self._open.values()):
                continue
            peer = self.peers[key]
            idle_from = peer.last_signal or peer.last_updated
            if (now - _as_aware(idle_from)).total_seconds() < max_idle_seconds:
                continue
            del self.peers[key]
            removed += 1
        return removed

    def on_network_stop(self, at: datetime, ns: str = "") -> list[PeerReport]:
        """Server/CM stopped. Close every open session with node_restart."""
        at = _as_aware(at)
        self._stopped = True
        reports: list[PeerReport] = []
        for session in list(self._open.values()):
            session.last_ns = ns or session.last_ns
            reports.extend(self._close_session(session, at, CloseReason.NODE_RESTART))
        return reports

    def on_network_start(self, at: datetime, ns: str = "") -> list[PeerReport]:
        """Remote server started (or Startup.DiffusionInit). New node generation.

        Debounced so Local.Started + Remote.Started + DiffusionInit in the same
        couple of seconds only increment once.
        """
        at = _as_aware(at)
        if self._last_generation_at is not None and at - self._last_generation_at < _GENERATION_DEBOUNCE:
            return []
        reports: list[PeerReport] = []
        if self._open:
            reports.extend(self.on_network_stop(at, ns=ns))
        self.node_generation += 1
        self._last_generation_at = at
        self._stopped = False
        reports.append(self._node_restart_report(at, ns))
        return reports

    def reset(self) -> int:
        """Wipe open sessions without submits (tests / emergency). Prefer on_network_stop."""
        cleared = len(self._open)
        for session in list(self._open.values()):
            session.closed_at = _now()
            session.close_reason = CloseReason.NODE_RESTART
            self._closed[session.session_id] = session
        self._open.clear()
        self.peers.clear()
        return cleared

    def touch_signal(self, remote_addr: str, at: datetime) -> bool:
        """Refresh last_signal on open sessions for this IP (header/body)."""
        at = _as_aware(at)
        hit = False
        for session in self._open.values():
            if session.remote_addr != remote_addr:
                continue
            self._touch_session(session, at)
            hit = True
        peer = self.peers.get(remote_addr)
        if peer is not None:
            if peer.first_seen is None:
                peer.first_seen = at
            peer.last_signal = at
            peer.last_updated = at
            hit = True
        return hit

    def note_outbound_client(
        self,
        *,
        local_addr: str,
        local_port: int,
        remote_addr: str,
        remote_port: int,
        at: datetime,
        ns: str,
    ) -> list[PeerReport]:
        """ChainSync/BlockFetch client activity. We dialed; outbound Hot.

        Header/body orphans happen when we never saw IG promote for this
        connection. Create or attach a session from the client connectionId.
        """
        at = _as_aware(at)
        session = self._find_open(local_addr, local_port, remote_addr, remote_port)
        reports: list[PeerReport] = []
        if session is None:
            session = self._new_session(
                local_addr=local_addr,
                local_port=local_port,
                remote_addr=remote_addr,
                remote_port=remote_port,
                at=at,
                ns=ns,
            )
            session.we_dialed = True
            session.outbound_temperature = PeerState.HOT
            self._open[session.conn_key] = session
            self._opened_count += 1
            reports.append(self._open_report(session, at))
            reports.extend(
                self._temperature_report(
                    session,
                    PeerDirection.OUTBOUND,
                    PeerState.UNCONNECTED,
                    PeerState.HOT,
                    at,
                )
            )
        else:
            self._rekey_local(session, local_addr, local_port)
            session.we_dialed = True
            session.last_ns = ns
            if not session.opened_submitted:
                reports.append(self._open_report(session, session.opened_at))
            old = session.outbound_temperature
            session.outbound_temperature = PeerState.HOT
            if old != PeerState.HOT:
                reports.extend(
                    self._temperature_report(
                        session, PeerDirection.OUTBOUND, old, PeerState.HOT, at
                    )
                )
        session.last_ns = ns
        self._touch_session(session, at)
        self._maybe_mark_useful(session, at)
        self._sync_ip_peer(session)
        return reports

    def diagnostic_counts(self) -> dict[str, int]:
        """Session gauges for operator diagnostics. Not node Warm/Hot boxes."""
        counts = {
            "node_generation": self.node_generation,
            "open": len(self._open),
            "useful": 0,
            "ig_warm": 0,
            "ig_hot": 0,
            "out_warm": 0,
            "out_hot": 0,
            "opened": self._opened_count,
            "handshakes_cached": sum(
                1 for s in self._open.values() if s.n2n_version is not None
            ),
        }
        for reason in CloseReason:
            counts[f"closed_{reason.value}"] = self._close_counts.by_reason.get(reason.value, 0)
        for session in self._open.values():
            if session.useful:
                counts["useful"] += 1
            if session.ig_temperature == PeerState.WARM:
                counts["ig_warm"] += 1
            elif session.ig_temperature == PeerState.HOT:
                counts["ig_hot"] += 1
            if session.outbound_temperature == PeerState.WARM:
                counts["out_warm"] += 1
            elif session.outbound_temperature == PeerState.HOT:
                counts["out_hot"] += 1
        return counts

    def useful_session_rows(self) -> list[dict]:
        """Open sessions that passed the useful filter (operator /peers)."""
        return self._session_rows(useful_only=True)

    def all_open_session_rows(self) -> list[dict]:
        """All currently open sessions, including short HS flicker."""
        return self._session_rows(useful_only=False)

    def reported_peer_rows(self) -> list[dict]:
        """Alias for useful_session_rows (local metrics / tests)."""
        return self.useful_session_rows()

    def _session_rows(self, *, useful_only: bool) -> list[dict]:
        rows: list[dict] = []
        for session in self._open.values():
            if useful_only and not session.useful:
                continue
            listen = submit_port(session.remote_port)
            rows.append(
                {
                    "session_id": session.session_id,
                    "node_generation": session.node_generation,
                    "remote_addr": session.remote_addr,
                    "remote_port": listen,
                    "local_addr": session.local_addr,
                    "local_port": session.local_port,
                    "we_dialed": session.we_dialed,
                    "ig_temperature": session.ig_temperature.value,
                    "outbound_temperature": session.outbound_temperature.value,
                    "useful": session.useful,
                    "n2n_version": session.n2n_version,
                    "diffusion_mode": session.diffusion_mode,
                    "peer_sharing": session.peer_sharing,
                    "peras_support": session.peras_support,
                    "last_signal": _as_aware(
                        session.last_signal or session.opened_at
                    ).isoformat(),
                    "opened_at": _as_aware(session.opened_at).isoformat(),
                }
            )
        rows.sort(key=lambda r: (r["remote_addr"], r["remote_port"], r["session_id"]))
        return rows

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _new_session(
        self,
        *,
        local_addr: str,
        local_port: int,
        remote_addr: str,
        remote_port: int,
        at: datetime,
        ns: str | None,
    ) -> PeerSession:
        return PeerSession(
            node_generation=self.node_generation,
            session_id=uuid.uuid4().hex,
            local_addr=local_addr,
            local_port=local_port,
            remote_addr=remote_addr,
            remote_port=remote_port,
            opened_at=at,
            last_ns=ns,
            last_signal=at,
        )

    def _is_close_event(self, event: PeerEvent, new_state: PeerState) -> bool:
        ns = event.ns
        if ns in (
            "Net.InboundGovernor.Remote.MuxErrored",
            "Net.InboundGovernor.Remote.ResponderErrored",
            "Net.ConnectionManager.Remote.ConnectionHandler.Error",
            "Net.InboundGovernor.Remote.DemotedToColdRemote",
        ):
            return True
        if ns in PEER_SELECTION_DEMOTE_WARM_NAMESPACES:
            return True
        return ns == "Net.PeerSelection.Actions.StatusChanged" and new_state == PeerState.COLD

    def _find_open(
        self, local_addr: str, local_port: int, remote_addr: str, remote_port: int
    ) -> PeerSession | None:
        key = connection_key(local_addr, local_port, remote_addr, remote_port)
        found = self._open.get(key)
        if found is not None:
            return found
        for session in self._open.values():
            if session.remote_addr == remote_addr and session.remote_port == remote_port:
                return session
        return None

    def _rekey_local(self, session: PeerSession, local_addr: str, local_port: int) -> None:
        if session.local_addr == local_addr and session.local_port == local_port:
            return
        placeholder = session.local_addr in ("0.0.0.0", "::", "") or session.local_port == 0
        if not placeholder:
            return
        old = session.conn_key
        session.local_addr = local_addr
        session.local_port = local_port
        self._open.pop(old, None)
        self._open[session.conn_key] = session

    def _session_for_event(self, event: PeerEvent, at: datetime) -> PeerSession:
        session = self._find_open(
            event.local_addr, event.local_port, event.remote_addr, event.remote_port
        )
        if session is not None:
            self._rekey_local(session, event.local_addr, event.local_port)
            return session
        session = self._new_session(
            local_addr=event.local_addr,
            local_port=event.local_port,
            remote_addr=event.remote_addr,
            remote_port=event.remote_port,
            at=at,
            ns=event.ns,
        )
        if event.ns == "Net.PeerSelection.Actions.StatusChanged" or (
            event.ns in PEER_SELECTION_DONE_NAMESPACES
        ):
            session.we_dialed = True
        self._open[session.conn_key] = session
        self._opened_count += 1
        return session

    def _apply_outbound(
        self,
        session: PeerSession,
        new_state: PeerState,
        event: PeerEvent,
        at: datetime,
    ) -> list[PeerReport]:
        reports: list[PeerReport] = []
        ns = event.ns
        session.we_dialed = True if session.we_dialed is None else session.we_dialed

        if ns in (
            "Net.InboundGovernor.Remote.MuxErrored",
            "Net.InboundGovernor.Remote.ResponderErrored",
            "Net.ConnectionManager.Remote.ConnectionHandler.Error",
        ) or "ConnectionHandler.Error" in ns:
            reason = self._death_reason(ns)
            return self._close_session(session, at, reason)

        if new_state == PeerState.COOLING:
            session.outbound_temperature = PeerState.COOLING
            return reports

        if new_state == PeerState.COLD:
            return self._close_session(session, at, CloseReason.COOLING_TO_COLD)

        old = session.outbound_temperature
        session.outbound_temperature = new_state
        if new_state in _ACTIVE:
            reports.extend(self._temperature_report(session, PeerDirection.OUTBOUND, old, new_state, at))
        return reports

    def _apply_inbound(
        self,
        session: PeerSession,
        new_state: PeerState,
        event: PeerEvent,
        at: datetime,
    ) -> list[PeerReport]:
        ns = event.ns
        if ns == "Net.InboundGovernor.Remote.MuxErrored":
            return self._close_session(session, at, CloseReason.IG_MUX_ERROR)
        if ns == "Net.InboundGovernor.Remote.ResponderErrored":
            return self._close_session(session, at, CloseReason.IG_RESPONDER_ERROR)
        if ns == "Net.ConnectionManager.Remote.ConnectionHandler.Error":
            return self._close_session(session, at, CloseReason.HANDLER_ERROR)

        if new_state == PeerState.COLD:
            return self._close_session(session, at, CloseReason.DEMOTED_COLD)

        old = session.ig_temperature
        session.ig_temperature = new_state
        if new_state in _ACTIVE:
            return self._temperature_report(session, PeerDirection.INBOUND, old, new_state, at)
        return []

    def _death_reason(self, ns: str) -> CloseReason:
        if "MuxErrored" in ns:
            return CloseReason.IG_MUX_ERROR
        if "ResponderErrored" in ns:
            return CloseReason.IG_RESPONDER_ERROR
        return CloseReason.HANDLER_ERROR

    def _temperature_report(
        self,
        session: PeerSession,
        direction: PeerDirection,
        old: PeerState,
        new: PeerState,
        at: datetime,
    ) -> list[PeerReport]:
        submitted_attr = "ig_submitted" if direction == PeerDirection.INBOUND else "out_submitted"
        already = getattr(session, submitted_attr)
        if already == new:
            return []
        if new == PeerState.WARM and already is None:
            # Open already advertised Warm. Skip duplicate cold_to_warm.
            setattr(session, submitted_attr, PeerState.WARM)
            return []
        if new == PeerState.WARM and already == PeerState.HOT:
            change = PeerEventChangeType.HOT_WARM
        elif new == PeerState.HOT:
            change = PeerEventChangeType.WARM_HOT
        elif new == PeerState.WARM:
            change = PeerEventChangeType.COLD_WARM
        else:
            return []
        setattr(session, submitted_attr, new)
        _ = old
        return [
            self._report(
                session,
                direction=direction,
                change_type=change,
                state=new.value,
                at=at,
                event_role=EventRole.TEMPERATURE,
            )
        ]

    def _open_report(self, session: PeerSession, at: datetime) -> PeerReport:
        session.opened_submitted = True
        if session.ig_temperature in _ACTIVE:
            session.ig_submitted = PeerState.WARM
        if session.outbound_temperature in _ACTIVE:
            session.out_submitted = PeerState.WARM
        direction = (
            PeerDirection.OUTBOUND if session.we_dialed else PeerDirection.INBOUND
        )
        return self._report(
            session,
            direction=direction,
            change_type=PeerEventChangeType.COLD_WARM,
            state=PeerState.WARM.value,
            at=at,
            event_role=EventRole.OPEN,
        )

    def _close_session(
        self, session: PeerSession, at: datetime, reason: CloseReason
    ) -> list[PeerReport]:
        if session.closed_at is not None:
            return []
        key = session.conn_key
        session.closed_at = at
        session.close_reason = reason
        session.ig_temperature = PeerState.COLD
        session.outbound_temperature = PeerState.COLD
        session.last_signal = at
        self._open.pop(key, None)
        self._closed[session.session_id] = session
        self._close_counts.add(reason)
        self._sync_ip_peer(session)
        direction = (
            PeerDirection.OUTBOUND if session.we_dialed else PeerDirection.INBOUND
        )
        if reason in (CloseReason.COOLING_TO_COLD,) or (
            session.we_dialed and reason == CloseReason.NODE_RESTART
        ):
            direction = PeerDirection.OUTBOUND
        return [
            self._report(
                session,
                direction=direction,
                change_type=PeerEventChangeType.WARM_COLD,
                state=PeerState.COLD.value,
                at=at,
                event_role=EventRole.CLOSE,
                close_reason=reason,
            )
        ]

    def _node_restart_report(self, at: datetime, ns: str) -> PeerReport:
        dummy = Peer(
            ns=ns or "node_restart",
            local_addr="0.0.0.0",
            local_port=0,
            remote_addr="0.0.0.0",
            remote_port=0,
            first_seen=at,
            last_signal=at,
            last_updated=at,
        )
        return PeerReport(
            peer=dummy,
            direction=PeerDirection.INBOUND,
            change_type=PeerEventChangeType.WARM_COLD,
            state=PeerState.COLD.value,
            at=at,
            remote_port=0,
            event_role=EventRole.NODE_RESTART,
            node_generation=self.node_generation,
            session_id=None,
            close_reason=CloseReason.NODE_RESTART,
            we_dialed=None,
        )

    def _report(
        self,
        session: PeerSession,
        *,
        direction: PeerDirection,
        change_type: PeerEventChangeType,
        state: str,
        at: datetime,
        event_role: EventRole,
        close_reason: CloseReason | None = None,
    ) -> PeerReport:
        return PeerReport(
            peer=session.as_peer(),
            direction=direction,
            change_type=change_type,
            state=state,
            at=at,
            remote_port=submit_port(session.remote_port),
            event_role=event_role,
            node_generation=session.node_generation,
            session_id=session.session_id,
            close_reason=close_reason,
            we_dialed=session.we_dialed,
        )

    def _touch_session(self, session: PeerSession, at: datetime) -> None:
        session.last_signal = at
        if session.warm_since is None and (
            session.ig_temperature in _ACTIVE or session.outbound_temperature in _ACTIVE
        ):
            session.warm_since = at

    def _maybe_mark_useful(self, session: PeerSession, now: datetime) -> None:
        if not session.open or session.useful:
            return
        ig = session.ig_temperature
        out = session.outbound_temperature
        if ig == PeerState.HOT or out == PeerState.HOT:
            session.useful = True
            return
        if ig not in _ACTIVE and out not in _ACTIVE:
            return
        if session.warm_since is None:
            session.warm_since = now
        if self.stable_seconds == 0:
            session.useful = True
            return
        if now - _as_aware(session.warm_since) >= timedelta(seconds=self.stable_seconds):
            session.useful = True

    def _sync_ip_peer(self, session: PeerSession) -> None:
        key = session.remote_addr
        peer = self.peers.get(key)
        if peer is None:
            peer = session.as_peer()
            self.peers[key] = peer
        else:
            if peer.first_seen is None or session.opened_at < peer.first_seen:
                peer.first_seen = session.opened_at
            peer.last_signal = session.last_signal or peer.last_signal
            peer.last_updated = session.last_signal or peer.last_updated
            peer.ns = session.last_ns
            if session.n2n_version is not None:
                peer.n2n_version = session.n2n_version
                peer.diffusion_mode = session.diffusion_mode
                peer.peer_sharing = session.peer_sharing
                peer.peras_support = session.peras_support
            if submit_port(session.remote_port) and (
                not peer.remote_port or session.we_dialed
            ):
                peer.remote_port = submit_port(session.remote_port)
            peer.local_addr = session.local_addr
            peer.local_port = session.local_port

        ig = PeerState.UNCONNECTED
        out = PeerState.UNCONNECTED
        for open_s in self._open.values():
            if open_s.remote_addr != key:
                continue
            if open_s.ig_temperature == PeerState.HOT or (
                open_s.ig_temperature == PeerState.WARM and ig != PeerState.HOT
            ):
                ig = open_s.ig_temperature
            if open_s.outbound_temperature == PeerState.HOT or (
                open_s.outbound_temperature == PeerState.WARM and out != PeerState.HOT
            ):
                out = open_s.outbound_temperature
            if open_s.outbound_temperature == PeerState.COOLING and out not in _ACTIVE:
                out = PeerState.COOLING
        if not any(s.remote_addr == key for s in self._open.values()):
            ig = PeerState.COLD
            out = PeerState.COLD
        peer.state_inbound = ig
        peer.state_outbound = out
        peer.duplex = False
