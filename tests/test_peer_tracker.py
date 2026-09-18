"""Tests for peer temperature tracking, debounce, and cooling collapse."""

from datetime import UTC, datetime, timedelta

from openblockperf.models.events import (
    ConnectionLostEvent,
    HandshakeSuccessEvent,
    PeerEventChangeType,
    PromotedPeerEvent,
    StatusChangedEvent,
)
from openblockperf.models.peer import PeerDirection, PeerState
from openblockperf.peer_tracker import PeerTracker


def _status_changed(
    *,
    at: str,
    transition: str,
    local: str = "10.0.0.1:3001",
    remote: str = "203.0.113.10:3001",
) -> StatusChangedEvent:
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
    def test_warm_then_hot_debounces_to_hot(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=15)
        t0 = "2026-09-15T19:00:00.000000Z"
        warm = _status_changed(at=t0, transition="ColdToWarm")
        assert tracker.apply_event(warm) == []
        hot = _status_changed(at="2026-09-15T19:00:01.000000Z", transition="WarmToHot")
        assert tracker.apply_event(hot) == []
        assert tracker.flush_stable(now=datetime(2026, 9, 15, 19, 0, 10, tzinfo=UTC)) == []
        reports = tracker.flush_stable(now=datetime(2026, 9, 15, 19, 0, 20, tzinfo=UTC))
        assert len(reports) == 1
        assert reports[0].change_type == PeerEventChangeType.WARM_HOT
        assert reports[0].direction == PeerDirection.OUTBOUND
        assert reports[0].remote_port == 3001

    def test_stable_warm_reports_cold_to_warm(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0)
        warm = _status_changed(at="2026-09-15T19:00:00.000000Z", transition="ColdToWarm")
        reports = tracker.apply_event(warm)
        assert len(reports) == 1
        assert reports[0].change_type == PeerEventChangeType.COLD_WARM

    def test_flicker_hot_without_stable_does_not_report_leave(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=15)
        hot = _status_changed(at="2026-09-15T19:00:00.000000Z", transition="WarmToHot")
        assert tracker.apply_event(hot) == []
        cool = _status_changed(at="2026-09-15T19:00:02.000000Z", transition="HotToCooling")
        assert tracker.apply_event(cool) == []

    def test_leave_after_reported_hot_is_immediate(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0)
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
        tracker = PeerTracker(peers, stable_seconds=0)
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
        tracker = PeerTracker(peers, stable_seconds=0)
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

    def test_handshake_enriches_peer_and_suppresses_ephemeral_port(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0)
        info = tracker.record_handshake(
            remote_addr="203.0.113.10",
            remote_port=45000,
            n2n_version=14,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingEnabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 15, 19, 0, 0, tzinfo=UTC),
        )
        assert info.remote_port == 0
        hot = _status_changed(at="2026-09-15T19:00:01.000000Z", transition="WarmToHot")
        reports = tracker.apply_event(hot)
        assert len(reports) == 1
        peer = reports[0].peer
        assert peer.n2n_version == 14
        assert peer.peer_sharing == "PeerSharingEnabled"
        assert peer.diffusion_mode == "InitiatorAndResponderDiffusionMode"
        assert peer.peras_support == "PerasUnsupported"

    def test_handshake_keeps_service_port(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0)
        info = tracker.record_handshake(
            remote_addr="203.0.113.10",
            remote_port=3001,
            n2n_version=15,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingDisabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 15, 19, 0, 0, tzinfo=UTC),
        )
        assert info.remote_port == 3001

    def test_diagnostic_counts_live_pending_reported(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=15)
        hot = _status_changed(at="2026-09-15T19:00:00.000000Z", transition="WarmToHot")
        assert tracker.apply_event(hot) == []
        diag = tracker.diagnostic_counts()
        assert diag["out_hot_live"] == 1
        assert diag["out_hot_pending"] == 1
        assert diag["out_hot_reported"] == 0
        reports = tracker.flush_stable(now=datetime(2026, 9, 15, 19, 0, 20, tzinfo=UTC))
        assert len(reports) == 1
        diag = tracker.diagnostic_counts()
        assert diag["out_hot_live"] == 1
        assert diag["out_hot_pending"] == 0
        assert diag["out_hot_reported"] == 1

    def test_prune_removes_idle_cold(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0)
        warm = _status_changed(at="2026-09-15T19:00:00.000000Z", transition="ColdToWarm")
        tracker.apply_event(warm)
        ev_cool = _status_changed(at="2026-09-15T19:00:01.000000Z", transition="WarmToCooling")
        tracker.apply_event(ev_cool)
        ev_cold = _status_changed(at="2026-09-15T19:00:02.000000Z", transition="CoolingToCold")
        tracker.apply_event(ev_cold)
        peer = peers["203.0.113.10"]
        stale = datetime.now(UTC) - timedelta(seconds=700)
        peer.last_updated = stale
        peer.last_signal = stale
        assert tracker.prune_cold(max_idle_seconds=600) == 1
        assert peers == {}


