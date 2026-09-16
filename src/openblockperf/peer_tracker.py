"""Debounced peer-state tracking and API report decisions.

Internal FSM follows cardano-node temperatures (including Cooling).
Only stable Warm/Hot enters (by configured level) and immediate leaves
are turned into backend-compatible PeerEventChangeType values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

from openblockperf.logging import logger
from openblockperf.models.events import PeerEvent, PeerEventChangeType
from openblockperf.models.peer import Peer, PeerDirection, PeerState


class PeerEventsLevel(str, Enum):
    OFF = "off"
    LOW = "low"
    MID = "mid"
    HIGH = "high"


# States that mean "interesting connected temperature" for tracking.
_ACTIVE = {PeerState.WARM, PeerState.HOT}
_GONE = {PeerState.COLD, PeerState.UNCONNECTED, PeerState.UNKNOWN, PeerState.COOLING}


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
        level: PeerEventsLevel = PeerEventsLevel.MID,
        stable_seconds: int = 15,
        traceroute_enabled: bool = False,
    ):
        self.peers = peers
        self.level = level
        self.stable_seconds = max(0, stable_seconds)
        self.traceroute_enabled = traceroute_enabled
        self._tracks: dict[str, PeerTrack] = {}

    def enabled(self) -> bool:
        return self.level != PeerEventsLevel.OFF

    def wants_warm(self) -> bool:
        return self.level == PeerEventsLevel.HIGH

    def wants_hot(self) -> bool:
        return self.level in (PeerEventsLevel.MID, PeerEventsLevel.HIGH)

    def wants_api_reports(self) -> bool:
        """Temperature reports to the API (mid/high). Low only tracks locally."""
        return self.level in (PeerEventsLevel.MID, PeerEventsLevel.HIGH)

    def peer_key(self, remote_addr: str) -> str:
        """Identity is remote IP only (inbound ephemeral ports are ignored)."""
        return remote_addr

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

    def _report_port(self, peer: Peer, direction: PeerDirection) -> int:
        """Inbound: never report ephemeral remote ports. Outbound: keep service port."""
        if direction == PeerDirection.INBOUND:
            return 0
        return peer.remote_port

    def _update_duplex(self, peer: Peer) -> None:
        peer.duplex = peer.state_inbound in _ACTIVE and peer.state_outbound in _ACTIVE

    def apply_event(self, event: PeerEvent) -> list[PeerReport]:
        """Apply one parsed peer event. Returns immediate leave reports (if any)."""
        if not self.enabled():
            return []

        key = self.peer_key(event.remote_addr)
        direction = PeerDirection(event.direction)
        new_state = PeerState(event.state)

        if key not in self.peers:
            # Inbound identity ignores ephemeral port in stored remote_port for reporting,
            # but keep last observed outbound service port when we learn it.
            stored_port = 0 if direction == PeerDirection.INBOUND else event.remote_port
            self.peers[key] = Peer(
                ns=event.ns,
                remote_addr=event.remote_addr,
                remote_port=stored_port,
                local_addr=event.local_addr,
                local_port=event.local_port,
            )
        peer = self.peers[key]

        if direction == PeerDirection.OUTBOUND and event.remote_port:
            peer.remote_port = event.remote_port
        peer.local_addr = event.local_addr
        peer.local_port = event.local_port
        peer.ns = event.ns
        peer.last_updated = _now()

        old_state = peer.state_inbound if direction == PeerDirection.INBOUND else peer.state_outbound
        if direction == PeerDirection.INBOUND:
            peer.state_inbound = new_state
        else:
            peer.state_outbound = new_state

        self._update_duplex(peer)
        track = self._track_for(key, peer)
        dtrack = self._dir_track(track, direction)

        reports: list[PeerReport] = []

        if not self.wants_api_reports():
            # low: keep local state only
            dtrack.pending = None
            return reports

        # Normalize Cooling as "leaving" for report interest.
        interest_new = self._interest_state(new_state)
        interest_old = self._interest_state(old_state)

        # Enter candidate (warm/hot)
        if interest_new in (PeerState.WARM, PeerState.HOT):
            if interest_new == PeerState.WARM and not self.wants_warm():
                # mid: ignore warm enters; wait for hot
                dtrack.pending = None
            elif interest_new == PeerState.HOT and not self.wants_hot():
                dtrack.pending = None
            elif dtrack.reported == interest_new:
                # Already reported this temperature; ignore churn
                dtrack.pending = None
            else:
                # Warm then quickly Hot: replace pending warm with hot
                dtrack.pending = PendingEnter(
                    direction=direction,
                    target=interest_new,
                    since=_as_aware(event.at),
                    event_at=_as_aware(event.at),
                )
                if self.stable_seconds == 0:
                    reports.extend(self._flush_pending(track, dtrack, force=True))

        # Leave interesting state → report immediately if we had reported it
        if interest_old in (PeerState.WARM, PeerState.HOT) and interest_new in _GONE:
            reports.extend(self._leave_reports(peer, dtrack, direction, interest_old, new_state, event))
            dtrack.pending = None
        elif interest_old == PeerState.HOT and interest_new == PeerState.WARM:
            # Hot demoted to warm
            reports.extend(self._leave_reports(peer, dtrack, direction, PeerState.HOT, new_state, event))
            # May start warm pending if high level
            if self.wants_warm() and dtrack.reported != PeerState.WARM:
                dtrack.pending = PendingEnter(
                    direction=direction,
                    target=PeerState.WARM,
                    since=_as_aware(event.at),
                    event_at=_as_aware(event.at),
                )
            else:
                dtrack.pending = None

        if self.traceroute_enabled:
            # Hook only; traceroute is not implemented in this change.
            logger.debug("peer traceroute enabled but not implemented yet", peer=peer.remote_addr)

        return reports

    def flush_stable(self, now: datetime | None = None) -> list[PeerReport]:
        """Emit reports for pending enters that stayed stable long enough."""
        if not self.wants_api_reports():
            return []
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
        # Still at or above the pending target?
        if pending.target == PeerState.HOT and current != PeerState.HOT:
            dtrack.pending = None
            return []
        if pending.target == PeerState.WARM and current not in (PeerState.WARM, PeerState.HOT):
            dtrack.pending = None
            return []
        # If we pending warm but already reached hot, upgrade target
        if pending.target == PeerState.WARM and current == PeerState.HOT and self.wants_hot():
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
        # Skip warm report if level is mid (should not pending warm there)
        if pending.target == PeerState.WARM and not self.wants_warm():
            dtrack.pending = None
            return []
        if pending.target == PeerState.HOT and not self.wants_hot():
            dtrack.pending = None
            return []

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
        # Only report leave for temperatures we care about at this level
        if left == PeerState.HOT and not self.wants_hot():
            dtrack.reported = None
            return []
        if left == PeerState.WARM and not self.wants_warm():
            # mid may have reported hot; warm leave alone is irrelevant
            if dtrack.reported != PeerState.HOT:
                dtrack.reported = None
            return []

        if left == PeerState.HOT:
            # Hot → warm or Hot → cold/cooling
            final = self._interest_state(new_state)
            change_type = PeerEventChangeType.HOT_WARM if final == PeerState.WARM else PeerEventChangeType.WARM_COLD
            state_out = PeerState.WARM.value if final == PeerState.WARM else PeerState.COLD.value
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
            rows.append(
                {
                    "remote_addr": peer.remote_addr,
                    "remote_port": peer.remote_port if out_rep in _ACTIVE else 0,
                    "directions": directions,
                    "state_inbound": in_rep.value if in_rep else None,
                    "state_outbound": out_rep.value if out_rep else None,
                    "duplex": duplex_reported,
                    "last_updated": _as_aware(peer.last_updated).isoformat(),
                }
            )
        rows.sort(key=lambda r: r["remote_addr"])
        return rows
