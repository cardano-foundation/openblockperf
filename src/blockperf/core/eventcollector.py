"""
EventCollector

A data structure for collecting and grouping log events by common attributes,
primarily block number and block hash. This allows the EventProcessor to
organize events into logical groups for analysis and processing.
"""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import rich

from blockperf import __version__
from blockperf.core.config import settings
from blockperf.core.events import (
    AddedToCurrentChainEvent,
    CompletedBlockFetchEvent,
    DownloadedHeaderEvent,
    EventError,
    SendFetchRequestEvent,
    SwitchedToAForkEvent,
)


@dataclass
class BlockEventGroup:
    """A group of log events for a given block hash."""

    host: str
    block_hash: str
    block_number: int | None = None
    block_size: int | None = None
    block_g: str | None = "?"
    slot: int | None = None  # the slot number
    slot_time: datetime | None = None

    # The following are key events we want to find in the logs
    # A block was first announced to the
    block_header: DownloadedHeaderEvent | None = None
    # A block was requested for download
    block_requested: SendFetchRequestEvent | None = None
    # A block finished download
    block_completed: CompletedBlockFetchEvent | None = None

    events: list[Any] = field(default_factory=list)  # list of events
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    def add_event(self, event: Any):
        """Add an event to this group. Fill in missing values that only some types of events provide"""
        self.events.append(event)
        self.last_updated = time.time()

        if not self.host:
            self.host = event.host

        if isinstance(event, DownloadedHeaderEvent):
            if not self.block_header:
                rich.print(
                    f"Header\t\t{event.block_hash[:8]} from {event.peer_ip}"
                )
                self.block_header = event
            # these should all be the same for all header events
            if not self.slot:
                self.slot = event.slot
            if not self.slot_time:
                self.slot_time = datetime.fromtimestamp(
                    settings().network_config.starttime + self.slot, tz=UTC
                )
            if not self.block_number:
                self.block_number = event.block_number
        elif isinstance(event, SendFetchRequestEvent):
            # self.block_requested will be set when the node actually did download
            # that block and completed it.
            rich.print(
                f"Requested\t{event.block_hash[:8]} from {event.peer_ip}"
            )
        elif isinstance(event, CompletedBlockFetchEvent):
            rich.print(
                f"Downloaded\t{event.block_hash[:8]} from {event.peer_ip}"
            )
            if not self.block_completed:
                self.block_completed = event
                # Now that we have a block downloaded, find the fetch request for it
                block_requested = self._get_fetch_for_completed(event)
                if not block_requested:
                    # This should not happen! We can not have a completed
                    # block event without having asked for it before
                    raise EventError(f"No send fetch found for {event}")
                self.block_requested = block_requested
            if not self.block_size:
                self.block_size = event.block_size

        elif isinstance(event, AddedToCurrentChainEvent):
            rich.print(f"Added\t\t{event.block_hash[:8]} to chain")
        elif isinstance(event, SwitchedToAForkEvent):
            rich.print(f"Switched \t{event.block_hash[:8]} to fork")

    @property
    def event_count(self) -> int:
        """Return the number of events in this group."""
        return len(self.events)

    @property
    def age_seconds(self) -> int:
        """Age of this group in seconds"""
        # rounding to full seconds (up/down)
        return round(time.time() - self.created_at)

    @property
    def event_types(self) -> set[str]:
        """Set of unique event types in this group."""
        types = set()
        for event in self.events:
            if hasattr(event, "event_type"):
                types.add(event.event_type)
            elif hasattr(event, "__class__"):
                types.add(event.__class__.__name__)
        return types

    @property
    def block_adopted(self) -> AddedToCurrentChainEvent | SwitchedToAForkEvent | None:  # fmt: skip
        for event in self.events:
            # i assume there can never be both ...
            if type(event) in [AddedToCurrentChainEvent, SwitchedToAForkEvent]:
                return event
        return None

    @property
    def header_delta(self) -> timedelta:
        """Returns the header delta.

        The header delta is the time between when this node first got note
        of this block by receiving a header of it versus the time of the slot
        the block was recorded it.
        """
        return self.block_header.at - self.slot_time

    @property
    def block_request_delta(self) -> datetime:
        """Returns the block request delta.

        The delta between when this node first got notice of this block
        (the time when it first received a header) vs when the node asked
        for the block to get downloaded (send a fetch request).
        """
        return self.block_requested.at - self.block_header.at

    @property
    def block_response_delta(self) -> timedelta:
        """Returns the block response delta.

        The delta between when this node first asked for a block (send a
        fetch request) versus when it did actually finished downloading.
        """
        return self.block_completed.at - self.block_requested.at

    @property
    def block_adopt_delta(self) -> timedelta:
        """Returns the block adopt delta.

        The delta between when this node completed the download of a
        block versus when it was actually adopted (by this node).
        """
        return self.block_adopted.at - self.block_completed.at

    @property
    def is_complete(self) -> bool:
        """Ensure all events to calculate sample are collected.

        * Must have seen the block header
        * Must have requested the block
        * Must have downloaded the block
        * Must have adopted the block - Either AddedToCurrentChain or SwitchedToAFork
        """
        return (
            self.block_header
            and self.block_requested
            and self.block_completed
            and self.block_adopted
        )

    def is_sane(self) -> bool:
        """Checks all values are within acceptable ranges.

        We did see wild values of these pop up in the past for all kinds of
        reasons. This tries to do some basic checking that the values are in
        a realistic range.
        """

        _header_delta = int(self.header_delta.total_seconds() * 1000)
        _block_request_delta = int(self.block_request_delta.total_seconds() * 1000)  # fmt: off
        _block_response_delta = int(self.block_response_delta.total_seconds() * 1000)  # fmt: off
        _block_adopt_delta = int(self.block_adopt_delta.total_seconds() * 1000)
        return (
            self.block_number > 0
            and self.slot > 0
            and 0 < len(self.block_hash) < 128  # noqa: PLR2004
            and 0 < self.block_size < 10000000  # noqa: PLR2004
            and -6000 < _header_delta < 600000  # noqa: PLR2004
            and -6000 < _block_request_delta < 600000  # noqa: PLR2004
            and -6000 < _block_response_delta < 600000  # noqa: PLR2004
            and -6000 < _block_adopt_delta < 600000  # noqa: PLR2004
        )

    # fmt: off
    def sample(self):
        return {
            "host": self.host,
            "block_hash": self.block_hash,
            "block_number": self.block_number,
            "block_size": self.block_size,
            "block_g": self.block_g,
            "slot": self.slot,
            "slot_time": self.slot_time.isoformat(),
            "header_remote_addr": self.block_header.peer_ip,
            "header_remote_port": self.block_header.peer_port,
            "header_delta": int(self.header_delta.total_seconds() * 1000),
            "block_remote_addr": self.block_completed.peer_ip,
            "block_remote_port": self.block_completed.peer_port,
            "block_request_delta": int(self.block_request_delta.total_seconds() * 1000),
            "block_response_delta": int(self.block_response_delta.total_seconds() * 1000),
            "block_adopt_delta": int(self.block_adopt_delta.total_seconds() * 1000),
            "local_addr": "185.175.59.38",
            "local_port": "3001",
            "magic": settings().network_config.magic,
            "client_version": __version__,
        }

    # fmt: on

    def _get_fetch_for_completed(self, event: CompletedBlockFetchEvent):
        for e in self.events:
            if (
                isinstance(e, SendFetchRequestEvent)
                and e.peer_ip == event.peer_ip
                and e.peer_port == event.peer_port
            ):
                return e
        return None

    def __str__(self):
        return f"BlockEventGroup(block_hash={self.block_hash if self.block_hash else None}, events={len(self.events)})"


