"""Tests for connection-session tracking, epoch, and HS-MuxError / restart patterns."""

from datetime import UTC, datetime, timedelta

from openblockperf.models.events import (
    ConnectionLostEvent,
    HandshakeSuccessEvent,
    NetworkShutdownEvent,
    NodeEpochStartEvent,
    PeerEventChangeType,
    PeerSelectionDoneEvent,
    PromotedPeerEvent,
    StatusChangedEvent,
)
from openblockperf.models.peer import CloseReason, EventRole, PeerDirection
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


def _promoted(
    *,
    at: str,
    remote_addr: str,
    remote_port: int,
    hot: bool = False,
    local_addr: str = "10.0.0.1",
    local_port: int = 3001,
) -> PromotedPeerEvent:
    kind = "PromotedToHotRemote" if hot else "PromotedToWarmRemote"
    return PromotedPeerEvent.model_validate(
        {
            "at": at,
            "ns": f"Net.InboundGovernor.Remote.{kind}",
            "data": {
                "kind": kind,
                "connectionId": {
                    "localAddress": {"address": local_addr, "port": str(local_port)},
                    "remoteAddress": {"address": remote_addr, "port": str(remote_port)},
                },
                "result": {"kind": "OperationSuccess"},
            },
            "sev": "Info",
            "thread": "1",
            "host": "test",
        }
    )


def _connection_lost(
    *,
    at: str,
    ns: str,
    remote_addr: str = "203.0.113.10",
    remote_port: int = 6000,
    context: str | None = "InboundError",
    local_addr: str = "10.0.0.1",
    local_port: int = 3001,
):
    data: dict = {
        "kind": "MuxErrored" if "MuxErrored" in ns else "ConnectionHandler",
        "connectionId": {
            "localAddress": {"address": local_addr, "port": str(local_port)},
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


def _hs(
    *,
    at: str,
    remote_addr: str,
    remote_port: int,
    local_addr: str = "10.0.0.1",
    local_port: int = 3001,
    version: int = 14,
) -> HandshakeSuccessEvent:
    return HandshakeSuccessEvent.model_validate(
        {
            "at": at,
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
                    "versionNumber": version,
                },
                "connectionId": {
                    "localAddress": {"address": local_addr, "port": str(local_port)},
                    "remoteAddress": {"address": remote_addr, "port": str(remote_port)},
                },
                "kind": "ConnectionHandler",
            },
            "sev": "Info",
            "thread": "1",
            "host": "test",
        }
    )


def _ns_event(cls, *, at: str, ns: str):
    return cls.model_validate(
        {
            "at": at,
            "ns": ns,
            "data": {"kind": "test"},
            "sev": "Info",
            "thread": "1",
            "host": "test",
        }
    )


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


class TestHandshakeSuccessEvent:
    def test_parses_agreed_options(self):
        ev = _hs(
            at="2026-09-18T13:34:31.901335Z",
            remote_addr="2604:2dc0:202:200::50b",
            remote_port=39206,
            local_addr="2a07:c700:0:700::91",
            local_port=6010,
        )
        assert ev.remote_addr == "2604:2dc0:202:200::50b"
        assert ev.remote_port == 39206
        assert ev.n2n_version == 14
        assert ev.diffusion_mode == "InitiatorAndResponderDiffusionMode"
        assert ev.peer_sharing == "PeerSharingEnabled"
        assert ev.peras_support == "PerasUnsupported"


