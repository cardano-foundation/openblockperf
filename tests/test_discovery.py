"""Tests for SRV discovery, health ranking, and endpoint failover."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from openblockperf.config import AppSettings, Network
from openblockperf.discovery import (
    EdgeEndpoint,
    EndpointPool,
    SrvTarget,
    api_base_url,
    health_url,
    normalize_host,
    override_base_url,
    probe_health,
    rank_healthy_endpoints,
)
from openblockperf.logging import logger


def test_normalize_host_strips_trailing_dot():
    assert normalize_host("ho-de-1.network.cardano.org.") == "ho-de-1.network.cardano.org"


def test_api_base_url_uses_fqdn_port_and_network_path():
    url = api_base_url("ho-de-1.network.cardano.org.", 443, "mainnet")
    assert url == "https://ho-de-1.network.cardano.org:443/mainnet/api/v0/"


def test_health_url_is_not_under_api_v0():
    url = health_url("ho-de-1.network.cardano.org", 443, "preprod")
    assert url == "https://ho-de-1.network.cardano.org:443/preprod/api/health"


def test_api_base_url_does_not_append_network_cardano_org():
    url = api_base_url("edge.example.test", 8443, "preview")
    assert url == "https://edge.example.test:8443/preview/api/v0/"
    assert "network.cardano.org" not in url


def test_override_base_url_adds_trailing_slash():
    assert override_base_url("http://localhost:8000/mainnet/api/v0") == "http://localhost:8000/mainnet/api/v0/"


@pytest.mark.asyncio
async def test_probe_health_accepts_healthy_json():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "healthy", "network": "mainnet"}
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    endpoint = await probe_health(SrvTarget("ho-de-1.network.cardano.org", 443), "mainnet", client)

    assert endpoint is not None
    assert endpoint.host == "ho-de-1.network.cardano.org"
    assert endpoint.port == 443
    assert endpoint.base_url.endswith("/mainnet/api/v0/")
    client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_health_rejects_non_healthy_status():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "degraded"}
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    endpoint = await probe_health(SrvTarget("ho-de-1.network.cardano.org", 443), "mainnet", client)
    assert endpoint is None


@pytest.mark.asyncio
async def test_rank_healthy_endpoints_sorts_by_rtt():
    slow = EdgeEndpoint(base_url="https://slow:443/mainnet/api/v0/", host="slow", port=443, rtt_ms=40.0)
    fast = EdgeEndpoint(base_url="https://fast:443/mainnet/api/v0/", host="fast", port=443, rtt_ms=8.0)
    targets = [SrvTarget("slow", 443), SrvTarget("fast", 443), SrvTarget("down", 443)]

    async def fake_probe(target, network, client):
        mapping = {"slow": slow, "fast": fast, "down": None}
        return mapping[target.host]

    with (
        patch("openblockperf.discovery.httpx.AsyncClient") as client_cls,
        patch("openblockperf.discovery.probe_health", side_effect=fake_probe),
    ):
        client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        ranked = await rank_healthy_endpoints(targets, "mainnet")

    assert [e.host for e in ranked] == ["fast", "slow"]


@pytest.mark.asyncio
async def test_cli_mode_picks_one_random_srv_target_without_health():
    settings = AppSettings(network=Network.MAINNET)
    pool = EndpointPool(settings, service_mode=False)
    targets = [SrvTarget("a.example.test", 443), SrvTarget("b.example.test", 8443)]

    with (
        patch("openblockperf.discovery.resolve_srv_records", AsyncMock(return_value=targets)),
        patch("openblockperf.discovery.random.choice", return_value=targets[1]),
        patch("openblockperf.discovery.rank_healthy_endpoints", AsyncMock()) as rank,
    ):
        endpoint = await pool.ensure_ready()

    rank.assert_not_awaited()
    assert endpoint.host == "b.example.test"
    assert endpoint.port == 8443
    assert endpoint.base_url == "https://b.example.test:8443/mainnet/api/v0/"
    assert len(pool.ranked) == 1


@pytest.mark.asyncio
async def test_service_mode_ranks_and_selects_lowest_rtt():
    settings = AppSettings(network=Network.PREPROD)
    pool = EndpointPool(settings, service_mode=True)
    targets = [SrvTarget("slow.example.test", 443), SrvTarget("fast.example.test", 443)]
    ranked = [
        EdgeEndpoint(
            base_url="https://fast.example.test:443/preprod/api/v0/",
            host="fast.example.test",
            port=443,
            rtt_ms=5.0,
        ),
        EdgeEndpoint(
            base_url="https://slow.example.test:443/preprod/api/v0/",
            host="slow.example.test",
            port=443,
            rtt_ms=25.0,
        ),
    ]

    with (
        patch("openblockperf.discovery.resolve_srv_records", AsyncMock(return_value=targets)),
        patch("openblockperf.discovery.rank_healthy_endpoints", AsyncMock(return_value=ranked)),
    ):
        endpoint = await pool.ensure_ready()

    assert endpoint.host == "fast.example.test"
    assert [e.host for e in pool.ranked] == ["fast.example.test", "slow.example.test"]


def test_apply_ranked_logs_full_list_at_info():
    settings = AppSettings(network=Network.PREPROD)
    pool = EndpointPool(settings, service_mode=True)
    ranked = [
        EdgeEndpoint(
            base_url="https://fast.example.test:443/preprod/api/v0/",
            host="fast.example.test",
            port=443,
            rtt_ms=5.04,
        ),
        EdgeEndpoint(
            base_url="https://slow.example.test:443/preprod/api/v0/",
            host="slow.example.test",
            port=443,
            rtt_ms=25.0,
        ),
    ]
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message.record["message"])), level="INFO")
    try:
        pool._apply_ranked(ranked, srv_name="_obpf._tcp.example.test", probed=3)
    finally:
        logger.remove(sink_id)

    payload = json.loads(messages[-1])
    assert list(payload.keys())[0] == "kind"
    assert payload["kind"] == "apiEdgeRanking"
    assert payload["selected"] == "https://fast.example.test:443/preprod/api/v0/"
    assert payload["healthy"] == 2
    assert payload["probed"] == 3
    assert [edge["host"] for edge in payload["edges"]] == ["fast.example.test", "slow.example.test"]
    assert payload["edges"][0]["rtt_ms"] == 5.0
    assert "\n" not in messages[-1]


@pytest.mark.asyncio
async def test_api_url_override_skips_srv():
    settings = AppSettings(api_url="http://localhost:8000/mainnet/api/v0")
    pool = EndpointPool(settings, service_mode=True)

    with patch("openblockperf.discovery.resolve_srv_records", AsyncMock()) as resolve:
        endpoint = await pool.ensure_ready()

    resolve.assert_not_awaited()
    assert endpoint.override is True
    assert endpoint.base_url == "http://localhost:8000/mainnet/api/v0/"


@pytest.mark.asyncio
async def test_failover_walks_ranked_list_without_reprobing():
    settings = AppSettings()
    pool = EndpointPool(settings, service_mode=True)
    first = EdgeEndpoint(base_url="https://a:443/mainnet/api/v0/", host="a", port=443, rtt_ms=1.0)
    second = EdgeEndpoint(base_url="https://b:443/mainnet/api/v0/", host="b", port=443, rtt_ms=2.0)
    pool.ranked = [first, second]
    pool.index = 0

    with patch("openblockperf.discovery.rank_healthy_endpoints", AsyncMock()) as rank:
        nxt = await pool.failover_from(first)

    rank.assert_not_awaited()
    assert nxt.host == "b"
    assert pool.index == 1


@pytest.mark.asyncio
async def test_exhausted_list_pauses_then_refreshes():
    settings = AppSettings()
    pool = EndpointPool(settings, service_mode=True)
    only = EdgeEndpoint(base_url="https://a:443/mainnet/api/v0/", host="a", port=443, rtt_ms=1.0)
    pool.ranked = [only]
    pool.index = 0
    refreshed = EdgeEndpoint(base_url="https://c:443/mainnet/api/v0/", host="c", port=443, rtt_ms=3.0)

    with (
        patch("openblockperf.discovery.asyncio.sleep", AsyncMock()) as sleep,
        patch("openblockperf.discovery.resolve_srv_records", AsyncMock(return_value=[SrvTarget("c", 443)])),
        patch("openblockperf.discovery.rank_healthy_endpoints", AsyncMock(return_value=[refreshed])),
    ):
        nxt = await pool.failover_from(only)

    sleep.assert_awaited_once()
    assert nxt.host == "c"
    assert pool.index == 0


@pytest.mark.asyncio
async def test_refresh_keeps_previous_list_on_failure():
    from openblockperf.errors import DiscoveryError

    settings = AppSettings()
    pool = EndpointPool(settings, service_mode=True)
    existing = EdgeEndpoint(base_url="https://a:443/mainnet/api/v0/", host="a", port=443, rtt_ms=1.0)
    pool.ranked = [existing]
    pool.index = 0

    with patch("openblockperf.discovery.resolve_srv_records", AsyncMock(side_effect=DiscoveryError("dns down"))):
        with pytest.raises(DiscoveryError):
            await pool.refresh()

    assert pool.current is existing
    assert pool.index == 0


@pytest.mark.asyncio
async def test_make_request_does_not_failover_on_http_error():
    from openblockperf.apiclient.base import BlockperfApiBase
    from openblockperf.errors import ApiError

    settings = AppSettings(api_url="http://localhost:8000/mainnet/api/v0")
    pool = EndpointPool(settings, service_mode=True)
    await pool.ensure_ready()

    request = MagicMock()
    response = MagicMock()
    response.status_code = 503
    response.reason_phrase = "Service Unavailable"
    response.url = "http://localhost:8000/mainnet/api/v0/submit/blocksample"
    error = httpx.HTTPStatusError("boom", request=request, response=response)

    client = AsyncMock()
    client.request = AsyncMock(side_effect=error)

    api = BlockperfApiBase(pool=pool, api_key="pk_test")
    api._client = client
    api._client_base = pool.current.base_url

    with pytest.raises(ApiError):
        await api._make_request("POST", "/submit/blocksample")

    assert pool.index == 0
    assert client.request.await_count == 1


def test_api_client_uses_timeout_and_retries_from_settings():
    from openblockperf.apiclient.client import BlockperfApiClient

    settings = AppSettings(api_request_timeout_ms=2500, api_request_retries=4)
    api = BlockperfApiClient(settings, service_mode=True)
    assert api._api.timeout == 2.5
    assert api._api.retries == 4
    assert api._api.attempts_per_host == 5


def test_log_json_event_peer_count_stats_is_single_line():
    from openblockperf.logging import log_json_event

    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message.record["message"])), level="INFO")
    try:
        log_json_event("peerCountStats", in_cold=1, out_cold=2, total_peers=3)
    finally:
        logger.remove(sink_id)

    payload = json.loads(messages[-1])
    assert list(payload.keys())[0] == "kind"
    assert payload == {
        "kind": "peerCountStats",
        "in_cold": 1,
        "out_cold": 2,
        "total_peers": 3,
    }
    assert "\n" not in messages[-1]
