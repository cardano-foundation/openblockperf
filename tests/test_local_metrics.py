"""Tests for local metrics JSON/Prometheus builders and useful session rows."""

from datetime import UTC, datetime

import pytest

from openblockperf.local_metrics import build_peers_json, build_prometheus_text
from openblockperf.models.events import StatusChangedEvent
from openblockperf.peer_tracker import PeerTracker


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


class TestUsefulSessionRows:
    def test_empty_until_hot_or_stable_warm(self):
        tracker = PeerTracker({}, stable_seconds=15)
        tracker.apply_event(_warm_to_hot("2026-09-16T12:00:00Z"))
        rows = tracker.reported_peer_rows()
        assert len(rows) == 1
        assert rows[0]["remote_addr"] == "203.0.113.10"
        assert rows[0]["outbound_temperature"] == "Hot"
        assert "duplex" not in rows[0]


class TestLocalMetricsBuilders:
    def test_json_contains_counts_and_peers(self):
        tracker = PeerTracker({}, stable_seconds=0)
        tracker.apply_event(_warm_to_hot("2026-09-16T12:00:00Z"))
        doc = build_peers_json(tracker)
        assert doc["export"] == "useful"
        assert doc["counts"]["useful"] == 1
        assert doc["counts"]["out_hot"] == 1
        assert "duplex" not in doc["counts"]
        assert len(doc["peers"]) == 1

    def test_json_all_open_export(self):
        tracker = PeerTracker({}, stable_seconds=15)
        body = "ColdToWarm (Just 10.0.0.1:3001) 203.0.113.10:3001"
        warm = StatusChangedEvent.model_validate(
            {
                "at": "2026-09-16T12:00:00Z",
                "ns": "Net.PeerSelection.Actions.StatusChanged",
                "data": {"kind": "PeerStatusChanged", "peerStatusChangeType": body},
                "sev": "Info",
                "thread": "1",
                "host": "test",
            }
        )
        tracker.apply_event(warm)
        useful = build_peers_json(tracker)
        assert useful["export"] == "useful"
        assert useful["peers"] == []
        all_open = build_peers_json(tracker, include_all_open=True)
        assert all_open["export"] == "open"
        assert len(all_open["peers"]) == 1

    def test_json_includes_relevance(self):
        from openblockperf.peer_relevance import PeerRelevanceTracker

        tracker = PeerTracker({}, stable_seconds=0)
        tracker.apply_event(_warm_to_hot("2026-09-16T12:00:00Z"))
        rel = PeerRelevanceTracker()
        now = datetime.now(UTC)
        rel.record_header("203.0.113.10", 1, now)
        rel.record_header("198.51.100.1", 2, now)
        doc = build_peers_json(tracker, relevance=rel)
        assert doc["peers"][0]["relevance"]["header_points"] == 10
        assert len(doc["relevance_orphans"]) == 1
        assert doc["relevance_orphans"][0]["remote_addr"] == "198.51.100.1"

    def test_prometheus_has_session_gauges(self):
        tracker = PeerTracker({}, stable_seconds=0)
        tracker.apply_event(_warm_to_hot("2026-09-16T12:00:00Z"))
        text = build_prometheus_text(tracker)
        assert 'openblockperf_session_temperature{track="outbound",state="hot"} 1' in text
        assert "openblockperf_sessions_useful 1" in text
        assert "openblockperf_node_generation" in text
        assert "openblockperf_handshakes_cached" in text
        assert "openblockperf_duplex" not in text


class TestLocalMetricsHttp:
    @pytest.mark.asyncio
    async def test_peers_and_metrics_endpoints(self):
        import asyncio

        import httpx

        from openblockperf.local_metrics import LocalMetricsServer

        tracker = PeerTracker({}, stable_seconds=0)
        tracker.apply_event(_warm_to_hot("2026-09-16T12:00:00Z"))
        server = LocalMetricsServer(tracker, bind="127.0.0.1", port=0, relevance=None)
        task = asyncio.create_task(server.start())
        await asyncio.sleep(0.05)
        try:
            assert server._server is not None
            sock = server._server.sockets[0]
            port = sock.getsockname()[1]
            async with httpx.AsyncClient() as client:
                r = await client.get(f"http://127.0.0.1:{port}/peers")
                assert r.status_code == 200
                assert r.json()["counts"]["useful"] == 1
                m = await client.get(f"http://127.0.0.1:{port}/metrics")
                assert m.status_code == 200
                assert "openblockperf_sessions_open" in m.text
                h = await client.get(f"http://127.0.0.1:{port}/health")
                assert h.text.strip() == "ok"
                all_r = await client.get(f"http://127.0.0.1:{port}/peers?all=1")
                assert all_r.json()["export"] == "open"
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await server.stop()
