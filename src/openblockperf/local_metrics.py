"""Optional local HTTP metrics for SPOs and gLiveView (Prometheus + JSON).

Enabled via ``local_metrics_enabled``. Default bind ``127.0.0.1:14041``.
Uses only the stdlib asyncio server (no extra web framework dependency).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from openblockperf.logging import logger
from openblockperf.peer_tracker import PeerTracker


def build_peers_json(tracker: PeerTracker, *, level: str) -> dict[str, Any]:
    """JSON document: reported peers + diagnostic counts."""
    diag = tracker.diagnostic_counts()
    return {
        "at": datetime.now(UTC).isoformat(),
        "peer_events_level": level,
        "export": "reported",
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
            "total_tracked": len(tracker.peers),
        },
        "peers": tracker.reported_peer_rows(),
    }


def build_prometheus_text(tracker: PeerTracker, *, level: str) -> str:
    """Prometheus exposition: aggregate gauges only (peer list is JSON)."""
    diag = tracker.diagnostic_counts()
    lines = [
        "# HELP openblockperf_peer_events_level Peer events level (info label).",
        "# TYPE openblockperf_peer_events_level gauge",
        f'openblockperf_peer_events_level{{level="{level}"}} 1',
        "# HELP openblockperf_peers_total Tracked peer IPs in the local map.",
        "# TYPE openblockperf_peers_total gauge",
        f"openblockperf_peers_total {len(tracker.peers)}",
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
    # Drain headers
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
    path = target.split("?", 1)[0]
    return method, path


class LocalMetricsServer:
    """Serves /metrics (Prometheus) and /peers (JSON) from a PeerTracker snapshot."""

    def __init__(
        self,
        tracker: PeerTracker,
        *,
        bind: str,
        port: int,
        level: str,
        get_level: Callable[[], str] | None = None,
    ):
        self.tracker = tracker
        self.bind = bind
        self.port = port
        self._level = level
        self._get_level = get_level
        self._server = None

    def _level_value(self) -> str:
        if self._get_level is not None:
            return self._get_level()
        return self._level

    async def _handle(self, reader, writer) -> None:
        try:
            method, path = await _read_request(reader)
            if method != "GET":
                payload = _http_response(405, "Method Not Allowed", b"method not allowed\n", "text/plain")
            elif path in ("/", "/health"):
                payload = _http_response(200, "OK", b"ok\n", "text/plain; charset=utf-8")
            elif path == "/metrics":
                text = build_prometheus_text(self.tracker, level=self._level_value())
                payload = _http_response(
                    200, "OK", text.encode("utf-8"), "text/plain; version=0.0.4; charset=utf-8"
                )
            elif path in ("/peers", "/peers.json"):
                doc = build_peers_json(self.tracker, level=self._level_value())
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
