"""Tests for openblockperf.blocksamplegroup.BlockSampleGroup

Covers:
- Initial state after construction
- add_event() side-effects per event type
- is_complete(): true only when all four event types are present
- is_sane(): value-range validation
- Delta properties: header_delta, block_request_delta, block_response_delta, block_adopt_delta
- block_adopted property
- _get_fetch_for_completed: matching by remote addr+port
"""

import pytest

from openblockperf.blocksamplegroup import BlockSampleGroup

BLOCK_HASH = "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1"


@pytest.fixture
def empty_group(mock_settings):
    """A brand-new BlockSampleGroup with no events."""
    return BlockSampleGroup(block_hash=BLOCK_HASH, settings=mock_settings)


@pytest.fixture
def complete_group(
    empty_group,
    downloaded_header_event,
    send_fetch_request_event,
    completed_block_fetch_event,
    added_to_current_chain_event,
):
    """Group with all four required events added in chronological order."""
    empty_group.add_event(downloaded_header_event)
    empty_group.add_event(send_fetch_request_event)
    empty_group.add_event(completed_block_fetch_event)
    empty_group.add_event(added_to_current_chain_event)
    return empty_group


class TestBlockSampleGroupInit:
    def test_block_hash_stored(self, empty_group):
        assert empty_group.block_hash == BLOCK_HASH

    def test_starts_empty(self, empty_group):
        assert empty_group.event_count == 0

    def test_not_complete_when_empty(self, empty_group):
        assert not empty_group.is_complete()

    def test_block_header_is_none(self, empty_group):
        assert empty_group.block_header is None

    def test_block_adopted_is_none_when_empty(self, empty_group):
        assert empty_group.block_adopted is None


class TestAddEvent:
    def test_downloaded_header_increments_count(self, empty_group, downloaded_header_event):
        empty_group.add_event(downloaded_header_event)
        assert empty_group.event_count == 1

    def test_downloaded_header_sets_block_number(self, empty_group, downloaded_header_event):
        empty_group.add_event(downloaded_header_event)
        assert empty_group.block_number == 3600148

    def test_downloaded_header_sets_slot(self, empty_group, downloaded_header_event):
        empty_group.add_event(downloaded_header_event)
        assert empty_group.slot == 91039899

    def test_downloaded_header_sets_slot_time(self, empty_group, downloaded_header_event):
        empty_group.add_event(downloaded_header_event)
        assert empty_group.slot_time is not None

    def test_completed_fetch_sets_block_size(
        self,
        empty_group,
        downloaded_header_event,
        send_fetch_request_event,
        completed_block_fetch_event,
    ):
        empty_group.add_event(downloaded_header_event)
        empty_group.add_event(send_fetch_request_event)
        empty_group.add_event(completed_block_fetch_event)
        assert empty_group.block_size == 87654

    def test_completed_fetch_links_send_fetch_request(
        self,
        empty_group,
        downloaded_header_event,
        send_fetch_request_event,
        completed_block_fetch_event,
    ):
        empty_group.add_event(downloaded_header_event)
        empty_group.add_event(send_fetch_request_event)
        empty_group.add_event(completed_block_fetch_event)
        assert empty_group.block_requested is not None

    def test_completed_fetch_without_prior_send_fetch_raises(
        self,
        empty_group,
        downloaded_header_event,
        completed_block_fetch_event,
    ):
        """CompletedBlockFetch with no matching SendFetchRequest must raise."""
        from openblockperf.errors import EventError

        empty_group.add_event(downloaded_header_event)
        with pytest.raises(EventError):
            empty_group.add_event(completed_block_fetch_event)

    # TODO: test that adding a second DownloadedHeader with an *earlier* timestamp
    #       replaces the stored block_header (the "new first header" logic)


class TestIsComplete:
    def test_complete_with_all_four_events(self, complete_group):
        assert complete_group.is_complete()

    def test_incomplete_missing_adopt(
        self,
        empty_group,
        downloaded_header_event,
        send_fetch_request_event,
        completed_block_fetch_event,
    ):
        empty_group.add_event(downloaded_header_event)
        empty_group.add_event(send_fetch_request_event)
        empty_group.add_event(completed_block_fetch_event)
        assert not empty_group.is_complete()

    def test_incomplete_only_header(self, empty_group, downloaded_header_event):
        empty_group.add_event(downloaded_header_event)
        assert not empty_group.is_complete()

    # TODO: test is_complete() with SwitchedToAFork as the adopt event


# ---------------------------------------------------------------------------
# Delta properties
# All four events in complete_group are stamped on 2025-09-12 in chronological
# order, so every delta must be >= 0.
# ---------------------------------------------------------------------------


class TestDeltas:
    def test_header_delta_is_timedelta(self, complete_group):
        from datetime import timedelta

        assert isinstance(complete_group.header_delta, timedelta)

    def test_block_request_delta_non_negative(self, complete_group):
        assert complete_group.block_request_delta.total_seconds() >= 0

    def test_block_response_delta_non_negative(self, complete_group):
        assert complete_group.block_response_delta.total_seconds() >= 0

    def test_block_adopt_delta_non_negative(self, complete_group):
        assert complete_group.block_adopt_delta.total_seconds() >= 0

    # TODO: test that deltas are in the expected rough magnitude
    #       (e.g. block_response_delta ≈ 0.165 s from the fixture data)


