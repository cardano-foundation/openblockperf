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
from openblockperf.logging import logger

API_REQUEST_TIMEOUT = 0.5
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

    Service mode ranks by health RTT. CLI mode picks one SRV target at random
    and does not walk a failover list.
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
        """Move to the next ranked edge. Rebuild the list if it is exhausted."""
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
        logger.info(
            "Selected lowest-RTT healthy API edge",
            srv=srv_name,
            url=fastest.base_url,
            host=fastest.host,
            port=fastest.port,
            rtt_ms=round(fastest.rtt_ms, 1) if fastest.rtt_ms is not None else None,
            healthy=len(ranked),
            probed=probed,
        )
        for endpoint in ranked:
            logger.debug(
                "Ranked API edge",
                url=endpoint.base_url,
                rtt_ms=round(endpoint.rtt_ms, 1) if endpoint.rtt_ms is not None else None,
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
            chosen = random.choice(targets)
            endpoint = EdgeEndpoint(
                base_url=api_base_url(chosen.host, chosen.port, network),
                host=chosen.host,
                port=chosen.port,
            )
            self.ranked = [endpoint]
            self.index = 0
            logger.info(
                "CLI picked random API edge from SRV",
                srv=srv_name,
                host=chosen.host,
                port=chosen.port,
                url=endpoint.base_url,
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
