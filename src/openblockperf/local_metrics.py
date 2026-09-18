"""Optional local HTTP metrics for SPOs and gLiveView (Prometheus + JSON).

Enabled via ``local_metrics_enabled``. Default bind ``127.0.0.1:14041``.
Uses only the stdlib asyncio server (no extra web framework dependency).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from openblockperf.logging import logger
from openblockperf.peer_relevance import PeerRelevanceTracker
from openblockperf.peer_tracker import PeerTracker


def build_peers_json(
    tracker: PeerTracker,
    *,
    relevance: PeerRelevanceTracker | None = None,
) -> dict[str, Any]:
    """JSON document: reported peers + diagnostic counts + sliding relevance."""
    diag = tracker.diagnostic_counts()
    rows = tracker.reported_peer_rows()
    relevance_orphans: list[dict] = []
    if relevance is not None:
        reported_ips = {r["remote_addr"] for r in rows}
        for row in rows:
            row["relevance"] = relevance.score_dict(row["remote_addr"])
        for score in relevance.all_scores():
            if score.remote_addr not in reported_ips:
                relevance_orphans.append(
                    {
                        "remote_addr": score.remote_addr,
                        "seen_in_blocksample_only": True,
                        "relevance": relevance.score_dict(score.remote_addr),
                    }
                )
    return {
        "at": datetime.now(UTC).isoformat(),
        "export": "reported",
        "relevance_window_seconds": 1800 if relevance is not None else None,
        "counts": {
            "live": {
                "in_warm": diag["in_warm_live"],
                "out_warm": diag["out_warm_live"],
                "in_hot": diag["in_hot_live"],
                "out_hot": diag["out_hot_live"],
                "duplex": diag["duplex_live"],
            },
            "reported": {
                "in_warm": diag["in_warm_reported"],
                "out_warm": diag["out_warm_reported"],
                "in_hot": diag["in_hot_reported"],
                "out_hot": diag["out_hot_reported"],
                "duplex": diag["duplex_reported"],
            },
            "pending": {
                "in_warm": diag["in_warm_pending"],
                "out_warm": diag["out_warm_pending"],
                "in_hot": diag["in_hot_pending"],
                "out_hot": diag["out_hot_pending"],
            },
            "handshakes_cached": diag.get("handshakes_cached", 0),
            "total_tracked": len(tracker.peers),
        },
        "peers": rows,
        "relevance_orphans": relevance_orphans,
    }


def build_prometheus_text(
    tracker: PeerTracker,
    *,
    relevance: PeerRelevanceTracker | None = None,
) -> str:
    """Prometheus exposition: aggregate gauges only (peer list is JSON)."""
    diag = tracker.diagnostic_counts()
    lines = [
        "# HELP openblockperf_peers_total Tracked peer IPs in the local map.",
        "# TYPE openblockperf_peers_total gauge",
        f"openblockperf_peers_total {len(tracker.peers)}",
        "# HELP openblockperf_handshakes_cached Cached HandshakeSuccess peers.",
        "# TYPE openblockperf_handshakes_cached gauge",
        f"openblockperf_handshakes_cached {diag.get('handshakes_cached', 0)}",
        "# HELP openblockperf_peers Temperature counts by view, direction, and state.",
        "# TYPE openblockperf_peers gauge",
    ]
    mapping = [
        ("live", "inbound", "warm", diag["in_warm_live"]),
        ("live", "outbound", "warm", diag["out_warm_live"]),
        ("live", "inbound", "hot", diag["in_hot_live"]),
        ("live", "outbound", "hot", diag["out_hot_live"]),
        ("reported", "inbound", "warm", diag["in_warm_reported"]),
        ("reported", "outbound", "warm", diag["out_warm_reported"]),
        ("reported", "inbound", "hot", diag["in_hot_reported"]),
        ("reported", "outbound", "hot", diag["out_hot_reported"]),
        ("pending", "inbound", "warm", diag["in_warm_pending"]),
        ("pending", "outbound", "warm", diag["out_warm_pending"]),
        ("pending", "inbound", "hot", diag["in_hot_pending"]),
        ("pending", "outbound", "hot", diag["out_hot_pending"]),
    ]
    for view, direction, state, value in mapping:
        lines.append(
            f'openblockperf_peers{{view="{view}",direction="{direction}",state="{state}"}} {value}'
        )
    lines.append("# HELP openblockperf_duplex Duplex peer count by view.")
    lines.append("# TYPE openblockperf_duplex gauge")
    lines.append(f'openblockperf_duplex{{view="live"}} {diag["duplex_live"]}')
    lines.append(f'openblockperf_duplex{{view="reported"}} {diag["duplex_reported"]}')
    if relevance is not None:
        scores = relevance.all_scores()
        header_points = sum(s.header_points for s in scores)
        body_points = sum(s.body_points for s in scores)
        headers_count = sum(s.headers_count for s in scores)
        bodies_count = sum(s.bodies_count for s in scores)
        lines.append("# HELP openblockperf_relevance_header_points Sum of header points in 30m window.")
        lines.append("# TYPE openblockperf_relevance_header_points gauge")
        lines.append(f"openblockperf_relevance_header_points {header_points}")
        lines.append("# HELP openblockperf_relevance_body_points Sum of body points in 30m window.")
        lines.append("# TYPE openblockperf_relevance_body_points gauge")
        lines.append(f"openblockperf_relevance_body_points {body_points}")
        lines.append("# HELP openblockperf_relevance_headers_count Header announce credits in 30m window.")
        lines.append("# TYPE openblockperf_relevance_headers_count gauge")
        lines.append(f"openblockperf_relevance_headers_count {headers_count}")
        lines.append("# HELP openblockperf_relevance_bodies_count Body serve credits in 30m window.")
        lines.append("# TYPE openblockperf_relevance_bodies_count gauge")
        lines.append(f"openblockperf_relevance_bodies_count {bodies_count}")
        lines.append("# HELP openblockperf_relevance_peers IPs with relevance in the 30m window.")
        lines.append("# TYPE openblockperf_relevance_peers gauge")
        lines.append(f"openblockperf_relevance_peers {len(scores)}")
    lines.append("")
    return "\n".join(lines)


def _http_response(status: int, reason: str, body: bytes, content_type: str) -> bytes:
    headers = (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    return headers.encode("ascii") + body


async def _read_request(reader) -> tuple[str, str]:
    """Return (method, path) from a minimal HTTP request. Path excludes query."""
    request_line = await reader.readline()
    if not request_line:
        return "", ""
    parts = request_line.decode("latin-1", errors="replace").strip().split()
    if len(parts) < 2:
        return "", ""
    method, target = parts[0].upper(), parts[1]
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
    path = target.split("?", 1)[0]
    return method, path


class LocalMetricsServer:
    """Serves /metrics (Prometheus) and /peers (JSON) from tracker + relevance."""

    def __init__(
        self,
        tracker: PeerTracker,
        *,
        bind: str,
        port: int,
        relevance: PeerRelevanceTracker | None = None,
    ):
        self.tracker = tracker
        self.relevance = relevance
        self.bind = bind
        self.port = port
        self._server = None

    async def _handle(self, reader, writer) -> None:
        try:
            method, path = await _read_request(reader)
            if method != "GET":
                payload = _http_response(405, "Method Not Allowed", b"method not allowed\n", "text/plain")
            elif path in ("/", "/health"):
                payload = _http_response(200, "OK", b"ok\n", "text/plain; charset=utf-8")
            elif path == "/metrics":
                text = build_prometheus_text(self.tracker, relevance=self.relevance)
                payload = _http_response(
                    200, "OK", text.encode("utf-8"), "text/plain; version=0.0.4; charset=utf-8"
                )
            elif path in ("/peers", "/peers.json"):
                doc = build_peers_json(self.tracker, relevance=self.relevance)
                body = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
                payload = _http_response(200, "OK", body, "application/json; charset=utf-8")
            else:
                payload = _http_response(404, "Not Found", b"not found\n", "text/plain")
            writer.write(payload)
            await writer.drain()
        except Exception:
            logger.exception("Local metrics request failed")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self) -> None:
        import asyncio

        self._server = await asyncio.start_server(self._handle, self.bind, self.port)
        sockets = self._server.sockets or []
        where = ", ".join(str(s.getsockname()) for s in sockets) or f"{self.bind}:{self.port}"
        logger.info("Local metrics listening", bind=where)
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