class TestHsMuxErrorPattern:
    """Unthrottled 2h dominant burst: HS -> Warm -> Hot -> MuxErrored (+ Handler.Error)."""

    def test_open_hot_close_one_session(self):
        tracker = PeerTracker({}, stable_seconds=15)
        ev = _hs(at="2026-09-18T15:04:31.000000Z", remote_addr="97.70.59.151", remote_port=54321)
        opens = tracker.open_handshake(
            local_addr=ev.local_addr,
            local_port=ev.local_port,
            remote_addr=ev.remote_addr,
            remote_port=ev.remote_port,
            n2n_version=ev.n2n_version,
            diffusion_mode=ev.diffusion_mode,
            peer_sharing=ev.peer_sharing,
            peras_support=ev.peras_support,
            at=ev.at,
            ns=ev.ns,
        )
        assert len(opens) == 1
        assert opens[0].event_role == EventRole.OPEN
        assert opens[0].change_type == PeerEventChangeType.COLD_WARM
        assert opens[0].session_id
        sid = opens[0].session_id

        warm = tracker.apply_event(
            _promoted(
                at="2026-09-18T15:04:32.000000Z",
                remote_addr="97.70.59.151",
                remote_port=54321,
            )
        )
        assert warm == []

        hot = tracker.apply_event(
            _promoted(
                at="2026-09-18T15:04:32.100000Z",
                remote_addr="97.70.59.151",
                remote_port=54321,
                hot=True,
            )
        )
        assert len(hot) == 1
        assert hot[0].event_role == EventRole.TEMPERATURE
        assert hot[0].change_type == PeerEventChangeType.WARM_HOT
        assert hot[0].session_id == sid
        assert hot[0].direction == PeerDirection.INBOUND

        lost = tracker.apply_event(
            _connection_lost(
                at="2026-09-18T15:04:33.000000Z",
                ns="Net.InboundGovernor.Remote.MuxErrored",
                remote_addr="97.70.59.151",
                remote_port=54321,
            )
        )
        assert len(lost) == 1
        assert lost[0].event_role == EventRole.CLOSE
        assert lost[0].close_reason == CloseReason.IG_MUX_ERROR
        assert lost[0].session_id == sid

        dup = tracker.apply_event(
            _connection_lost(
                at="2026-09-18T15:04:33.001000Z",
                ns="Net.ConnectionManager.Remote.ConnectionHandler.Error",
                remote_addr="97.70.59.151",
                remote_port=54321,
            )
        )
        assert dup == []
        assert tracker.diagnostic_counts()["open"] == 0
        assert tracker.diagnostic_counts()["closed_ig_mux_error"] == 1

    def test_ephemeral_port_submitted_as_zero(self):
        tracker = PeerTracker({}, stable_seconds=0)
        reports = tracker.open_handshake(
            local_addr="10.0.0.1",
            local_port=3001,
            remote_addr="198.51.100.7",
            remote_port=54321,
            n2n_version=14,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingEnabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 18, 15, 0, 0, tzinfo=UTC),
            ns="Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess",
        )
        assert reports[0].remote_port == 0

    def test_listen_port_kept(self):
        tracker = PeerTracker({}, stable_seconds=0)
        reports = tracker.open_handshake(
            local_addr="10.0.0.1",
            local_port=3001,
            remote_addr="198.51.100.7",
            remote_port=3001,
            n2n_version=15,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingDisabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 18, 15, 0, 0, tzinfo=UTC),
            ns="Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess",
        )
        assert reports[0].remote_port == 3001


class TestWeDialedOutbound:
    def test_cold_to_warm_marks_we_dialed_and_skips_duplicate_open(self):
        tracker = PeerTracker({}, stable_seconds=0)
        hs = tracker.open_handshake(
            local_addr="10.0.0.1",
            local_port=3001,
            remote_addr="10.10.193.98",
            remote_port=6000,
            n2n_version=15,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingEnabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 18, 21, 29, 25, tzinfo=UTC),
            ns="Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess",
        )
        assert hs[0].event_role == EventRole.OPEN
        follow = tracker.apply_event(
            _status_changed(
                at="2026-09-18T21:29:25.116000Z",
                transition="ColdToWarm",
                local="10.0.0.1:3001",
                remote="10.10.193.98:6000",
            )
        )
        assert follow == []
        hot = tracker.apply_event(
            _status_changed(
                at="2026-09-18T21:29:25.117000Z",
                transition="WarmToHot",
                local="10.0.0.1:3001",
                remote="10.10.193.98:6000",
            )
        )
        assert len(hot) == 1
        assert hot[0].we_dialed is True
        assert hot[0].direction == PeerDirection.OUTBOUND
        assert hot[0].change_type == PeerEventChangeType.WARM_HOT

    def test_cooling_to_cold_closes_planned(self):
        tracker = PeerTracker({}, stable_seconds=0)
        tracker.apply_event(_status_changed(at="2026-09-15T19:00:00.000000Z", transition="ColdToWarm"))
        tracker.apply_event(_status_changed(at="2026-09-15T19:00:01.000000Z", transition="WarmToHot"))
        cool = tracker.apply_event(
            _status_changed(at="2026-09-15T19:00:05.000000Z", transition="WarmToCooling")
        )
        assert cool == []
        leaves = tracker.apply_event(
            _status_changed(at="2026-09-15T19:00:06.000000Z", transition="CoolingToCold")
        )
        assert len(leaves) == 1
        assert leaves[0].close_reason == CloseReason.COOLING_TO_COLD
        assert leaves[0].event_role == EventRole.CLOSE


