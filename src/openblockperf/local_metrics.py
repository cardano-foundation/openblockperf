"""Optional local HTTP metrics for SPOs (Prometheus + JSON).

Enabled via ``local_metrics_enabled``. Default bind ``127.0.0.1:14041``.
Uses only the stdlib asyncio server (no extra web framework dependency).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from openblockperf.logging import logger
from openblockperf.peer_relevance import PeerRelevanceTracker
from openblockperf.peer_tracker import PeerTracker


def build_peers_json(
    tracker: PeerTracker,
    *,
    relevance: PeerRelevanceTracker | None = None,
    include_all_open: bool = False,
) -> dict[str, Any]:
    """JSON document: useful (or all open) sessions + diagnostic counts."""
    diag = tracker.diagnostic_counts()
    rows = tracker.all_open_session_rows() if include_all_open else tracker.useful_session_rows()
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
    closed = {
        key.removeprefix("closed_"): value
        for key, value in diag.items()
        if key.startswith("closed_")
    }
    return {
        "at": datetime.now(UTC).isoformat(),
        "export": "open" if include_all_open else "useful",
        "node_generation": diag["node_generation"],
        "relevance_window_seconds": 1800 if relevance is not None else None,
        "counts": {
            "open": diag["open"],
            "useful": diag["useful"],
            "ig_warm": diag["ig_warm"],
            "ig_hot": diag["ig_hot"],
            "out_warm": diag["out_warm"],
            "out_hot": diag["out_hot"],
            "opened": diag["opened"],
            "handshakes_cached": diag.get("handshakes_cached", 0),
            "closed": closed,
        },
        "peers": rows,
        "relevance_orphans": relevance_orphans,
    }


def build_prometheus_text(
    tracker: PeerTracker,
    *,
    relevance: PeerRelevanceTracker | None = None,
) -> str:
    """Prometheus exposition: session gauges, not node Warm/Hot boxes."""
    diag = tracker.diagnostic_counts()
    lines = [
        "# HELP openblockperf_node_generation Cardano-node / diffusion start count this client process.",
        "# TYPE openblockperf_node_generation gauge",
        f"openblockperf_node_generation {diag['node_generation']}",
        "# HELP openblockperf_sessions_open Currently open remote peer sessions.",
        "# TYPE openblockperf_sessions_open gauge",
        f"openblockperf_sessions_open {diag['open']}",
        "# HELP openblockperf_sessions_useful Open sessions flagged useful (Hot or stable Warm).",
        "# TYPE openblockperf_sessions_useful gauge",
        f"openblockperf_sessions_useful {diag['useful']}",
        "# HELP openblockperf_sessions_opened Sessions opened this process (HS or first temperature).",
        "# TYPE openblockperf_sessions_opened counter",
        f"openblockperf_sessions_opened {diag['opened']}",
        "# HELP openblockperf_handshakes_cached Open sessions with HandshakeSuccess options.",
        "# TYPE openblockperf_handshakes_cached gauge",
        f"openblockperf_handshakes_cached {diag.get('handshakes_cached', 0)}",
        "# HELP openblockperf_session_temperature Open sessions by governor track and temperature.",
        "# TYPE openblockperf_session_temperature gauge",
        f'openblockperf_session_temperature{{track="ig",state="warm"}} {diag["ig_warm"]}',
        f'openblockperf_session_temperature{{track="ig",state="hot"}} {diag["ig_hot"]}',
        f'openblockperf_session_temperature{{track="outbound",state="warm"}} {diag["out_warm"]}',
        f'openblockperf_session_temperature{{track="outbound",state="hot"}} {diag["out_hot"]}',
        "# HELP openblockperf_sessions_closed Sessions closed this process by reason.",
        "# TYPE openblockperf_sessions_closed counter",
    ]
    for key, value in diag.items():
        if not key.startswith("closed_"):
            continue
        reason = key.removeprefix("closed_")
        lines.append(f'openblockperf_sessions_closed{{reason="{reason}"}} {value}')
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


async def _read_request(reader) -> tuple[str, str, str]:
    """Return (method, path, query) from a minimal HTTP request."""
    request_line = await reader.readline()
    if not request_line:
        return "", "", ""
    parts = request_line.decode("latin-1", errors="replace").strip().split()
    if len(parts) < 2:
        return "", "", ""
    method, target = parts[0].upper(), parts[1]
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
    parsed = urlparse(target)
    return method, parsed.path, parsed.query


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
            method, path, query = await _read_request(reader)
            if method != "GET":
                payload = _http_response(405, "Method Not Allowed", b"method not allowed\n", "text/plain")
            elif path in ("/", "/health"):
                payload = _http_response(200, "OK", b"ok\n", "text/plain; charset=utf-8")
            elif path == "/metrics":
                text = build_prometheus_text(self.tracker, relevance=self.relevance)
                payload = _http_response(
                    200, "OK", text.encode("utf-8"), "text/plain; version=0.0.4; charset=utf-8"
                )
            elif path in ("/peers", "/peers.json", "/peers/sessions"):
                qs = parse_qs(query)
                include_all = path == "/peers/sessions" or qs.get("all", ["0"])[0] in (
                    "1",
                    "true",
                    "yes",
                )
                doc = build_peers_json(
                    self.tracker,
                    relevance=self.relevance,
                    include_all_open=include_all,
                )
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
