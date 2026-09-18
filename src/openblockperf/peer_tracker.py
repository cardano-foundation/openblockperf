"""Debounced peer-state tracking and API report decisions.

Internal FSM follows cardano-node temperatures (including Cooling).
All clients report the same lifecycle: stable Cold→Warm and Warm→Hot enters
(after peer_event_stable_seconds) plus immediate leaves. Cooling is collapsed
into reportable leave types and never submitted as its own change_type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from openblockperf.logging import logger
from openblockperf.models.events import PeerEvent, PeerEventChangeType
from openblockperf.models.peer import Peer, PeerDirection, PeerState

# States that mean "interesting connected temperature" for tracking.
_ACTIVE = {PeerState.WARM, PeerState.HOT}
_GONE = {PeerState.COLD, PeerState.UNCONNECTED, PeerState.UNKNOWN, PeerState.COOLING}

# Ephemeral TCP source ports are not relay listen ports.
_EPHEMERAL_PORT_MIN = 32768


@dataclass
class PeerHandshakeInfo:
    """Latest ConnectionManager HandshakeSuccess for a remote IP."""

    remote_addr: str
    # Service listen port when known; 0 if inbound ephemeral / unknown.
    remote_port: int
    n2n_version: int | None
    diffusion_mode: str | None
    peer_sharing: str | None
    peras_support: str | None
    at: datetime


@dataclass
class PendingEnter:
    """A candidate Warm/Hot enter waiting for the stability window."""

    direction: PeerDirection
    target: PeerState
    since: datetime
    event_at: datetime


@dataclass
class PeerReport:
    """Payload the handler turns into an API submit."""

    peer: Peer
    direction: PeerDirection
    change_type: PeerEventChangeType
    state: str
    at: datetime
    remote_port: int


@dataclass
class DirectionTrack:
    """Per-direction reported and pending state."""

    reported: PeerState | None = None  # last state we told the backend about
    pending: PendingEnter | None = None


@dataclass
class PeerTrack:
    peer: Peer
    inbound: DirectionTrack = field(default_factory=DirectionTrack)
    outbound: DirectionTrack = field(default_factory=DirectionTrack)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class PeerTracker:
    """Owns peer dict updates and decides what to submit."""

    def __init__(
        self,
        peers: dict[str, Peer],
        *,
        stable_seconds: int = 15,
        traceroute_enabled: bool = False,
    ):
        self.peers = peers
        self.stable_seconds = max(0, stable_seconds)
        # Future: optional traceroute enrichment (not implemented yet).
        self.traceroute_enabled = traceroute_enabled
        self._tracks: dict[str, PeerTrack] = {}
        self._handshakes: dict[str, PeerHandshakeInfo] = {}

    def enabled(self) -> bool:
        """Peer temperature tracking is always on."""
        return True

    def peer_key(self, remote_addr: str) -> str:
        """Identity is remote IP only (inbound ephemeral ports are ignored)."""
        return remote_addr

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
    ) -> PeerHandshakeInfo:
        """Cache HandshakeSuccess options for later peerevent enrichment."""
        port = 0 if remote_port >= _EPHEMERAL_PORT_MIN else remote_port
        info = PeerHandshakeInfo(
            remote_addr=remote_addr,
            remote_port=port,
            n2n_version=n2n_version,
            diffusion_mode=diffusion_mode,
            peer_sharing=peer_sharing,
            peras_support=peras_support,
            at=_as_aware(at),
        )
        self._handshakes[remote_addr] = info
        peer = self.peers.get(remote_addr)
        if peer is not None:
            self._apply_handshake_to_peer(peer, info)
        return info

    def handshake_for(self, remote_addr: str) -> PeerHandshakeInfo | None:
        return self._handshakes.get(remote_addr)

    def _apply_handshake_to_peer(self, peer: Peer, info: PeerHandshakeInfo) -> None:
        peer.n2n_version = info.n2n_version
        peer.diffusion_mode = info.diffusion_mode
        peer.peer_sharing = info.peer_sharing
        peer.peras_support = info.peras_support
        if info.remote_port and not peer.remote_port:
            peer.remote_port = info.remote_port

    def _track_for(self, key: str, peer: Peer) -> PeerTrack:
        track = self._tracks.get(key)
        if track is None:
            track = PeerTrack(peer=peer)
            self._tracks[key] = track
        else:
            track.peer = peer
        return track

    def _dir_track(self, track: PeerTrack, direction: PeerDirection) -> DirectionTrack:
        return track.inbound if direction == PeerDirection.INBOUND else track.outbound

    def _update_duplex(self, peer: Peer) -> None:
        peer.duplex = peer.state_inbound in _ACTIVE and peer.state_outbound in _ACTIVE

    def _report_port(self, peer: Peer, direction: PeerDirection) -> int:
        if direction == PeerDirection.INBOUND:
            return 0
        return peer.remote_port

    def apply_event(self, event: PeerEvent) -> list[PeerReport]:
        """Update peer temperatures from a PeerEvent; return any API reports."""
        key = self.peer_key(event.remote_addr)
        direction = (
            event.direction
            if isinstance(event.direction, PeerDirection)
            else PeerDirection(event.direction)
        )
        new_state = PeerState(event.state) if not isinstance(event.state, PeerState) else event.state

        peer = self.peers.get(key)
        if peer is None:
            stored_port = 0 if direction == PeerDirection.INBOUND else event.remote_port
            peer = Peer(
                ns=event.ns,
                local_addr=event.local_addr,
                local_port=event.local_port,
                remote_addr=event.remote_addr,
                remote_port=stored_port,
            )
            self.peers[key] = peer
        if direction == PeerDirection.OUTBOUND and event.remote_port:
            peer.remote_port = event.remote_port

        hs = self._handshakes.get(key)
        if hs is not None:
            self._apply_handshake_to_peer(peer, hs)

        old_state = peer.state_inbound if direction == PeerDirection.INBOUND else peer.state_outbound
        if direction == PeerDirection.INBOUND:
            peer.state_inbound = new_state
        else:
            peer.state_outbound = new_state
        peer.last_updated = _as_aware(event.at)
        peer.ns = event.ns
        self._update_duplex(peer)

        track = self._track_for(key, peer)
        dtrack = self._dir_track(track, direction)
        reports: list[PeerReport] = []

        interest_new = self._interest_state(new_state)
        interest_old = self._interest_state(old_state)

        if interest_new in (PeerState.WARM, PeerState.HOT):
            if dtrack.reported == interest_new:
                dtrack.pending = None
            else:
                dtrack.pending = PendingEnter(
                    direction=direction,
                    target=interest_new,
                    since=_as_aware(event.at),
                    event_at=_as_aware(event.at),
                )
                if self.stable_seconds == 0:
                    reports.extend(self._flush_pending(track, dtrack, force=True))

        if interest_old in (PeerState.WARM, PeerState.HOT) and interest_new in _GONE:
            reports.extend(self._leave_reports(peer, dtrack, direction, interest_old, new_state, event))
            dtrack.pending = None
        elif interest_old == PeerState.HOT and interest_new == PeerState.WARM:
            reports.extend(self._leave_reports(peer, dtrack, direction, PeerState.HOT, new_state, event))
            if dtrack.reported != PeerState.WARM:
                dtrack.pending = PendingEnter(
                    direction=direction,
                    target=PeerState.WARM,
                    since=_as_aware(event.at),
                    event_at=_as_aware(event.at),
                )
            else:
                dtrack.pending = None

        if self.traceroute_enabled:
            logger.debug("peer traceroute enabled but not implemented yet", peer=peer.remote_addr)

        return reports

    def flush_stable(self, now: datetime | None = None) -> list[PeerReport]:
        """Emit reports for pending enters that stayed stable long enough."""
        now = _as_aware(now or _now())
        reports: list[PeerReport] = []
        for track in list(self._tracks.values()):
            for dtrack in (track.inbound, track.outbound):
                reports.extend(self._flush_pending(track, dtrack, now=now))
        return reports

    def _interest_state(self, state: PeerState) -> PeerState:
        """Map Cooling to gone for interest comparisons."""
        if state == PeerState.COOLING:
            return PeerState.COLD
        return state

    def _flush_pending(
        self,
        track: PeerTrack,
        dtrack: DirectionTrack,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> list[PeerReport]:
        pending = dtrack.pending
        if pending is None:
            return []
        now = _as_aware(now or _now())
        peer = track.peer
        current = peer.state_inbound if pending.direction == PeerDirection.INBOUND else peer.state_outbound
        if pending.target == PeerState.HOT and current != PeerState.HOT:
            dtrack.pending = None
            return []
        if pending.target == PeerState.WARM and current not in (PeerState.WARM, PeerState.HOT):
            dtrack.pending = None
            return []
        if pending.target == PeerState.WARM and current == PeerState.HOT:
            pending.target = PeerState.HOT

        elapsed = now - pending.since
        if not force and elapsed < timedelta(seconds=self.stable_seconds):
            return []

        if dtrack.reported == pending.target:
            dtrack.pending = None
            return []

        change_type = (
            PeerEventChangeType.WARM_HOT if pending.target == PeerState.HOT else PeerEventChangeType.COLD_WARM
        )
        dtrack.reported = pending.target
        dtrack.pending = None
        return [
            PeerReport(
                peer=peer,
                direction=pending.direction,
                change_type=change_type,
                state=pending.target.value,
                at=pending.event_at,
                remote_port=self._report_port(peer, pending.direction),
            )
        ]

    def _leave_reports(
        self,
        peer: Peer,
        dtrack: DirectionTrack,
        direction: PeerDirection,
        left: PeerState,
        new_state: PeerState,
        event: PeerEvent,
    ) -> list[PeerReport]:
        if dtrack.reported is None:
            return []

        if left == PeerState.HOT:
            final = self._interest_state(new_state)
            change_type = PeerEventChangeType.HOT_WARM if final == PeerState.WARM else PeerEventChangeType.WARM_COLD
            state_out = PeerState.WARM.value if final == PeerState.WARM else PeerState.COLD.value
            # Keep Warm as reported after Hot→Warm so a later Warm→Cold still leaves.
            dtrack.reported = PeerState.WARM if change_type == PeerEventChangeType.HOT_WARM else None
        else:
            change_type = PeerEventChangeType.WARM_COLD
            state_out = PeerState.COLD.value
            dtrack.reported = None

        return [
            PeerReport(
                peer=peer,
                direction=direction,
                change_type=change_type,
                state=state_out,
                at=_as_aware(event.at),
                remote_port=self._report_port(peer, direction),
            )
        ]

    def prune_cold(self, max_idle_seconds: int = 600) -> int:
        """Remove peers that are fully cold/unknown and idle. Returns removed count."""
        now = _now()
        removed = 0
        for key in list(self.peers.keys()):
            peer = self.peers[key]
            if peer.state_inbound in _ACTIVE or peer.state_outbound in _ACTIVE:
                continue
            if peer.state_inbound == PeerState.COOLING or peer.state_outbound == PeerState.COOLING:
                continue
            idle = (now - _as_aware(peer.last_updated)).total_seconds()
            if idle < max_idle_seconds:
                continue
            del self.peers[key]
            self._tracks.pop(key, None)
            removed += 1
        return removed

    def reset(self) -> int:
        """Wipe peer FSM and handshake cache (node CM/server shutdown).

        Returns how many peers were cleared. Does not emit leave reports; the
        node is restarting and new promote/StatusChanged events will rebuild.
        """
        cleared = len(self.peers)
        self.peers.clear()
        self._tracks.clear()
        self._handshakes.clear()
        return cleared

    def diagnostic_counts(self) -> dict[str, int]:
        """Live vs reported vs pending Warm/Hot counts for operator diagnostics.

        * live_*     – current FSM temperature (every parsed event)
        * reported_* – temperatures already submitted to the backend (debounce passed)
        * pending_*  – waiting for peer_event_stable_seconds before submit
        """
        counts = {
            "in_warm_live": 0,
            "out_warm_live": 0,
            "in_hot_live": 0,
            "out_hot_live": 0,
            "in_warm_reported": 0,
            "out_warm_reported": 0,
            "in_hot_reported": 0,
            "out_hot_reported": 0,
            "in_warm_pending": 0,
            "out_warm_pending": 0,
            "in_hot_pending": 0,
            "out_hot_pending": 0,
            "duplex_live": 0,
            "duplex_reported": 0,
            "handshakes_cached": len(self._handshakes),
        }
        for key, peer in self.peers.items():
            if peer.state_inbound == PeerState.WARM:
                counts["in_warm_live"] += 1
            elif peer.state_inbound == PeerState.HOT:
                counts["in_hot_live"] += 1
            if peer.state_outbound == PeerState.WARM:
                counts["out_warm_live"] += 1
            elif peer.state_outbound == PeerState.HOT:
                counts["out_hot_live"] += 1
            if peer.duplex:
                counts["duplex_live"] += 1

            track = self._tracks.get(key)
            if track is None:
                continue
            for prefix, dtrack in (("in", track.inbound), ("out", track.outbound)):
                if dtrack.reported == PeerState.WARM:
                    counts[f"{prefix}_warm_reported"] += 1
                elif dtrack.reported == PeerState.HOT:
                    counts[f"{prefix}_hot_reported"] += 1
                if dtrack.pending is not None:
                    if dtrack.pending.target == PeerState.WARM:
                        counts[f"{prefix}_warm_pending"] += 1
                    elif dtrack.pending.target == PeerState.HOT:
                        counts[f"{prefix}_hot_pending"] += 1
            if track.inbound.reported in _ACTIVE and track.outbound.reported in _ACTIVE:
                counts["duplex_reported"] += 1
        return counts

    def reported_peer_rows(self) -> list[dict]:
        """Peers with at least one direction still marked reported (export set)."""
        rows: list[dict] = []
        for key, peer in self.peers.items():
            track = self._tracks.get(key)
            if track is None:
                continue
            in_rep = track.inbound.reported
            out_rep = track.outbound.reported
            if in_rep not in _ACTIVE and out_rep not in _ACTIVE:
                continue
            directions: list[str] = []
            if in_rep in _ACTIVE:
                directions.append("inbound")
            if out_rep in _ACTIVE:
                directions.append("outbound")
            duplex_reported = in_rep in _ACTIVE and out_rep in _ACTIVE
            hs = self._handshakes.get(key)
            rows.append(
                {
                    "remote_addr": peer.remote_addr,
                    "remote_port": peer.remote_port if out_rep in _ACTIVE else 0,
                    "directions": directions,
                    "state_inbound": in_rep.value if in_rep else None,
                    "state_outbound": out_rep.value if out_rep else None,
                    "duplex": duplex_reported,
                    "n2n_version": peer.n2n_version,
                    "diffusion_mode": peer.diffusion_mode,
                    "peer_sharing": peer.peer_sharing,
                    "peras_support": peer.peras_support,
                    "handshake_at": hs.at.isoformat() if hs else None,
                    "last_updated": _as_aware(peer.last_updated).isoformat(),
                }
            )
        rows.sort(key=lambda r: r["remote_addr"])
        return rows