class TestUsefulFlag:
    def test_hot_is_useful_immediately(self):
        tracker = PeerTracker({}, stable_seconds=15)
        tracker.apply_event(_status_changed(at="2026-09-16T12:00:00Z", transition="WarmToHot"))
        assert tracker.useful_session_rows()[0]["outbound_temperature"] == "Hot"
        assert tracker.useful_session_rows()[0]["useful"] is True

    def test_warm_waits_for_stable_seconds(self):
        tracker = PeerTracker({}, stable_seconds=15)
        tracker.apply_event(_status_changed(at="2026-09-16T12:00:00Z", transition="ColdToWarm"))
        assert tracker.useful_session_rows() == []
        tracker.flush_stable(now=datetime(2026, 9, 16, 12, 0, 10, tzinfo=UTC))
        assert tracker.useful_session_rows() == []
        tracker.flush_stable(now=datetime(2026, 9, 16, 12, 0, 20, tzinfo=UTC))
        rows = tracker.useful_session_rows()
        assert len(rows) == 1
        assert rows[0]["outbound_temperature"] == "Warm"

    def test_all_open_includes_short_warm(self):
        tracker = PeerTracker({}, stable_seconds=15)
        tracker.apply_event(_status_changed(at="2026-09-16T12:00:00Z", transition="ColdToWarm"))
        assert len(tracker.all_open_session_rows()) == 1
        assert tracker.all_open_session_rows()[0]["useful"] is False


class TestEpochRestart:
    """50-minute capture: Stopped/Shutdown then Started, counters from zero."""

    def test_stop_closes_then_start_increments_epoch(self):
        tracker = PeerTracker({}, stable_seconds=0)
        tracker.apply_event(_status_changed(at="2026-09-18T21:27:00Z", transition="WarmToHot"))
        assert tracker.diagnostic_counts()["open"] == 1
        stop = _ns_event(
            NetworkShutdownEvent,
            at="2026-09-18T21:28:07.000000Z",
            ns="Net.ConnectionManager.Remote.Shutdown",
        )
        closes = tracker.on_network_stop(stop.at, ns=stop.ns)
        assert len(closes) == 1
        assert closes[0].close_reason == CloseReason.NODE_EPOCH
        assert tracker.diagnostic_counts()["open"] == 0
        assert tracker.epoch_id == 0

        start = _ns_event(
            NodeEpochStartEvent,
            at="2026-09-18T21:29:25.000000Z",
            ns="Net.Server.Remote.Started",
        )
        reports = tracker.on_network_start(start.at, ns=start.ns)
        roles = [r.event_role for r in reports]
        assert EventRole.EPOCH in roles
        assert tracker.epoch_id == 1
        hs = tracker.open_handshake(
            local_addr="10.10.193.91",
            local_port=6010,
            remote_addr="10.10.193.98",
            remote_port=6000,
            n2n_version=15,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingEnabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 18, 21, 29, 25, tzinfo=UTC),
            ns="Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess",
        )
        assert hs[0].epoch_id == 1

    def test_local_and_remote_started_debounce(self):
        tracker = PeerTracker({}, stable_seconds=0)
        t0 = datetime(2026, 9, 18, 21, 29, 25, 114728, tzinfo=UTC)
        first = tracker.on_network_start(t0, ns="Net.Server.Local.Started")
        assert len(first) == 1
        assert tracker.epoch_id == 1
        t1 = datetime(2026, 9, 18, 21, 29, 25, 114876, tzinfo=UTC)
        second = tracker.on_network_start(t1, ns="Net.Server.Remote.Started")
        assert second == []
        assert tracker.epoch_id == 1

    def test_start_without_stop_still_closes_leftovers(self):
        tracker = PeerTracker({}, stable_seconds=0)
        tracker.apply_event(_status_changed(at="2026-09-18T21:27:00Z", transition="WarmToHot"))
        reports = tracker.on_network_start(
            datetime(2026, 9, 18, 21, 29, 25, tzinfo=UTC),
            ns="Net.Server.Remote.Started",
        )
        assert any(r.event_role == EventRole.CLOSE for r in reports)
        assert any(r.event_role == EventRole.EPOCH for r in reports)
        assert tracker.diagnostic_counts()["open"] == 0