class TestHandshakeSuccessEvent:
    def test_parses_agreed_options(self):
        ev = HandshakeSuccessEvent.model_validate(
            {
                "at": "2026-09-18T13:34:31.901335436Z",
                "ns": "Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess",
                "data": {
                    "connectionHandler": {
                        "agreedOptions": {
                            "diffusionMode": "InitiatorAndResponderDiffusionMode",
                            "networkMagic": 764824073,
                            "peerSharing": "PeerSharingEnabled",
                            "perasSupport": "PerasUnsupported",
                            "query": False,
                        },
                        "kind": "HandshakeSuccess",
                        "versionNumber": 14,
                    },
                    "connectionId": {
                        "localAddress": {"address": "2a07:c700:0:700::91", "port": "6010"},
                        "remoteAddress": {"address": "2604:2dc0:202:200::50b", "port": "39206"},
                    },
                    "kind": "ConnectionHandler",
                },
                "sev": "Info",
                "thread": "83368",
                "host": "cn011",
            }
        )
        assert ev.remote_addr == "2604:2dc0:202:200::50b"
        assert ev.remote_port == 39206
        assert ev.n2n_version == 14
        assert ev.diffusion_mode == "InitiatorAndResponderDiffusionMode"
        assert ev.peer_sharing == "PeerSharingEnabled"
        assert ev.peras_support == "PerasUnsupported"


def _connection_lost(
    *,
    at: str,
    ns: str,
    remote_addr: str = "203.0.113.10",
    remote_port: int = 6000,
    context: str | None = "InboundError",
):
    data: dict = {
        "kind": "MuxErrored" if "MuxErrored" in ns else "ConnectionHandler",
        "connectionId": {
            "localAddress": {"address": "10.0.0.1", "port": "3001"},
            "remoteAddress": {"address": remote_addr, "port": str(remote_port)},
        },
    }
    if "ConnectionHandler.Error" in ns:
        data["connectionHandler"] = {
            "command": "ShutdownPeer",
            "context": context,
            "kind": "Error",
            "reason": "resource vanished",
        }
        data["kind"] = "ConnectionHandler"
    elif "ResponderErrored" in ns:
        data["kind"] = "ResponderErrored"
        data["reason"] = "ExceededTimeLimit"
    else:
        data["reason"] = "Connection reset by peer"

    return ConnectionLostEvent.model_validate(
        {
            "at": at,
            "ns": ns,
            "data": data,
            "sev": "Info",
            "thread": "1",
            "host": "test",
        }
    )


