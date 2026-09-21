"""Temporary peer-session audit log (JSONL) for lifecycle debugging.

Enable with ``peer_audit_log_file`` in config. Off by default. Each line is one
JSON object. Use for a few hours, then compare with backend peer lists.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openblockperf.logging import logger
from openblockperf.peer_tracker import PeerReport, PeerTracker


def _iso(at: datetime | None = None) -> str:
    value = at or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


class PeerAuditLog:
    """Append-only JSONL writer for peer parse / decision / submit / counts."""

    def __init__(self, path: Path, *, counts_every_seconds: float = 60.0) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._counts_every = counts_every_seconds
        self._last_counts_at: datetime | None = None
        self._fh = self.path.open("a", encoding="utf-8")
        self.write(
            "audit_start",
            path=str(self.path),
            note="temporary peer audit; disable peer_audit_log_file when done",
        )
        logger.info(f"Peer audit log enabled: {self.path}")

    def close(self) -> None:
        try:
            self.write("audit_stop")
        except Exception:
            pass
        try:
            self._fh.close()
        except Exception:
            pass

    def write(self, kind: str, *, at: datetime | None = None, **fields: Any) -> None:
        row = {"kind": kind, "logged_at": _iso(), **fields}
        if at is not None:
            row["at"] = _iso(at)
        self._fh.write(json.dumps(row, default=str, separators=(",", ":")) + "\n")
        self._fh.flush()

    def parse(
        self,
        *,
        at: datetime,
        ns: str,
        event_type: str,
        local_addr: str | None = None,
        local_port: int | None = None,
        remote_addr: str | None = None,
        remote_port: int | None = None,
        **extra: Any,
    ) -> None:
        self.write(
            "parse",
            at=at,
            ns=ns,
            event_type=event_type,
            local_addr=local_addr,
            local_port=local_port,
            remote_addr=remote_addr,
            remote_port=remote_port,
            **extra,
        )

    def submit(self, report: PeerReport) -> None:
        peer = report.peer
        self.write(
            "submit",
            at=report.at,
            event_role=report.event_role.value,
            change_type=report.change_type.value
            if hasattr(report.change_type, "value")
            else str(report.change_type),
            direction=report.direction.value
            if hasattr(report.direction, "value")
            else str(report.direction),
            last_state=report.state,
            session_id=report.session_id,
            node_generation=report.node_generation,
            close_reason=report.close_reason.value if report.close_reason else None,
            we_dialed=report.we_dialed,
            remote_addr=peer.remote_addr,
            remote_port=report.remote_port,
            local_addr=peer.local_addr,
            local_port=peer.local_port,
            n2n_version=peer.n2n_version,
            diffusion_mode=peer.diffusion_mode,
            peer_sharing=peer.peer_sharing,
            peras_support=peer.peras_support,
        )

    def enrich(
        self,
        *,
        at: datetime,
        session_id: str | None,
        remote_addr: str,
        remote_port: int,
        n2n_version: int | None,
        diffusion_mode: str | None,
        peer_sharing: str | None,
        peras_support: str | None,
        note: str = "hs_on_existing_session",
    ) -> None:
        self.write(
            "enrich",
            at=at,
            session_id=session_id,
            remote_addr=remote_addr,
            remote_port=remote_port,
            n2n_version=n2n_version,
            diffusion_mode=diffusion_mode,
            peer_sharing=peer_sharing,
            peras_support=peras_support,
            note=note,
        )

    def counts(self, tracker: PeerTracker, *, reason: str = "flush") -> None:
        now = datetime.now(UTC)
        if (
            reason == "flush"
            and self._last_counts_at is not None
            and (now - self._last_counts_at).total_seconds() < self._counts_every
        ):
            return
        self._last_counts_at = now
        self.write("counts", reason=reason, **tracker.diagnostic_counts())
