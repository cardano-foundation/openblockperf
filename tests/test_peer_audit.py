"""Tests for temporary peer audit JSONL logging."""

import json
from datetime import UTC, datetime
from pathlib import Path

from openblockperf.models.events import PeerEventChangeType
from openblockperf.models.peer import EventRole, Peer, PeerDirection, PeerState
from openblockperf.peer_audit import PeerAuditLog
from openblockperf.peer_tracker import PeerReport, PeerTracker


def test_peer_audit_writes_parse_submit_counts(tmp_path: Path):
    path = tmp_path / "peer-audit.jsonl"
    audit = PeerAuditLog(path)
    tracker = PeerTracker({}, stable_seconds=0)
    at = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
    audit.parse(
        at=at,
        ns="Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess",
        event_type="HandshakeSuccessEvent",
        local_addr="10.0.0.1",
        local_port=3001,
        remote_addr="198.51.100.9",
        remote_port=45000,
        n2n_version=15,
        diffusion_mode="InitiatorAndResponderDiffusionMode",
    )
    report = PeerReport(
        peer=Peer(
            ns="hs",
            local_addr="10.0.0.1",
            local_port=3001,
            remote_addr="198.51.100.9",
            remote_port=0,
            n2n_version=15,
            diffusion_mode="InitiatorAndResponderDiffusionMode",
        ),
        direction=PeerDirection.INBOUND,
        change_type=PeerEventChangeType.COLD_WARM,
        state=PeerState.WARM.value,
        at=at,
        remote_port=0,
        event_role=EventRole.OPEN,
        node_generation=1,
        session_id="abc123",
        we_dialed=None,
    )
    audit.submit(report)
    audit.counts(tracker, reason="flush")
    audit.close()

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 4
    kinds = [json.loads(line)["kind"] for line in lines]
    assert kinds[0] == "audit_start"
    assert "parse" in kinds
    assert "submit" in kinds
    assert "counts" in kinds
    assert kinds[-1] == "audit_stop"
    submit = next(json.loads(line) for line in lines if json.loads(line)["kind"] == "submit")
    assert submit["session_id"] == "abc123"
    assert submit["n2n_version"] == 15
    assert "\n" not in submit["session_id"]
