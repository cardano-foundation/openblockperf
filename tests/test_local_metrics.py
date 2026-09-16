"""Tests for local metrics JSON/Prometheus builders and reported peer rows."""

from datetime import UTC, datetime

import pytest

from openblockperf.local_metrics import build_peers_json, build_prometheus_text
from openblockperf.models.events import StatusChangedEvent
from openblockperf.peer_tracker import PeerEventsLevel, PeerTracker


def _warm_to_hot(at: str, remote: str = "203.0.113.10:3001") -> StatusChangedEvent:
    la, lp = "10.0.0.1:3001".rsplit(":", 1)
    ra, rp = remote.rsplit(":", 1)
    body = (
        f"WarmToHot (ConnectionId {{localAddress = {la}:{lp}, "
        f"remoteAddress = {ra}:{rp}}})"
    )
    return StatusChangedEvent.model_validate(
        {
            "at": at,
            "ns": "Net.PeerSelection.Actions.StatusChanged",
            "data": {"kind": "PeerStatusChanged", "peerStatusChangeType": body},
            "sev": "Info",
            "thread": "1",
            "host": "test",
        }
    )


class TestReportedPeerRows:
    def test_empty_until_reported(self):
        tracker = PeerTracker({}, level=PeerEventsLevel.MID, stable_seconds=15)
        tracker.apply_event(_warm_to_hot("2026-09-16T12:00:00Z"))
        assert tracker.reported_peer_rows() == []
        tracker.flush_stable(now=datetime(2026, 9, 16, 12, 0, 20, tzinfo=UTC))
        rows = tracker.reported_peer_rows()
        assert len(rows) == 1
        assert rows[0]["remote_addr"] == "203.0.113.10"
        assert rows[0]["directions"] == ["outbound"]
        assert rows[0]["state_outbound"] == "Hot"
        assert rows[0]["duplex"] is False


class TestLocalMetricsBuilders:
    def test_json_contains_counts_and_peers(self):
        tracker = PeerTracker({}, level=PeerEventsLevel.MID, stable_seconds=0)
        tracker.apply_event(_warm_to_hot("2026-09-16T12:00:00Z"))
        doc = build_peers_json(tracker, level="mid")
        assert doc["export"] == "reported"
        assert doc["counts"]["reported"]["out_hot"] == 1
        assert len(doc["peers"]) == 1

    def test_json_includes_relevance(self):
        from openblockperf.peer_relevance import PeerRelevanceTracker

        tracker = PeerTracker({}, level=PeerEventsLevel.MID, stable_seconds=0)
        tracker.apply_event(_warm_to_hot("2026-09-16T12:00:00Z"))
        rel = PeerRelevanceTracker()
        now = datetime.now(UTC)
        rel.record_header("203.0.113.10", 1, now)
        rel.record_header("198.51.100.1", 2, now)
        doc = build_peers_json(tracker, level="mid", relevance=rel)
        assert doc["peers"][0]["relevance"]["header_points"] == 10
        assert len(doc["relevance_orphans"]) == 1
        assert doc["relevance_orphans"][0]["remote_addr"] == "198.51.100.1"

    def test_prometheus_has_view_labels(self):
        tracker = PeerTracker({}, level=PeerEventsLevel.MID, stable_seconds=0)
        tracker.apply_event(_warm_to_hot("2026-09-16T12:00:00Z"))
        text = build_prometheus_text(tracker, level="mid")
        assert 'openblockperf_peers{view="reported",direction="outbound",state="hot"} 1' in text
        assert 'openblockperf_peer_events_level{level="mid"} 1' in text


class TestLocalMetricsHttp:
    @pytest.mark.asyncio
    async def test_peers_and_metrics_endpoints(self):
        import asyncio

        import httpx

        from openblockperf.local_metrics import LocalMetricsServer

        tracker = PeerTracker({}, level=PeerEventsLevel.MID, stable_seconds=0)
        tracker.apply_event(_warm_to_hot("2026-09-16T12:00:00Z"))
        server = LocalMetricsServer(
            tracker, bind="127.0.0.1", port=0, level="mid", relevance=None
        )
        task = asyncio.create_task(server.start())
        await asyncio.sleep(0.05)
        try:
            assert server._server is not None
            sock = server._server.sockets[0]
            port = sock.getsockname()[1]
            async with httpx.AsyncClient() as client:
                r = await client.get(f"http://127.0.0.1:{port}/peers")
                assert r.status_code == 200
                assert r.json()["counts"]["reported"]["out_hot"] == 1
                m = await client.get(f"http://127.0.0.1:{port}/metrics")
                assert m.status_code == 200
                assert "openblockperf_peers" in m.text
                h = await client.get(f"http://127.0.0.1:{port}/health")
                assert h.text.strip() == "ok"
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await server.stop()