class EventCollector:
    """
    Main data structure for collecting and organizing log events.

    Groups events by block number and hash, and provides various ways to
    access and analyze these groups.
    """

    def __init__(self):
        # Groups of events indexed by the block hash they belong to
        self.groups: dict[str, BlockEventGroup] = {}

        # Group of events that couldn't be grouped by a block hash
        self.ungrouped_events: list[Any] = []

        # Statistics
        self.total_events_processed = 0
        self.total_groups_created = 0

    def add_event(self, event: Any) -> bool:
        """
        Add an event to the collector. Attempts to group it by block attributes.

        Args:
            event: The event object to add

        Returns:
            The EventGroup the event was added to, or None if ungrouped
        """
        try:
            self.total_events_processed += 1
            block_hash = event.block_hash
            if not block_hash:
                self.ungrouped_events.append(event)
                rich.print(f"[bold yellow]Found ungrouped event {event}[/]")
                return None
            group = self._get_or_create_group(block_hash)
            group.add_event(event)
            return True
        except EventError as e:
            rich.print(e)
            return False

    def _get_or_create_group(self, block_hash) -> BlockEventGroup:
        """Returns the group with given hash, creates a new group if needed."""
        if block_hash in self.groups:
            group = self.groups[block_hash]
        else:
            rich.print(f"[bold magenta]New block: {block_hash}[/]")
            group = BlockEventGroup(block_hash=block_hash)
            self.groups[block_hash] = group
            self.total_groups_created += 1

        if not group:
            raise EventError(f"Could not find group for {block_hash}")

        return group

    def get_group(
        self,
        block_hash: str | None = None,
    ) -> BlockEventGroup | None:
        """Get a specific event group by block number and/or hash."""
        if block_hash is not None:
            return self.groups.get(block_hash)
        return None

    def get_all_groups(self) -> list[BlockEventGroup]:
        """Get all event groups."""
        return list(self.groups.values())

    def get_recent_groups(
        self, max_age_seconds: float = 300
    ) -> list[BlockEventGroup]:
        """Get groups created within the last max_age_seconds."""
        current_time = time.time()
        return [
            group
            for group in self.groups.values()
            if (current_time - group.created_at) <= max_age_seconds
        ]

    def get_stale_groups(
        self, max_age_seconds: float = 3600
    ) -> list[BlockEventGroup]:
        """Get groups that haven't been updated in max_age_seconds."""
        return [
            group
            for group in self.groups.values()
            if group.time_since_last_update() > max_age_seconds
        ]

    def cleanup_old_groups(self, max_age_seconds: float = 3600) -> int:
        """Remove groups older than max_age_seconds. Returns number removed."""
        stale_groups = self.get_stale_groups(max_age_seconds)
        removed_count = 0

        for group in stale_groups:
            self._remove_group(group)
            removed_count += 1

        return removed_count

    def _remove_group_by_hash(self, block_hash):
        if block_hash in self.groups:
            del self.groups[block_hash]

    def remove_group(self, group: BlockEventGroup):
        self._remove_group_by_hash(group.block_hash)

    def get_statistics(self) -> dict[str, Any]:
        """Get collector statistics."""
        return {
            "total_events_processed": self.total_events_processed,
            "total_groups": len(self.groups),
            "total_groups_created": self.total_groups_created,
            "ungrouped_events": len(self.ungrouped_events),
        }

    def get_group_summary(self) -> list[dict[str, Any]]:
        """Get a summary of all groups for debugging/monitoring."""
        summary = []
        for group in self.groups.values():
            summary.append(
                {
                    "block_hash": group.block_hash[:8]
                    if group.block_hash
                    else None,
                    "event_count": group.event_count,
                    "age_seconds": group.age_seconds,
                    "event_types": list(group.event_types),
                }
            )
        return summary

    def __len__(self):
        """Return total number of groups."""
        return len(self.groups)

    def __str__(self):
        return f"EventCollector(groups={len(self.groups)}, events={self.total_events_processed})"
