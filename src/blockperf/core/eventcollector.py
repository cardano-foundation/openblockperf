"""
EventCollector

A data structure for collecting and grouping log events by common attributes,
primarily block number and block hash. This allows the EventProcessor to
organize events into logical groups for analysis and processing.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import rich

from blockperf.core.events import (
    AddedToCurrentChainEvent,
    CompletedBlockFetchEvent,
    DownloadedHeaderEvent,
    SwitchedToAForkEvent,
)


@dataclass
class EventGroup:
    """A group of log events for a given block hash."""

    block_hash: str
    events: list[Any] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    def add_event(self, event: Any):
        """Add an event to this group."""
        self.events.append(event)
        self.last_updated = time.time()

    def age(self) -> int:
        """Returns age of this group in seconds"""

        current_timestamp = int(time.time())
        age = current_timestamp - int(self.created_at)
        print(
            f"Group age {age} - created {self.created_at} - now {current_timestamp}"
        )
        return age

    def event_count(self) -> int:
        """Return the number of events in this group."""
        return len(self.events)

    def age_seconds(self) -> float:
        """Return how long ago this group was created (in seconds)."""
        return time.time() - self.created_at

    def get_event_types(self) -> set[str]:
        """Return set of unique event types in this group."""
        types = set()
        for event in self.events:
            if hasattr(event, "event_type"):
                types.add(event.event_type)
            elif hasattr(event, "__class__"):
                types.add(event.__class__.__name__)
        return types

    def get_first_downloaded_header(self) -> DownloadedHeaderEvent | None:
        """Returns the first DownloadedHeaderEvent or None"""
        for event in self.events():
            if type(event) is DownloadedHeaderEvent:
                return event
        return None

    def get_first_completed_block(self) -> CompletedBlockFetchEvent | None:
        """Returns the first CompletedBlockFetchEvent or None"""
        for event in self.events():
            if type(event) is DownloadedHeaderEvent:
                return event
        return None

    def get_block_adopted(
        self,
    ) -> AddedToCurrentChainEvent | SwitchedToAForkEvent | None:
        """ """
        pass

    def is_complete(self):
        """From the original:
        To be able to calculate the sample data for a given block_hash the
        following events need to have happend (recorded in the logs).

        * Must have completed download of header
        * Must have completed download of block
        * Must have found the fetch_request to the remote peer that
            the block was downloaded from
        * Must be adopted to the chain. Either AddedToCurrentChain or SwitchedToAFork
        """
        return True

    def sample(self):
        return {"some": 1, "dictionary": True}

    def __str__(self):
        return f"EventGroup(block_hash={self.block_hash if self.block_hash else None}, events={len(self.events)})"


class EventCollector:
    """
    Main data structure for collecting and organizing log events.

    Groups events by block number and hash, and provides various ways to
    access and analyze these groups.
    """

    def __init__(self):
        # Groups of events indexed by the block hash they belong to
        self.groups: dict[str, EventGroup] = {}

        # Group of events that couldn't be grouped by a block hash
        self.ungrouped_events: list[Any] = []

        # Statistics
        self.total_events_processed = 0
        self.total_groups_created = 0

    def add_event(self, event: Any) -> EventGroup | None:
        """
        Add an event to the collector. Attempts to group it by block attributes.

        Args:
            event: The event object to add

        Returns:
            The EventGroup the event was added to, or None if ungrouped
        """
        self.total_events_processed += 1

        # get block hash from event, but not all events have a block hash.
        block_hash = event.block_hash
        if not block_hash:
            self.ungrouped_events.append(event)
            return None

        # Create group key
        group_key = block_hash

        # Get or create the group
        if group_key in self.groups:
            group = self.groups[group_key]
        else:
            print(f"Create group: {block_hash}")
            group = EventGroup(block_hash=block_hash)
            self.groups[group_key] = group
            self.total_groups_created += 1

        # Add event to group
        group.add_event(event)
        return group

    def get_group(
        self,
        block_hash: str | None = None,
    ) -> EventGroup | None:
        """Get a specific event group by block number and/or hash."""
        if block_hash is not None:
            return self.groups.get(block_hash)
        return None

    def get_all_groups(self) -> list[EventGroup]:
        """Get all event groups."""
        return list(self.groups.values())

    def get_recent_groups(
        self, max_age_seconds: float = 300
    ) -> list[EventGroup]:
        """Get groups created within the last max_age_seconds."""
        current_time = time.time()
        return [
            group
            for group in self.groups.values()
            if (current_time - group.created_at) <= max_age_seconds
        ]

    def get_stale_groups(
        self, max_age_seconds: float = 3600
    ) -> list[EventGroup]:
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

    def remove_group(self, group: EventGroup):
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
                    "event_count": group.event_count(),
                    "age_seconds": round(group.age_seconds(), 2),
                    "last_update_seconds_ago": round(
                        group.time_since_last_update(), 2
                    ),
                    "event_types": list(group.get_event_types()),
                }
            )
        return summary

    def __len__(self):
        """Return total number of groups."""
        return len(self.groups)

    def __str__(self):
        return f"EventCollector(groups={len(self.groups)}, events={self.total_events_processed})"
