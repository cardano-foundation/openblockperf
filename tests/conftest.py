"""Shared pytest fixtures for the openblockperf test suite."""

from unittest.mock import MagicMock

import pytest

from openblockperf.config import AppSettings, Network, settings

# ---------------------------------------------------------------------------
# Raw event payloads
# ---------------------------------------------------------------------------
# These dicts mirror exactly what the cardano-tracer / journald pipeline
# delivers.  They are session-scoped because they are plain dicts – read-only
# and cheap to keep alive for the whole run.


@pytest.fixture(scope="session")
def raw_downloaded_header() -> dict:
    return {
        "at": "2025-09-12T16:51:39.269022269Z",
        "ns": "ChainSync.Client.DownloadedHeader",
        "data": {
            "block": "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1",
            "blockNo": 3600148,
            "kind": "DownloadedHeader",
            "peer": {"connectionId": "172.0.118.125:30002 167.235.223.34:5355"},
            "slot": 91039899,
        },
        "sev": "Info",
        "thread": "96913",
        "host": "test-node",
    }


@pytest.fixture(scope="session")
def raw_send_fetch_request() -> dict:
    return {
        "at": "2025-09-12T16:52:11.098464254Z",
        "ns": "BlockFetch.Client.SendFetchRequest",
        "data": {
            "head": "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1",
            "kind": "SendFetchRequest",
            "length": 1,
            "peer": {"connectionId": "172.0.118.125:30002 167.235.223.34:5355"},
        },
        "sev": "Info",
        "thread": "88864",
        "host": "test-node",
    }


@pytest.fixture(scope="session")
def raw_completed_block_fetch() -> dict:
    return {
        "at": "2025-09-12T16:52:11.263418188Z",
        "ns": "BlockFetch.Client.CompletedBlockFetch",
        "data": {
            "block": "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1",
            "delay": 0.165,
            "kind": "CompletedBlockFetch",
            "peer": {"connectionId": "172.0.118.125:30002 167.235.223.34:5355"},
            "size": 87654,
        },
        "sev": "Info",
        "thread": "88863",
        "host": "test-node",
    }


@pytest.fixture(scope="session")
def raw_added_to_current_chain() -> dict:
    # Note: the hash in "headers" is intentionally double-quoted — that is
    # how cardano-tracer emits it and AddedToCurrentChainEvent.block_hash
    # must strip those quotes.
    return {
        "at": "2025-09-12T16:52:11.400000000Z",
        "ns": "ChainDB.AddBlockEvent.AddedToCurrentChain",
        "data": {
            "headers": [
                {
                    "blockNo": "3600148",
                    "hash": '"9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1"',
                    "kind": "ShelleyBlock",
                    "slotNo": "91039899",
                }
            ],
            "kind": "AddedToCurrentChain",
            "newtip": "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1@91039899",
        },
        "sev": "Notice",
        "thread": "27",
        "host": "test-node",
    }


# Parsed event model fixtures


@pytest.fixture(scope="session")
def downloaded_header_event(raw_downloaded_header):
    from openblockperf.models.events import DownloadedHeaderEvent

    return DownloadedHeaderEvent(**raw_downloaded_header)


@pytest.fixture(scope="session")
def send_fetch_request_event(raw_send_fetch_request):
    from openblockperf.models.events import SendFetchRequestEvent

    return SendFetchRequestEvent(**raw_send_fetch_request)


@pytest.fixture(scope="session")
def completed_block_fetch_event(raw_completed_block_fetch):
    from openblockperf.models.events import CompletedBlockFetchEvent

    return CompletedBlockFetchEvent(**raw_completed_block_fetch)


@pytest.fixture(scope="session")
def added_to_current_chain_event(raw_added_to_current_chain):
    from openblockperf.models.events import AddedToCurrentChainEvent

    return AddedToCurrentChainEvent(**raw_added_to_current_chain)


# Settings / config fixtures


@pytest.fixture
def default_settings() -> AppSettings:
    """Fresh AppSettings with all defaults (mainnet, no env overrides)."""
    return AppSettings()


@pytest.fixture
def preprod_settings() -> AppSettings:
    return AppSettings(network=Network.PREPROD)


@pytest.fixture
def mock_settings():
    """Minimal AppSettings mock — avoids reading .env / environment variables."""
    m = MagicMock(spec=AppSettings)
    m.network_config.starttime = 1591566291  # mainnet genesis
    m.network_config.magic = 764824073
    m.local_addr = "0.0.0.0"
    m.local_port = 3001
    return m