class TestConnectionLost:
    def test_mux_errored_parses_inbound_cold(self):
        ev = _connection_lost(
            at="2026-09-18T21:21:09.000000Z",
            ns="Net.InboundGovernor.Remote.MuxErrored",
        )
        assert ev.state == "Cold"
        assert ev.direction == "inbound"
        assert ev.change_type == PeerEventChangeType.WARM_COLD

    def test_handler_error_outbound_context(self):
        ev = _connection_lost(
            at="2026-09-18T21:21:09.000000Z",
            ns="Net.ConnectionManager.Remote.ConnectionHandler.Error",
            context="OutboundError",
        )
        assert ev.direction == "outbound"
        assert ev.state == "Cold"


class TestHandshakeCache:
    def test_record_handshake_enriches_later_statuschanged(self):
        peers = {}
        tracker = PeerTracker(peers, stable_seconds=0)
        tracker.record_handshake(
            remote_addr="203.0.113.10",
            remote_port=3001,
            n2n_version=14,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingEnabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 15, 19, 0, 0, tzinfo=UTC),
            local_addr="10.0.0.1",
            local_port=3001,
        )
        reports = tracker.apply_event(
            _status_changed(at="2026-09-15T19:00:01.000000Z", transition="WarmToHot")
        )
        assert reports[0].peer.n2n_version == 14
        info = tracker.handshake_for("203.0.113.10")
        assert info is not None
        assert info.remote_port == 3001

    def test_reset_clears_open_sessions(self):
        tracker = PeerTracker({}, stable_seconds=0)
        tracker.apply_event(_promoted(at="2026-09-18T21:00:00Z", remote_addr="203.0.113.10", remote_port=6000))
        assert tracker.reset() == 1
        assert tracker.diagnostic_counts()["open"] == 0
        assert tracker.peers == {}


class TestPresenceAndTtl:
    def test_expire_stale_closes_after_ttl(self):
        tracker = PeerTracker({}, stable_seconds=0, signal_ttl_seconds=1800)
        tracker.apply_event(
            _status_changed(at="2026-09-19T00:00:00.000000Z", transition="WarmToHot")
        )
        leaves = tracker.expire_stale(now=datetime(2026, 9, 19, 0, 30, 0, tzinfo=UTC))
        assert len(leaves) == 1
        assert leaves[0].close_reason == CloseReason.TTL
        assert tracker.reported_peer_rows() == []

    def test_touch_signal_keeps_session_alive(self):
        tracker = PeerTracker({}, stable_seconds=0, signal_ttl_seconds=1800)
        tracker.apply_event(
            _status_changed(at="2026-09-19T00:00:00.000000Z", transition="WarmToHot")
        )
        assert tracker.touch_signal("203.0.113.10", datetime(2026, 9, 19, 0, 25, 0, tzinfo=UTC))
        leaves = tracker.expire_stale(now=datetime(2026, 9, 19, 0, 29, 0, tzinfo=UTC))
        assert leaves == []
        assert tracker.diagnostic_counts()["open"] == 1

    def test_ttl_zero_disables(self):
        tracker = PeerTracker({}, stable_seconds=0, signal_ttl_seconds=0)
        tracker.apply_event(
            _status_changed(at="2026-09-19T00:00:00.000000Z", transition="WarmToHot")
        )
        assert tracker.expire_stale(now=datetime(2026, 9, 19, 2, 0, 0, tzinfo=UTC)) == []

    def test_prune_removes_idle_closed(self):
        tracker = PeerTracker({}, stable_seconds=0)
        tracker.apply_event(_status_changed(at="2026-09-15T19:00:00Z", transition="ColdToWarm"))
        tracker.apply_event(_status_changed(at="2026-09-15T19:00:02Z", transition="CoolingToCold"))
        peer = tracker.peers["203.0.113.10"]
        stale = datetime.now(UTC) - timedelta(seconds=700)
        peer.last_updated = stale
        peer.last_signal = stale
        for session in tracker._closed.values():
            session.closed_at = stale
        assert tracker.prune_cold(max_idle_seconds=600) == 1
        assert tracker.peers == {}


