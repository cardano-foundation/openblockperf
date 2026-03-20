"""Tests for openblockperf.models.events

Covers:
- DownloadedHeaderEvent: field parsing, property accessors
- SendFetchRequestEvent: block hash, peer addresses
- CompletedBlockFetchEvent: block hash, size, delay
- AddedToCurrentChainEvent: the double-quoted hash quirk, missing headers
- SwitchedToAForkEvent: same double-quote stripping as AddedToCurrentChain
"""

import pytest
from pydantic import ValidationError

from openblockperf.models.events.event import (
    AddedToCurrentChainEvent,
    CompletedBlockFetchEvent,
    DownloadedHeaderEvent,
    SendFetchRequestEvent,
    SwitchedToAForkEvent,
)

BLOCK_HASH = "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1"


class TestDownloadedHeaderEvent:
    def test_parses_without_error(self, downloaded_header_event):
        assert downloaded_header_event is not None

    def test_block_hash(self, downloaded_header_event):
        assert downloaded_header_event.block_hash == BLOCK_HASH

    def test_block_number(self, downloaded_header_event):
        assert downloaded_header_event.block_number == 3600148

    def test_slot(self, downloaded_header_event):
        assert downloaded_header_event.slot == 91039899

    def test_remote_addr(self, downloaded_header_event):
        assert downloaded_header_event.remote_addr == "167.235.223.34"

    def test_remote_port(self, downloaded_header_event):
        assert downloaded_header_event.remote_port == 5355

    def test_at_is_timezone_aware(self, downloaded_header_event):
        assert downloaded_header_event.at.tzinfo is not None

    # TODO: test that missing 'peer' key raises ValidationError
    # TODO: test with an IPv6 peer connectionId


class TestSendFetchRequestEvent:
    def test_block_hash(self, send_fetch_request_event):
        assert send_fetch_request_event.block_hash == BLOCK_HASH

    def test_remote_addr(self, send_fetch_request_event):
        assert send_fetch_request_event.remote_addr == "167.235.223.34"

    def test_remote_port(self, send_fetch_request_event):
        assert send_fetch_request_event.remote_port == 5355

    # TODO: test length field is accessible via raw data dict


class TestCompletedBlockFetchEvent:
    def test_block_hash(self, completed_block_fetch_event):
        assert completed_block_fetch_event.block_hash == BLOCK_HASH

    def test_block_size(self, completed_block_fetch_event):
        assert completed_block_fetch_event.block_size == 87654

    def test_delay(self, completed_block_fetch_event):
        assert completed_block_fetch_event.delay == pytest.approx(0.165)

    def test_remote_addr(self, completed_block_fetch_event):
        assert completed_block_fetch_event.remote_addr == "167.235.223.34"

    # TODO: test zero-size block raises or is handled gracefully


class TestAddedToCurrentChainEvent:
    """
    The ``hash`` field inside ``data.headers[0]`` arrives with surrounding
    double-quotes from cardano-tracer, e.g. ``'"abc123"'``.
    ``block_hash`` must strip them.
    """

    def test_block_hash_equals_bare_hash(self, added_to_current_chain_event):
        assert added_to_current_chain_event.block_hash == BLOCK_HASH

    def test_block_hash_has_no_leading_quote(self, added_to_current_chain_event):
        assert not added_to_current_chain_event.block_hash.startswith('"')

    def test_block_hash_has_no_trailing_quote(self, added_to_current_chain_event):
        assert not added_to_current_chain_event.block_hash.endswith('"')

    def test_raises_when_headers_key_missing(self):
        event = AddedToCurrentChainEvent(
            at="2025-09-12T16:52:11.400000000Z",
            ns="ChainDB.AddBlockEvent.AddedToCurrentChain",
            data={"kind": "AddedToCurrentChain"},  # no "headers"
            sev="Notice",
            thread="27",
            host="test-node",
        )
        with pytest.raises(Exception):  # EventError
            _ = event.block_hash

    def test_raises_when_headers_is_empty_list(self):
        event = AddedToCurrentChainEvent(
            at="2025-09-12T16:52:11.400000000Z",
            ns="ChainDB.AddBlockEvent.AddedToCurrentChain",
            data={"kind": "AddedToCurrentChain", "headers": []},
            sev="Notice",
            thread="27",
            host="test-node",
        )
        with pytest.raises(Exception):  # EventError
            _ = event.block_hash

    # TODO: test event with hash that has only a leading quote (no trailing)
    # TODO: test event with hash that has no quotes at all (should still work)


class TestSwitchedToAForkEvent:
    """SwitchedToAFork has the same double-quoted hash behaviour."""

    def test_block_hash_strips_quotes(self):
        fork_hash = "838498b0cc666026ec366199ec89afd67a2febc932816acef9bbd2a1f59689a5"
        event = SwitchedToAForkEvent(
            at="2025-09-12T16:51:18.698911267Z",
            ns="ChainDB.AddBlockEvent.SwitchedToAFork",
            data={
                "headers": [
                    {
                        "blockNo": "3600147",
                        "hash": f'"{fork_hash}"',
                        "kind": "ShelleyBlock",
                        "slotNo": "91039878",
                    }
                ],
                "kind": "TraceAddBlockEvent.SwitchedToAFork",
            },
            sev="Notice",
            thread="27",
            host="test-node",
        )
        assert event.block_hash == fork_hash

    # TODO: test raises when headers missing (same as AddedToCurrentChain)