def _promoted_warm(*, at: str, remote_addr: str, remote_port: int = 6000):
    return PromotedPeerEvent.model_validate(
        {
            "at": at,
            "ns": "Net.InboundGovernor.Remote.PromotedToWarmRemote",
            "data": {
                "kind": "PromotedToWarmRemote",
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
    )


class TestConnectionLost:
    def test_mux_errored_parses_inbound_cold(self):
        ev = _connection_lost(
            at="2026-09-18T21:21:09.000000Z",
            ns="Net.InboundGovernor.Remote.MuxErrored",
        )
        assert ev.state == "Cold"
        assert ev.direction == "inbound"
        assert ev.change_type == PeerEventChangeType.WARM_COLD
        assert ev.remote_addr == "203.0.113.10"

    def test_handler_error_outbound_context(self):
        ev = _connection_lost(
            at="2026-09-18T21:21:09.000000Z",
            ns="Net.ConnectionManager.Remote.ConnectionHandler.Error",
            context="OutboundError",
        )
        assert ev.direction == "outbound"
        assert ev.state == "Cold"

    def test_mux_errored_clears_reported_inbound_hot(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0)
        warm = _promoted_warm(at="2026-09-18T21:00:00.000000Z", remote_addr="203.0.113.10")
        reports = tracker.apply_event(warm)
        assert len(reports) == 1
        assert reports[0].change_type == PeerEventChangeType.COLD_WARM
        hot = PromotedPeerEvent.model_validate(
            _promoted_hot(
                at="2026-09-18T21:00:01.000000Z",
                remote_addr="203.0.113.10",
                remote_port=6000,
            )
        )
        reports = tracker.apply_event(hot)
        assert reports[0].change_type == PeerEventChangeType.WARM_HOT
        assert peers["203.0.113.10"].state_inbound == PeerState.HOT

        lost = _connection_lost(
            at="2026-09-18T21:00:05.000000Z",
            ns="Net.InboundGovernor.Remote.MuxErrored",
        )
        leaves = tracker.apply_event(lost)
        assert len(leaves) == 1
        assert leaves[0].change_type == PeerEventChangeType.WARM_COLD
        assert peers["203.0.113.10"].state_inbound == PeerState.COLD
        diag = tracker.diagnostic_counts()
        assert diag["in_hot_live"] == 0
        assert diag["in_hot_reported"] == 0

    def test_reset_clears_peers_and_handshakes(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0)
        tracker.apply_event(
            _promoted_warm(at="2026-09-18T21:00:00.000000Z", remote_addr="203.0.113.10")
        )
        tracker.record_handshake(
            remote_addr="203.0.113.10",
            remote_port=6000,
            n2n_version=14,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingEnabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 18, 21, 0, 0, tzinfo=UTC),
        )
        assert tracker.reset() == 1
        assert peers == {}
        assert tracker.handshake_for("203.0.113.10") is None
        assert tracker.diagnostic_counts()["handshakes_cached"] == 0


class TestPresenceAndTtl:
    def test_first_seen_and_last_signal_on_enter(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0, signal_ttl_seconds=1800)
        t0 = "2026-09-19T00:00:00.000000Z"
        tracker.apply_event(_status_changed(at=t0, transition="ColdToWarm"))
        peer = peers["203.0.113.10"]
        assert peer.first_seen == datetime(2026, 9, 19, 0, 0, 0, tzinfo=UTC)
        assert peer.last_signal == peer.first_seen

        t1 = "2026-09-19T00:10:00.000000Z"
        tracker.apply_event(_status_changed(at=t1, transition="WarmToHot"))
        assert peer.first_seen == datetime(2026, 9, 19, 0, 0, 0, tzinfo=UTC)
        assert peer.last_signal == datetime(2026, 9, 19, 0, 10, 0, tzinfo=UTC)

    def test_touch_signal_from_header_keeps_peer_alive(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0, signal_ttl_seconds=1800)
        tracker.apply_event(
            _status_changed(at="2026-09-19T00:00:00.000000Z", transition="WarmToHot")
        )
        assert tracker.touch_signal(
            "203.0.113.10", datetime(2026, 9, 19, 0, 25, 0, tzinfo=UTC)
        )
        # 29 minutes after last peerevent but 4 min after header touch → still alive
        leaves = tracker.expire_stale(now=datetime(2026, 9, 19, 0, 29, 0, tzinfo=UTC))
        assert leaves == []
        assert peers["203.0.113.10"].state_outbound == PeerState.HOT

    def test_expire_stale_demotes_after_ttl(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0, signal_ttl_seconds=1800)
        reports = tracker.apply_event(
            _status_changed(at="2026-09-19T00:00:00.000000Z", transition="WarmToHot")
        )
        assert reports[0].change_type == PeerEventChangeType.WARM_HOT
        leaves = tracker.expire_stale(now=datetime(2026, 9, 19, 0, 30, 0, tzinfo=UTC))
        assert len(leaves) == 1
        assert leaves[0].change_type == PeerEventChangeType.WARM_COLD
        assert peers["203.0.113.10"].state_outbound == PeerState.COLD
        assert tracker.reported_peer_rows() == []

    def test_ttl_zero_disables(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0, signal_ttl_seconds=0)
        tracker.apply_event(
            _status_changed(at="2026-09-19T00:00:00.000000Z", transition="WarmToHot")
        )
        assert tracker.expire_stale(now=datetime(2026, 9, 19, 2, 0, 0, tzinfo=UTC)) == []
        assert peers["203.0.113.10"].state_outbound == PeerState.HOT

    def test_reported_rows_include_presence(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0, signal_ttl_seconds=1800)
        tracker.apply_event(
            _status_changed(at="2026-09-19T00:00:00.000000Z", transition="WarmToHot")
        )
        row = tracker.reported_peer_rows()[0]
        assert row["first_seen"].startswith("2026-09-19T00:00:00")
        assert row["last_signal"].startswith("2026-09-19T00:00:00")