# is_sane()
# The fixture events use slot 91039899 against mainnet starttime, which places
# slot_time in 2023.  The header event is from 2025, so header_delta >> 600 s
# and is_sane() will return False for these fixtures.
# Use this section to add purpose-built fixtures with calibrated timestamps.


class TestIsSane:
    @pytest.mark.skip(reason="Needs fixtures with timestamps calibrated to slot_time")
    def test_complete_group_with_realistic_deltas_is_sane(self, complete_group):
        assert complete_group.is_sane()

    @pytest.mark.skip(reason="Needs fixtures with timestamps calibrated to slot_time")
    def test_group_with_huge_header_delta_is_not_sane(self, complete_group):
        # TODO: craft an event whose header arrives > 600 s after slot_time
        pass

    # TODO: test zero block_size is rejected
    # TODO: test negative deltas are rejected
    # TODO: test block_number == 0 is rejected


class TestBlockAdopted:
    def test_returns_added_to_current_chain_event(self, complete_group, added_to_current_chain_event):
        from openblockperf.models.events import AddedToCurrentChainEvent

        assert isinstance(complete_group.block_adopted, AddedToCurrentChainEvent)

    def test_returns_none_before_adopt_event(
        self,
        empty_group,
        downloaded_header_event,
        send_fetch_request_event,
        completed_block_fetch_event,
    ):
        empty_group.add_event(downloaded_header_event)
        empty_group.add_event(send_fetch_request_event)
        empty_group.add_event(completed_block_fetch_event)
        assert empty_group.block_adopted is None

    # TODO: test that SwitchedToAFork is also recognised as a valid adopt event


class TestHeaderAnnouncers:
    def test_tracks_up_to_three_unique_announcers(
        self,
        empty_group,
        raw_downloaded_header,
    ):
        from copy import deepcopy
        from datetime import timedelta

        from openblockperf.models.events import DownloadedHeaderEvent

        base = DownloadedHeaderEvent(**raw_downloaded_header)
        peers = [
            ("10.0.0.1", 3001),
            ("10.0.0.2", 3002),
            ("10.0.0.3", 3003),
            ("10.0.0.4", 3004),
        ]
        for i, (addr, port) in enumerate(peers):
            raw = deepcopy(raw_downloaded_header)
            raw["at"] = (base.at + timedelta(milliseconds=i)).isoformat().replace("+00:00", "Z")
            raw["data"] = dict(raw["data"])
            raw["data"]["peer"] = {"connectionId": f"172.0.118.125:30002 {addr}:{port}"}
            empty_group.add_event(DownloadedHeaderEvent(**raw))

        assert len(empty_group.header_announcers) == 3
        assert empty_group.header_announcer_ips == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
        assert empty_group.header_announcer_rank("10.0.0.2") == 2
        assert empty_group.header_announcer_rank("10.0.0.4") is None

    def test_get_sample_fills_header2_header3(
        self,
        empty_group,
        raw_downloaded_header,
        raw_send_fetch_request,
        raw_completed_block_fetch,
        raw_added_to_current_chain,
    ):
        from copy import deepcopy
        from datetime import datetime, timedelta

        from openblockperf.models.events import (
            AddedToCurrentChainEvent,
            CompletedBlockFetchEvent,
            DownloadedHeaderEvent,
            SendFetchRequestEvent,
        )

        def header_at(addr: str, port: int, ms: int) -> DownloadedHeaderEvent:
            raw = deepcopy(raw_downloaded_header)
            base_at = datetime.fromisoformat(raw_downloaded_header["at"].replace("Z", "+00:00"))
            raw["at"] = (base_at + timedelta(milliseconds=ms)).isoformat().replace("+00:00", "Z")
            raw["data"] = dict(raw["data"])
            raw["data"]["peer"] = {"connectionId": f"172.0.118.125:30002 {addr}:{port}"}
            return DownloadedHeaderEvent(**raw)

        empty_group.add_event(header_at("203.0.113.1", 3001, 0))
        empty_group.add_event(header_at("203.0.113.2", 6000, 1))
        empty_group.add_event(header_at("203.0.113.3", 7000, 2))
        empty_group.add_event(SendFetchRequestEvent(**raw_send_fetch_request))
        empty_group.add_event(CompletedBlockFetchEvent(**raw_completed_block_fetch))
        empty_group.add_event(AddedToCurrentChainEvent(**raw_added_to_current_chain))

        sample = empty_group.get_sample()
        assert sample.header_remote_addr == "203.0.113.1"
        assert sample.header_remote_port == 3001
        assert sample.header2_remote_addr == "203.0.113.2"
        assert sample.header2_remote_port == 6000
        assert sample.header3_remote_addr == "203.0.113.3"
        assert sample.header3_remote_port == 7000

    def test_get_sample_empty_header2_header3_when_single_announcer(self, complete_group):
        sample = complete_group.get_sample()
        assert sample.header2_remote_addr == ""
        assert sample.header2_remote_port == 0
        assert sample.header3_remote_addr == ""
        assert sample.header3_remote_port == 0
