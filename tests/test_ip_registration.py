"""Tests for dual-stack IP registration (proof + register)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openblockperf.apiclient.client import BlockperfApiClient
from openblockperf.apiclient.models import (
    IpProofResponse,
    IpRegistrationRequest,
    IpRegistrationResponse,
    IpRegistrationResponseStatus,
)
from openblockperf.config import AppSettings


def test_ip_registration_request_serializes_proof_tokens():
    body = IpRegistrationRequest(proof_tokens=["t4", "t6"])
    assert body.model_dump() == {"proof_tokens": ["t4", "t6"]}


def test_ip_registration_response_accepts_ipaddresses():
    response = IpRegistrationResponse.model_validate(
        {
            "status": "registered",
            "apikey": "pk_test",
            "ipaddress": "203.0.113.9",
            "ipaddresses": ["203.0.113.9", "2001:db8::1"],
        }
    )
    assert response.status == IpRegistrationResponseStatus.REGISTERED
    assert response.ipaddresses == ["203.0.113.9", "2001:db8::1"]


@pytest.mark.asyncio
async def test_request_ip_proof_forces_local_address_and_hostname():
    settings = AppSettings(api_url="https://edge.example.test/mainnet/api/v0", node_name="relay-a")
    api = BlockperfApiClient(settings, service_mode=False)
    await api.prepare()

    captured: dict = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            captured["kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path):
            captured["path"] = path
            response = MagicMock()
            response.raise_for_status = MagicMock()
            response.json.return_value = {
                "token": "tok-v4",
                "ip": "203.0.113.9",
                "hostname": "relay-a",
                "expires_at": "2026-09-09T20:00:00Z",
            }
            return response

    with patch("openblockperf.apiclient.client.httpx.AsyncClient", FakeClient):
        with patch("openblockperf.apiclient.client.httpx.AsyncHTTPTransport") as transport_cls:
            transport_cls.return_value = MagicMock()
            proof = await api.request_ip_proof("v4")

    transport_cls.assert_called_once_with(local_address="0.0.0.0")
    assert captured["kwargs"]["headers"]["X-Hostname"] == "relay-a"
    assert "X-Edge-Telemetry-Token" not in captured["kwargs"]["headers"]
    assert captured["path"] == "registration/ip/proof"
    assert proof.token == "tok-v4"
    assert proof.ip == "203.0.113.9"
    await api.close()


@pytest.mark.asyncio
async def test_request_ip_proof_v6_binds_to_all_interfaces():
    settings = AppSettings(api_url="https://edge.example.test/mainnet/api/v0", node_name="relay-a")
    api = BlockperfApiClient(settings, service_mode=False)
    await api.prepare()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path):
            response = MagicMock()
            response.raise_for_status = MagicMock()
            response.json.return_value = {"token": "tok-v6", "ip": "2001:db8::1"}
            return response

    with patch("openblockperf.apiclient.client.httpx.AsyncClient", FakeClient):
        with patch("openblockperf.apiclient.client.httpx.AsyncHTTPTransport") as transport_cls:
            transport_cls.return_value = MagicMock()
            proof = await api.request_ip_proof("v6")

    transport_cls.assert_called_once_with(local_address="::")
    assert proof.token == "tok-v6"
    await api.close()


@pytest.mark.asyncio
async def test_register_ip_submits_both_proof_tokens():
    settings = AppSettings(api_url="https://edge.example.test/mainnet/api/v0", node_name="relay-a")
    api = BlockperfApiClient(settings, service_mode=False)
    await api.prepare()

    proofs = {
        "v4": IpProofResponse(token="t4", ip="203.0.113.9"),
        "v6": IpProofResponse(token="t6", ip="2001:db8::1"),
    }
    expected = IpRegistrationResponse(
        status=IpRegistrationResponseStatus.REGISTERED,
        apikey="pk_new",
        ipaddress="203.0.113.9",
        ipaddresses=["203.0.113.9", "2001:db8::1"],
    )
    api.collect_ip_proofs = AsyncMock(return_value=proofs)  # type: ignore[method-assign]
    api.clientip_registration = AsyncMock(return_value=expected)  # type: ignore[method-assign]

    response, got_proofs, used_legacy = await api.register_ip()

    api.clientip_registration.assert_awaited_once_with(False, False, proof_tokens=["t4", "t6"])
    assert response is expected
    assert got_proofs == proofs
    assert used_legacy is False
    await api.close()


@pytest.mark.asyncio
async def test_register_ip_falls_back_to_legacy_when_no_proofs():
    settings = AppSettings(api_url="https://edge.example.test/mainnet/api/v0", node_name="relay-a")
    api = BlockperfApiClient(settings, service_mode=False)
    await api.prepare()

    expected = IpRegistrationResponse(
        status=IpRegistrationResponseStatus.REGISTERED,
        apikey="pk_legacy",
        ipaddress="203.0.113.9",
    )
    api.collect_ip_proofs = AsyncMock(return_value={})  # type: ignore[method-assign]
    api.clientip_registration = AsyncMock(return_value=expected)  # type: ignore[method-assign]

    response, proofs, used_legacy = await api.register_ip()

    api.clientip_registration.assert_awaited_once_with(False, False, proof_tokens=None)
    assert response is expected
    assert proofs == {}
    assert used_legacy is True
    await api.close()


@pytest.mark.asyncio
async def test_clientip_registration_sends_proof_body_and_headers():
    settings = AppSettings(
        api_url="https://edge.example.test/mainnet/api/v0",
        node_name="relay-a",
        api_key="pk_existing",
    )
    api = BlockperfApiClient(settings, service_mode=False)
    await api.prepare()

    captured: dict = {}

    async def fake_post(endpoint, data=None, response_model=None, **kwargs):
        captured["endpoint"] = endpoint
        captured["data"] = data
        captured["headers"] = kwargs.get("headers")
        return IpRegistrationResponse(
            status=IpRegistrationResponseStatus.UPDATE_IP,
            apikey="pk_existing",
            ipaddresses=["203.0.113.9", "2001:db8::1"],
        )

    api._api.post = fake_post  # type: ignore[method-assign]
    await api.clientip_registration(False, True, proof_tokens=["t4", "t6"])

    assert captured["endpoint"] == "/registration/ip"
    assert isinstance(captured["data"], IpRegistrationRequest)
    assert captured["data"].proof_tokens == ["t4", "t6"]
    assert captured["headers"]["X-Update-Ip"] == "True"
    assert captured["headers"]["X-Force-Renewal"] == "False"
    await api.close()


@pytest.mark.asyncio
async def test_clientip_registration_legacy_sends_no_body():
    settings = AppSettings(api_url="https://edge.example.test/mainnet/api/v0", node_name="relay-a")
    api = BlockperfApiClient(settings, service_mode=False)
    await api.prepare()

    captured: dict = {}

    async def fake_post(endpoint, data=None, response_model=None, **kwargs):
        captured["data"] = data
        return IpRegistrationResponse(
            status=IpRegistrationResponseStatus.REGISTERED,
            apikey="pk_legacy",
            ipaddress="203.0.113.9",
        )

    api._api.post = fake_post  # type: ignore[method-assign]
    await api.clientip_registration(False, False, proof_tokens=None)

    assert captured["data"] is None
    await api.close()
