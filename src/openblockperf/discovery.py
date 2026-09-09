"""DNS SRV discovery and ranked API edge selection."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass

import dns.asyncresolver
import dns.exception
import httpx

from openblockperf.config import DEFAULT_API_SRV, AppSettings
from openblockperf.errors import DiscoveryError
from openblockperf.logging import log_json_event, logger

API_REQUEST_TIMEOUT = 8.0
API_REQUEST_RETRIES = 2
HEALTH_PROBE_TIMEOUT = 2.0
ENDPOINT_LIST_EXHAUSTED_PAUSE = 30.0
SRV_REFRESH_INTERVAL = 86400.0


@dataclass(frozen=True)
class SrvTarget:
    host: str
    port: int


@dataclass(frozen=True)
class EdgeEndpoint:
    """A reachable API edge.

    ``base_url`` is the httpx client base, including the network and ``/api/v0/``
    prefix (or the caller-supplied override URL).
    """

    base_url: str
    host: str | None = None
    port: int | None = None
    rtt_ms: float | None = None
    override: bool = False

    @property
    def short_name(self) -> str:
        """First DNS label of the edge host, e.g. ``ho-fr-1`` from an SRV target."""
        if self.host:
            return self.host.split(".", 1)[0]
        return "override" if self.override else "unknown"


def normalize_host(host: str) -> str:
    return host.rstrip(".")


def api_base_url(host: str, port: int, network: str) -> str:
    return f"https://{normalize_host(host)}:{port}/{network}/api/v0/"


def health_url(host: str, port: int, network: str) -> str:
    return f"https://{normalize_host(host)}:{port}/{network}/api/health"


def override_base_url(api_url: str) -> str:
    return api_url.rstrip("/") + "/"


async def resolve_srv_records(name: str) -> list[SrvTarget]:
    """Resolve SRV records. Priority and weight are ignored."""
    try:
        answers = await dns.asyncresolver.resolve(name, "SRV")
    except dns.exception.DNSException as exc:
        raise DiscoveryError(f"SRV lookup failed for {name}: {exc}") from exc

    targets: list[SrvTarget] = []
    seen: set[tuple[str, int]] = set()
    for rdata in answers:
        host = normalize_host(str(rdata.target))
        port = int(rdata.port)
        key = (host, port)
        if key in seen:
            continue
        seen.add(key)
        targets.append(SrvTarget(host=host, port=port))

    if not targets:
        raise DiscoveryError(f"No SRV records for {name}")
    return targets


async def probe_health(target: SrvTarget, network: str, client: httpx.AsyncClient) -> EdgeEndpoint | None:
    """Return an endpoint when GET health is HTTP 200 with status=healthy."""
    url = health_url(target.host, target.port, network)
    started = time.perf_counter()
    try:
        response = await client.get(url)
    except httpx.RequestError as exc:
        logger.debug("Health probe failed", url=url, error=repr(exc))
        return None

    rtt_ms = (time.perf_counter() - started) * 1000
    if response.status_code != 200:  # noqa: PLR2004
        logger.debug("Health probe non-200", url=url, status=response.status_code)
        return None
    try:
        payload = response.json()
    except ValueError:
        logger.debug("Health probe invalid JSON", url=url)
        return None
    if payload.get("status") != "healthy":
        logger.debug("Health probe not healthy", url=url, payload=payload)
        return None
    return EdgeEndpoint(
        base_url=api_base_url(target.host, target.port, network),
        host=target.host,
        port=target.port,
        rtt_ms=rtt_ms,
    )


async def rank_healthy_endpoints(targets: list[SrvTarget], network: str) -> list[EdgeEndpoint]:
    """Probe health in parallel and return healthy edges sorted by lowest RTT."""
    timeout = httpx.Timeout(HEALTH_PROBE_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await asyncio.gather(*[probe_health(target, network, client) for target in targets])
    healthy = [endpoint for endpoint in results if endpoint is not None]
    healthy.sort(key=lambda endpoint: endpoint.rtt_ms if endpoint.rtt_ms is not None else float("inf"))
    return healthy


class EndpointPool:
    """Holds discovered API edges and advances through them on failover.

    Service mode ranks by health RTT and rediscovers after the list is exhausted.
    CLI mode (register-ip / register-calidus) probes health, shuffles the healthy
    edges for load balancing, and walks that list on failover without a rediscovery pause.
    """

    def __init__(self, settings: AppSettings, *, service_mode: bool) -> None:
        self.settings = settings
        self.service_mode = service_mode
        self.ranked: list[EdgeEndpoint] = []
        self.index = 0
        self._lock = asyncio.Lock()

    @property
    def current(self) -> EdgeEndpoint | None:
        if not self.ranked:
            return None
        if self.index >= len(self.ranked):
            return None
        return self.ranked[self.index]

    @property
    def uses_srv(self) -> bool:
        return not self.settings.api_url

    async def ensure_ready(self) -> EdgeEndpoint:
        async with self._lock:
            if self.current is not None:
                return self.current
            await self._refresh_unlocked(retry_until_healthy=True)
            if self.current is None:
                raise DiscoveryError("No API endpoint available")
            return self.current

    async def refresh(self) -> EdgeEndpoint:
        """Replace the ranked list once. Keep the previous list if rediscovery fails."""
        async with self._lock:
            previous = list(self.ranked)
            previous_index = self.index
            try:
                await self._refresh_unlocked(retry_until_healthy=False)
            except DiscoveryError:
                self.ranked = previous
                self.index = previous_index
                raise
            if self.current is None:
                self.ranked = previous
                self.index = previous_index
                raise DiscoveryError("No API endpoint available after refresh")
            return self.current

    async def failover_from(self, failed: EdgeEndpoint) -> EdgeEndpoint:
        """Move to the next ranked edge. Service mode rediscovers when exhausted."""
        async with self._lock:
            if self.current is not None and self.current != failed:
                return self.current
            self.index += 1
            if self.current is not None:
                logger.warning(
                    "Failing over to next API edge",
                    url=self.current.base_url,
                    host=self.current.host,
                    port=self.current.port,
                )
                return self.current
            if not self.service_mode:
                raise DiscoveryError("No more healthy API edges to try")
            logger.warning(
                "API edge list exhausted, pausing before rediscovery",
                pause_seconds=ENDPOINT_LIST_EXHAUSTED_PAUSE,
            )
            await asyncio.sleep(ENDPOINT_LIST_EXHAUSTED_PAUSE)
            await self._refresh_unlocked(retry_until_healthy=True)
            if self.current is None:
                raise DiscoveryError("No API endpoint available after failover rediscovery")
            return self.current

    def _apply_ranked(self, ranked: list[EdgeEndpoint], *, srv_name: str, probed: int) -> None:
        self.ranked = ranked
        self.index = 0
        fastest = ranked[0]
        log_json_event(
            "apiEdgeRanking",
            srv=srv_name,
            selected=fastest.base_url,
            healthy=len(ranked),
            probed=probed,
            edges=[
                {
                    "host": endpoint.host,
                    "port": endpoint.port,
                    "rtt_ms": round(endpoint.rtt_ms, 1) if endpoint.rtt_ms is not None else None,
                    "url": endpoint.base_url,
                }
                for endpoint in ranked
            ],
        )

    async def _refresh_unlocked(self, *, retry_until_healthy: bool) -> None:
        if self.settings.api_url:
            endpoint = EdgeEndpoint(
                base_url=override_base_url(self.settings.api_url),
                override=True,
            )
            self.ranked = [endpoint]
            self.index = 0
            logger.info("Using API URL override", url=endpoint.base_url)
            return

        srv_name = self.settings.api_srv or DEFAULT_API_SRV
        network = self.settings.network_name

        if not self.service_mode:
            targets = await resolve_srv_records(srv_name)
            healthy = await rank_healthy_endpoints(targets, network)
            if not healthy:
                raise DiscoveryError(f"No healthy API edges for {srv_name}")
            # Shuffle so registration load is spread across healthy edges.
            random.shuffle(healthy)
            self.ranked = healthy
            self.index = 0
            chosen = healthy[0]
            logger.info(
                "CLI picked healthy API edge from SRV",
                srv=srv_name,
                host=chosen.host,
                port=chosen.port,
                url=chosen.base_url,
                healthy=len(healthy),
                probed=len(targets),
            )
            return

        while True:
            try:
                targets = await resolve_srv_records(srv_name)
            except DiscoveryError:
                if not retry_until_healthy:
                    raise
                logger.warning(
                    "SRV lookup failed, retrying after pause",
                    srv=srv_name,
                    pause_seconds=ENDPOINT_LIST_EXHAUSTED_PAUSE,
                )
                await asyncio.sleep(ENDPOINT_LIST_EXHAUSTED_PAUSE)
                continue

            ranked = await rank_healthy_endpoints(targets, network)
            if ranked:
                self._apply_ranked(ranked, srv_name=srv_name, probed=len(targets))
                return

            if not retry_until_healthy:
                raise DiscoveryError(f"No healthy API edges for {srv_name}")
            logger.warning(
                "No healthy API edges, retrying after pause",
                srv=srv_name,
                probed=len(targets),
                pause_seconds=ENDPOINT_LIST_EXHAUSTED_PAUSE,
            )
            await asyncio.sleep(ENDPOINT_LIST_EXHAUSTED_PAUSE)
