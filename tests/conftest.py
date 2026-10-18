"""Shared pytest fixtures for the openblockperf test suite."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openblockperf.config import AppSettings, Network

# Shared with the Rust spike under rust/. Keep payloads in testdata/.
_TESTDATA = Path(__file__).resolve().parents[1] / "testdata"


def _load_testdata_json(relative: str) -> dict:
    path = _TESTDATA / relative
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Raw event payloads (from testdata/events/)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def raw_downloaded_header() -> dict:
    return _load_testdata_json("events/downloaded_header.json")


@pytest.fixture(scope="session")
def raw_send_fetch_request() -> dict:
    return _load_testdata_json("events/send_fetch_request.json")


@pytest.fixture(scope="session")
def raw_completed_block_fetch() -> dict:
    return _load_testdata_json("events/completed_block_fetch.json")


@pytest.fixture(scope="session")
def raw_added_to_current_chain() -> dict:
    # Note: the hash in "headers" is intentionally double-quoted — that is
    # how cardano-tracer emits it and AddedToCurrentChainEvent.block_hash
    # must strip those quotes. See testdata/events/added_to_current_chain.json.
    return _load_testdata_json("events/added_to_current_chain.json")


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