class TestTwoConnectionsSameIp:
    def test_listen_and_ephemeral_are_separate_sessions(self):
        tracker = PeerTracker({}, stable_seconds=0)
        tracker.open_handshake(
            local_addr="10.0.0.1",
            local_port=3001,
            remote_addr="198.51.100.7",
            remote_port=3001,
            n2n_version=14,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingEnabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 18, 15, 0, 0, tzinfo=UTC),
            ns="hs",
        )
        tracker.open_handshake(
            local_addr="10.0.0.1",
            local_port=3001,
            remote_addr="198.51.100.7",
            remote_port=45000,
            n2n_version=14,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingEnabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 18, 15, 0, 1, tzinfo=UTC),
            ns="hs",
        )
        assert tracker.diagnostic_counts()["open"] == 2
        rows = tracker.all_open_session_rows()
        ports = sorted(r["remote_port"] for r in rows)
        assert ports == [0, 3001]


def _selection_done(
    *,
    at: str,
    ns: str,
    remote_addr: str = "88.211.220.4",
    remote_port: int = 3001,
    extra: dict | None = None,
) -> PeerSelectionDoneEvent:
    kind = ns.rsplit(".", 1)[-1]
    data = {
        "kind": kind,
        "peer": {"address": remote_addr, "port": str(remote_port)},
    }
    if extra:
        data.update(extra)
    return PeerSelectionDoneEvent.model_validate(
        {
            "at": at,
            "ns": ns,
            "data": data,
            "sev": "Info",
            "thread": "211",
            "host": "test",
        }
    )


class TestPeerSelectionDoneParse:
    def test_promote_warm_done_is_outbound_hot(self):
        ev = _selection_done(
            at="2026-09-15T19:07:40.421097967Z",
            ns="Net.PeerSelection.Selection.PromoteWarmDone",
            extra={"actualActive": 20, "targetActive": 20},
        )
        assert ev.state == "Hot"
        assert ev.direction == "outbound"
        assert ev.change_type == PeerEventChangeType.WARM_HOT
        assert ev.remote_addr == "88.211.220.4"
        assert ev.remote_port == 3001
        assert ev.local_port == 0

    def test_promote_cold_done_ipv6(self):
        ev = _selection_done(
            at="2026-09-20T10:00:00.000000Z",
            ns="Net.PeerSelection.Selection.PromoteColdDone",
            remote_addr="2a01:2a8:a23d:16::17",
            remote_port=3001,
            extra={"actualEstablished": 27, "targetEstablished": 30},
        )
        assert ev.state == "Warm"
        assert ev.local_addr == "::"
        assert ev.remote_addr == "2a01:2a8:a23d:16::17"


