"""Tests for Amaru peer-session v0 parsing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openblockperf.amaru import (
    AmaruPeerBridge,
    is_amaru_message,
    parse_amaru_peer_action,
    parse_peer_hostport,
)
from openblockperf.errors import UnknowEventNameSpaceError
from openblockperf.models.peer import CloseReason, EventRole, PeerState
from openblockperf.peer_tracker import PeerTracker


def _line(message: str, *, ts: str = "2026-09-22T11:55:29.533558Z", **fields) -> dict:
    return {
        "timestamp": ts,
        "level": "INFO",
        "target": "amaru::protocols",
        "fields": {"message": message, **fields},
    }


@pytest.fixture
def bridge() -> AmaruPeerBridge:
    tracker = PeerTracker({}, stable_seconds=0, signal_ttl_seconds=0)
    return AmaruPeerBridge(tracker, default_local_addr="0.0.0.0", default_local_port=5001)


class TestParseHelpers:
    def test_is_amaru_vs_haskell(self):
        assert is_amaru_message(_line("manager.peer.handshake_completed", peer="1.2.3.4:3001"))
        assert not is_amaru_message(
            {"at": "2025-01-01T00:00:00Z", "ns": "ChainSync.Client.DownloadedHeader", "data": {}}
        )

    def test_parse_ipv4_and_ipv6(self):
        assert parse_peer_hostport("13.41.234.173:3001") == ("13.41.234.173", 3001)
        assert parse_peer_hostport("[2001:db8::1]:3001") == ("2001:db8::1", 3001)

    def test_unknown_message_returns_none(self):
        assert parse_amaru_peer_action(_line("tip.adopt", block_height=1)) is None


class TestAmaruPeerBridge:
    def test_we_dialed_diffusion_lifecycle(self, bridge: AmaruPeerBridge):
        roles: list[str] = []

        def collect(msg: dict):
            for r in bridge.apply_message(msg):
                roles.append(r.event_role.value)

        collect(_line("peer_selection.connect_initial", ts="2026-09-22T11:55:29.439887Z"))
        collect(
            _line(
                "manager.listen.started",
                ts="2026-09-22T11:55:29.440064Z",
                listen_addr="0.0.0.0:5001",
            )
        )
        assert bridge.listen_port == 5001
        # Debounced: one node_restart from the start burst
        assert roles.count("node_restart") == 1

        collect(_line("manager.peer.connect", peer="13.41.234.173:3001"))
        collect(
            _line(
                "manager.peer.connected",
                peer="13.41.234.173:3001",
                conn_id=0,
            )
        )
        collect(
            _line(
                "manager.peer.handshake_completed",
                peer="13.41.234.173:3001",
                conn_id=0,
                advertisable=False,
                full_duplex=True,
            )
        )
        assert roles[-1] == "open"
        session = bridge.tracker._find_open("0.0.0.0", 5001, "13.41.234.173", 3001)
        assert session is not None
        assert session.we_dialed is True

        collect(
            _line(
                "manager.peer.local_use_applied",
                peer="13.41.234.173:3001",
                conn_id=0,
                local_use="diffusion",
            )
        )
        assert roles[-1] == "temperature"
        assert session.outbound_temperature == PeerState.HOT
        assert session.useful is True

        collect(
            _line(
                "peer_selection.peer.demoted",
                peer="13.41.234.173:3001",
                conn_id=0,
                reason="churn",
            )
        )
        assert session.outbound_temperature == PeerState.WARM

        collect(
            _line(
                "manager.peer.connection_died_handled",
                peer="13.41.234.173:3001",
                conn_id=0,
                outcome="peer_removed",
                role="initiator",
            )
        )
        assert roles[-1] == "close"
        assert bridge.tracker.diagnostic_counts()["open"] == 0
        closed = list(bridge.tracker._closed.values())
        assert closed[-1].close_reason == CloseReason.DEMOTED_COLD

    def test_inbound_idle_hs_then_die(self, bridge: AmaruPeerBridge):
        bridge.apply_message(
            _line(
                "manager.listen.started",
                listen_addr="0.0.0.0:5001",
            )
        )
        reports = bridge.apply_message(
            _line(
                "manager.peer.handshake_completed",
                peer="70.80.201.180:4555",
                conn_id=8,
                advertisable=True,
                full_duplex=True,
            )
        )
        assert len(reports) == 1
        assert reports[0].event_role == EventRole.OPEN
        assert reports[0].we_dialed is not True

        # none → no temperature submit
        more = bridge.apply_message(
            _line(
                "manager.peer.local_use_applied",
                peer="70.80.201.180:4555",
                conn_id=8,
                local_use="none",
            )
        )
        assert more == []

        child = bridge.apply_message(
            _line(
                "connection.child_died",
                peer="70.80.201.180:4555",
                conn_id=8,
                child="Mux",
            )
        )
        assert len(child) == 1
        assert child[0].event_role == EventRole.CLOSE
        assert child[0].close_reason == CloseReason.IG_MUX_ERROR

        # died_handled after child_died → duplicate ignored
        dup = bridge.apply_message(
            _line(
                "manager.peer.connection_died_handled",
                peer="70.80.201.180:4555",
                conn_id=8,
                outcome="peer_removed",
                role="responder",
            )
        )
        assert dup == []

    def test_handshake_child_died_without_open_is_skipped(self, bridge: AmaruPeerBridge):
        reports = bridge.apply_message(
            _line(
                "connection.child_died",
                peer="144.76.1.222:46488",
                conn_id=9,
                child="Handshake",
            )
        )
        assert reports == []
        assert bridge.tracker.diagnostic_counts()["open"] == 0

    def test_inbound_promoted_to_diffusion(self, bridge: AmaruPeerBridge):
        bridge.apply_message(
            _line("manager.listen.started", listen_addr="0.0.0.0:5001")
        )
        bridge.apply_message(
            _line(
                "manager.peer.handshake_completed",
                peer="70.80.201.180:4555",
                conn_id=8,
            )
        )
        bridge.apply_message(
            _line(
                "manager.peer.local_use_applied",
                peer="70.80.201.180:4555",
                conn_id=8,
                local_use="none",
            )
        )
        hot = bridge.apply_message(
            _line(
                "manager.peer.local_use_applied",
                peer="70.80.201.180:4555",
                conn_id=8,
                local_use="Diffusion",
            )
        )
        assert len(hot) == 1
        assert hot[0].event_role == EventRole.TEMPERATURE
        session = bridge.tracker._find_open("0.0.0.0", 5001, "70.80.201.180", 4555)
        assert session is not None
        assert session.outbound_temperature == PeerState.HOT


@pytest.mark.asyncio
async def test_handler_routes_amaru_auto(default_settings):
    from openblockperf.handler import EventHandler

    settings = default_settings.model_copy(update={"node_kind": "auto", "local_port": 5001})
    api = MagicMock()
    api.submit_peer_report = AsyncMock()
    handler = EventHandler({}, {}, api, settings)

    await handler.handle_message(
        _line("manager.listen.started", listen_addr="0.0.0.0:5001")
    )
    await handler.handle_message(
        _line(
            "manager.peer.handshake_completed",
            peer="1.2.3.4:3001",
            conn_id=0,
        )
    )
    assert api.submit_peer_report.await_count >= 1

    with pytest.raises(UnknowEventNameSpaceError):
        await handler.handle_message(
            {
                "timestamp": "2026-09-22T12:10:24.564865Z",
                "level": "INFO",
                "target": "amaru::consensus",
                "fields": {
                    "message": "tip.adopt",
                    "block_height": 1,
                    "header_hash": "abc",
                    "slot": 1,
                },
            }
        )
