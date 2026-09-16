"""Tests for sliding-window peer relevance scoring."""

from datetime import UTC, datetime

from openblockperf.peer_relevance import (
    BODY_POINTS,
    HEADER_POINTS,
    PeerRelevanceTracker,
)


class TestPeerRelevanceTracker:
    def test_header_ranks_and_body(self):
        t = PeerRelevanceTracker()
        at = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
        assert t.record_header("1.1.1.1", 1, at) == HEADER_POINTS[1]
        assert t.record_header("2.2.2.2", 2, at) == HEADER_POINTS[2]
        assert t.record_header("3.3.3.3", 3, at) == HEADER_POINTS[3]
        assert t.record_header("4.4.4.4", 4, at) == 0
        assert t.record_body("1.1.1.1", at) == BODY_POINTS
        s = t.score_for("1.1.1.1", now=at)
        assert s.headers_1st_count == 1
        assert s.header_points == 10
        assert s.bodies_count == 1
        assert s.body_points == 10

    def test_sliding_window_expires(self):
        t = PeerRelevanceTracker()
        old = datetime(2026, 9, 16, 11, 0, 0, tzinfo=UTC)
        now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
        t.record_header("1.1.1.1", 1, old)
        s = t.score_for("1.1.1.1", now=now)
        assert s.headers_count == 0
        t.record_header("1.1.1.1", 1, datetime(2026, 9, 16, 11, 45, 0, tzinfo=UTC))
        s = t.score_for("1.1.1.1", now=now)
        assert s.headers_1st_count == 1

    def test_snapshot_shape(self):
        t = PeerRelevanceTracker()
        at = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
        t.record_header("9.9.9.9", 1, at)
        snap = t.snapshot(now=at)
        assert snap["kind"] == "peerRelevanceSnapshot"
        assert snap["window_seconds"] == 1800
        assert snap["peers"][0]["remote_addr"] == "9.9.9.9"
        assert snap["peers"][0]["header_points"] == 10