class TestOutboundSelectionDone:
    def test_promote_cold_then_warm_marks_we_dialed_hot(self):
        tracker = PeerTracker({}, stable_seconds=15)
        tracker.open_handshake(
            local_addr="10.0.0.1",
            local_port=3001,
            remote_addr="88.211.220.4",
            remote_port=3001,
            n2n_version=14,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingEnabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 15, 19, 7, 40, tzinfo=UTC),
            ns="hs",
        )
        follow = tracker.apply_event(
            _selection_done(
                at="2026-09-15T19:07:40.420000Z",
                ns="Net.PeerSelection.Selection.PromoteColdDone",
                extra={"actualEstablished": 19, "targetEstablished": 20},
            )
        )
        assert follow == []
        hot = tracker.apply_event(
            _selection_done(
                at="2026-09-15T19:07:40.421000Z",
                ns="Net.PeerSelection.Selection.PromoteWarmDone",
                extra={"actualActive": 20, "targetActive": 20},
            )
        )
        assert len(hot) == 1
        assert hot[0].we_dialed is True
        assert hot[0].direction == PeerDirection.OUTBOUND
        assert hot[0].change_type == PeerEventChangeType.WARM_HOT
        counts = tracker.diagnostic_counts()
        assert counts["out_hot"] == 1
        assert counts["useful"] == 1
        row = tracker.useful_session_rows()[0]
        assert row["we_dialed"] is True
        assert row["outbound_temperature"] == "Hot"

    def test_demote_warm_done_closes_planned(self):
        tracker = PeerTracker({}, stable_seconds=0)
        tracker.apply_event(
            _selection_done(
                at="2026-09-15T19:00:00.000000Z",
                ns="Net.PeerSelection.Selection.PromoteColdDone",
            )
        )
        leaves = tracker.apply_event(
            _selection_done(
                at="2026-09-15T19:00:10.000000Z",
                ns="Net.PeerSelection.Selection.DemoteWarmDone",
                extra={"actualEstablished": 19, "targetEstablished": 20},
            )
        )
        assert len(leaves) == 1
        assert leaves[0].close_reason == CloseReason.COOLING_TO_COLD
        assert tracker.diagnostic_counts()["open"] == 0


class TestOutboundClientFromHeader:
    def test_header_orphan_opens_we_dialed_hot_session(self):
        tracker = PeerTracker({}, stable_seconds=15)
        reports = tracker.note_outbound_client(
            local_addr="172.0.118.125",
            local_port=30002,
            remote_addr="5.161.57.109",
            remote_port=3001,
            at=datetime(2026, 9, 20, 9, 0, 0, tzinfo=UTC),
            ns="ChainSync.Client.DownloadedHeader",
        )
        roles = [r.event_role for r in reports]
        assert EventRole.OPEN in roles
        assert EventRole.TEMPERATURE in roles
        row = tracker.useful_session_rows()[0]
        assert row["remote_addr"] == "5.161.57.109"
        assert row["we_dialed"] is True
        assert row["outbound_temperature"] == "Hot"
        assert tracker.diagnostic_counts()["out_hot"] == 1

    def test_header_does_not_merge_onto_inbound_ephemeral_session(self):
        tracker = PeerTracker({}, stable_seconds=0)
        tracker.open_handshake(
            local_addr="10.0.0.1",
            local_port=3001,
            remote_addr="5.161.57.109",
            remote_port=45000,
            n2n_version=14,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
            peer_sharing="PeerSharingEnabled",
            peras_support="PerasUnsupported",
            at=datetime(2026, 9, 20, 9, 0, 0, tzinfo=UTC),
            ns="hs",
        )
        tracker.apply_event(
            _promoted(
                at="2026-09-20T09:00:01.000000Z",
                remote_addr="5.161.57.109",
                remote_port=45000,
                hot=True,
            )
        )
        tracker.note_outbound_client(
            local_addr="10.0.0.1",
            local_port=3001,
            remote_addr="5.161.57.109",
            remote_port=3001,
            at=datetime(2026, 9, 20, 9, 0, 2, tzinfo=UTC),
            ns="ChainSync.Client.DownloadedHeader",
        )
        assert tracker.diagnostic_counts()["open"] == 2
        assert tracker.diagnostic_counts()["out_hot"] == 1
        assert tracker.diagnostic_counts()["ig_hot"] == 1

