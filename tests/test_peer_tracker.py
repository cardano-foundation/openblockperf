"""Tests for peer temperature tracking, debounce, and cooling collapse."""

from datetime import UTC, datetime, timedelta

from openblockperf.models.events import (
    PeerEventChangeType,
    StatusChangedEvent,
)
from openblockperf.models.peer import PeerDirection, PeerState
from openblockperf.peer_tracker import PeerEventsLevel, PeerTracker


def _status_changed(
    *,
    at: str,
    transition: str,
    local: str = "10.0.0.1:3001",
    remote: str = "203.0.113.10:3001",
) -> StatusChangedEvent:
    # transition examples: ColdToWarm, WarmToHot, HotToCooling, CoolingToCold
    if transition.endswith("ToWarm") and "Cold" in transition:
        body = f"{transition} (Just {local}) {remote}"
    else:
        la, lp = local.rsplit(":", 1)
        ra, rp = remote.rsplit(":", 1)
        body = (
            f"{transition} (ConnectionId {{localAddress = {la}:{lp}, "
            f"remoteAddress = {ra}:{rp}}})"
        )
    return StatusChangedEvent.model_validate(
        {
            "at": at,
            "ns": "Net.PeerSelection.Actions.StatusChanged",
            "data": {
                "kind": "PeerStatusChanged",
                "peerStatusChangeType": body,
            },
            "sev": "Info",
            "thread": "1",
            "host": "test",
        }
    )


def _promoted_hot(*, at: str, remote_addr: str, remote_port: int) -> dict:
    return {
        "at": at,
        "ns": "Net.InboundGovernor.Remote.PromotedToHotRemote",
        "data": {
            "kind": "PromotedToHotRemote",
            "connectionId": {
                "localAddress": {"address": "10.0.0.1", "port": "3001"},
                "remoteAddress": {"address": remote_addr, "port": str(remote_port)},
            },
            "result": {"kind": "OperationSuccess"},
        },
        "sev": "Info",
        "thread": "1",
        "host": "test",
    }


class TestStatusChangedCoolingParse:
    def test_hot_to_cooling_parses(self):
        ev = _status_changed(
            at="2026-09-15T19:00:00.000000Z",
            transition="HotToCooling",
        )
        assert ev.state == "Cooling"
        assert ev.change_type == PeerEventChangeType.HOT_COOLING
        assert not ev.change_type.is_reportable()

    def test_cooling_to_cold_parses(self):
        ev = _status_changed(
            at="2026-09-15T19:00:01.000000Z",
            transition="CoolingToCold",
        )
        assert ev.state == "Cold"
        assert ev.change_type == PeerEventChangeType.COOLING_COLD


class TestPeerTrackerDebounce:
    def test_mid_skips_warm_and_debounces_hot(self):
        peers = {}
        tracker = PeerTracker(peers, level=PeerEventsLevel.MID, stable_seconds=15)
        t0 = "2026-09-15T19:00:00.000000Z"
        warm = _status_changed(at=t0, transition="ColdToWarm")
        assert tracker.apply_event(warm) == []
        hot = _status_changed(at="2026-09-15T19:00:01.000000Z", transition="WarmToHot")
        assert tracker.apply_event(hot) == []
        # Not yet stable
        assert tracker.flush_stable(now=datetime(2026, 9, 15, 19, 0, 10, tzinfo=UTC)) == []
        reports = tracker.flush_stable(now=datetime(2026, 9, 15, 19, 0, 20, tzinfo=UTC))
        assert len(reports) == 1
        assert reports[0].change_type == PeerEventChangeType.WARM_HOT
        assert reports[0].direction == PeerDirection.OUTBOUND
        assert reports[0].remote_port == 3001

    def test_flicker_hot_without_stable_does_not_report_leave(self):
        peers = {}
        tracker = PeerTracker(peers, level=PeerEventsLevel.MID, stable_seconds=15)
        hot = _status_changed(at="2026-09-15T19:00:00.000000Z", transition="WarmToHot")
        assert tracker.apply_event(hot) == []
        cool = _status_changed(at="2026-09-15T19:00:02.000000Z", transition="HotToCooling")
        # Never reported → no leave
        assert tracker.apply_event(cool) == []

    def test_leave_after_reported_hot_is_immediate(self):
        peers = {}
        tracker = PeerTracker(peers, level=PeerEventsLevel.MID, stable_seconds=0)
        hot = _status_changed(at="2026-09-15T19:00:00.000000Z", transition="WarmToHot")
        reports = tracker.apply_event(hot)
        assert len(reports) == 1
        cool = _status_changed(at="2026-09-15T19:00:05.000000Z", transition="HotToCooling")
        leaves = tracker.apply_event(cool)
        assert len(leaves) == 1
        assert leaves[0].change_type == PeerEventChangeType.WARM_COLD

    def test_inbound_reports_port_zero_and_keys_by_ip(self):
        from openblockperf.models.events import PromotedPeerEvent

        peers = {}
        tracker = PeerTracker(peers, level=PeerEventsLevel.MID, stable_seconds=0)
        raw = _promoted_hot(at="2026-09-15T19:00:00.000000Z", remote_addr="198.51.100.7", remote_port=54321)
        ev = PromotedPeerEvent.model_validate(raw)
        reports = tracker.apply_event(ev)
        assert len(reports) == 1
        assert reports[0].remote_port == 0
        assert reports[0].direction == PeerDirection.INBOUND
        assert "198.51.100.7" in peers
        assert peers["198.51.100.7"].state_inbound == PeerState.HOT

    def test_duplex_when_both_directions_hot(self):
        from openblockperf.models.events import PromotedPeerEvent

        peers = {}
        tracker = PeerTracker(peers, level=PeerEventsLevel.MID, stable_seconds=0)
        out = _status_changed(
            at="2026-09-15T19:00:00.000000Z",
            transition="WarmToHot",
            remote="198.51.100.7:3001",
        )
        tracker.apply_event(out)
        assert peers["198.51.100.7"].duplex is False
        inbound = PromotedPeerEvent.model_validate(
            _promoted_hot(at="2026-09-15T19:00:01.000000Z", remote_addr="198.51.100.7", remote_port=40000)
        )
        tracker.apply_event(inbound)
        assert peers["198.51.100.7"].duplex is True

    def test_high_reports_stable_warm(self):
        peers = {}
        tracker = PeerTracker(peers, level=PeerEventsLevel.HIGH, stable_seconds=0)
        warm = _status_changed(at="2026-09-15T19:00:00.000000Z", transition="ColdToWarm")
        reports = tracker.apply_event(warm)
        assert len(reports) == 1
        assert reports[0].change_type == PeerEventChangeType.COLD_WARM

    def test_off_ignores_events(self):
        peers = {}
        tracker = PeerTracker(peers, level=PeerEventsLevel.OFF, stable_seconds=0)
        hot = _status_changed(at="2026-09-15T19:00:00.000000Z", transition="WarmToHot")
        assert tracker.apply_event(hot) == []
        assert peers == {}

    def test_prune_removes_idle_cold(self):
        peers = {}
        tracker = PeerTracker(peers, level=PeerEventsLevel.MID, stable_seconds=0)
        warm = _status_changed(at="2026-09-15T19:00:00.000000Z", transition="ColdToWarm")
        tracker.apply_event(warm)
        cold = _status_changed(at="2026-09-15T19:00:01.000000Z", transition="WarmToCooling")
        # WarmToCooling then treat as gone – use CoolingToCold after setting cold path
        # Force cold via CoolingToCold from a hot-less warm leave: set state cold manually path
        from openblockperf.models.events import StatusChangedEvent

        # Direct cold via WarmToCooling parse then CoolingToCold
        ev_cool = _status_changed(at="2026-09-15T19:00:01.000000Z", transition="WarmToCooling")
        tracker.apply_event(ev_cool)
        ev_cold = _status_changed(at="2026-09-15T19:00:02.000000Z", transition="CoolingToCold")
        tracker.apply_event(ev_cold)
        peer = peers["203.0.113.10"]
        peer.last_updated = datetime.now(UTC) - timedelta(seconds=700)
        assert tracker.prune_cold(max_idle_seconds=600) == 1
        assert peers == {}
