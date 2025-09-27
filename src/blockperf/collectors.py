"""
EventCollector

A data structure for collecting and grouping log events by common attributes,
primarily block number and block hash. This allows the EventProcessor to
organize events into logical groups for analysis and processing.
"""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Literal

import rich

from blockperf import __version__
from blockperf.config import settings
from blockperf.errors import EventError
from blockperf.models import (
    AddedToCurrentChainEvent,
    BaseBlockEvent,
    CompletedBlockFetchEvent,
    DemotedToColdRemoteEvent,
    DemotedToWarmRemoteEvent,
    DownloadedHeaderEvent,
    InboundGovernorCountersEvent,
    Peer,
    PeerDirection,
    PeerState,
    PromotedToHotRemoteEvent,
    PromotedToWarmRemoteEvent,
    SendFetchRequestEvent,
    StartedEvent,
    StatusChangedEvent,
    SwitchedToAForkEvent,
)


@dataclass
class BlockEventGroup:
    """A group of log events for a given block hash."""

    block_hash: str
    block_number: int | None = None
    block_size: int | None = None
    block_g: float | None = 0.1
    slot: int | None = None  # the slot number
    slot_time: datetime | None = None

    # The following are key events we want to find in the logs
    # A block was first announced to the
    block_header: DownloadedHeaderEvent | None = None
    # A block was requested for download
    block_requested: SendFetchRequestEvent | None = None
    # A block finished download
    block_completed: CompletedBlockFetchEvent | None = None

    events: list[BaseBlockEvent] = field(default_factory=list)  # list of events
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    def add_event(self, event: BaseBlockEvent):
        """Add an event to this group. Fill in missing values that only some types of events provide"""
        self.events.append(event)
        self.last_updated = time.time()

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
            "local_addr": settings().local_addr,
            "local_port": int(settings().local_port),
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
    Main data structure for collecting and organizing all log events for a specific host.

    Groups events by block number and hash, and provides various ways to
    access and analyze these groups.
    """

    host: str
    peers: dict[tuple, Peer] = {}

    def __init__(self):
        # Groups of events indexed by the block hash they belong to
        self.block_event_groups: dict[str, BlockEventGroup] = {}

        # Statistics
        self.total_events_processed = 0
        self.total_groups_created = 0

    def add_event(self, event: BaseBlockEvent) -> None:
        """
        Add an event to the collector, depending on the events type.

        If the event is one of the block sample events it will be stored in
        an instance of a BlockEventGroup.

        If the event is a change in the nodes peers the peers list of
        the collector will be updated accordingly. These events are not stored.
        """
        # Events relevant for block sample calculation
        blocksample_events = (
            CompletedBlockFetchEvent,
            SendFetchRequestEvent,
            AddedToCurrentChainEvent,
            SwitchedToAForkEvent,
            DownloadedHeaderEvent,
        )
        # Events relevant for peers calculation
        peer_events = (
            PromotedToHotRemoteEvent,
            PromotedToWarmRemoteEvent,
            DemotedToColdRemoteEvent,
            DemotedToWarmRemoteEvent,
            StatusChangedEvent,
        )

        if isinstance(event, blocksample_events):
            # self.add_blocksample_event(event)
            pass
        elif isinstance(event, peer_events):
            rich.print(event)
            self.add_peer_event(event)
        elif isinstance(event, StartedEvent):
            rich.print("[bold blue]Node restarted[/]")
            self.peers = {}
        elif isinstance(event, InboundGovernorCountersEvent):
            rich.print(event)
        else:
            rich.print(event)

    def add_blocksample_event(self, event: BaseBlockEvent):
        """Add given blocksample to a BlockEventGroup for that events block_hash."""
        try:
            block_hash = event.block_hash
            if not block_hash:
                raise (
                    f"[bold yellow]Event without block_hash found {event}[/]"
                )

            if block_hash not in self.block_event_groups:
                self.block_event_groups[block_hash] = BlockEventGroup(
                    block_hash=block_hash
                )
            group = self.block_event_groups[block_hash]
            group.add_event(event)
        except EventError as e:
            rich.print(e)

    def update_peers(self, peers: list) -> None:
        """Add given list of peer to the internal peers list."""
        keys = []
        for peer in peers:
            if not isinstance(peer, Peer):
                raise RuntimeError("Given peer is not of type Peer")
            key = (peer.addr, peer.port)
            keys.append(key)  # store keys for later
            if key not in self.peers:
                self.peers[key] = peer
        # From the self.peers list, remove the ones without a connection
        keys_to_remove = []
        for k in self.peers:
            if k not in keys:
                keys_to_remove.append(k)

        if keys_to_remove:
            rich.print(f"[bold red]Removing {keys_to_remove} from peers[/]")
            for k in keys_to_remove:
                del self.peers[k]

    def add_peer_event(self, event: BaseBlockEvent):
        """Add given peer event"""

        # Get addr and port of peer to identify in peers list
        addr, port = event.peer_addr_port()
        key = (addr, port)
        if key not in self.peers:
            self.peers[key] = Peer(addr=addr, port=port)
        peer = self.peers[key]  # esier to refer to peer then self.peers[key]
        peer.state = event.state
        if not peer.direction:
            if d := event.direction():
                peer.direction = d

        rich.print(peer)

        # if isinstance(event, StatusChangedEvent):
        #    pass
        # elif isinstance(event, DemotedToColdRemoteEvent):
        #    pass
        # elif isinstance(event, (DemotedToWarmRemoteEvent, PromotedToWarmRemoteEvent)):  # fmt: off
        #    pass
        # elif isinstance(event, PromotedToHotRemoteEvent):
        #    pass

    def get_all_groups(self) -> list[BlockEventGroup]:
        """Get all event groups."""
        return list(self.block_event_groups.values())

    def get_peer_statistics(self):
        peers = self.peers.values()
        cold = [p for p in peers if p.state == PeerState.COLD]
        warm = [p for p in peers if p.state == PeerState.WARM]
        hot = [p for p in peers if p.state == PeerState.HOT]
        cooling = [p for p in peers if p.state == PeerState.COOLING]
        unknown = [p for p in peers if p.state == PeerState.UNKNOWN]
        return {
            "cold": len(cold),
            "warm": len(warm),
            "hot": len(hot),
            "cooling": len(cooling),
            "unknown": len(unknown),
            "total": len(self.peers),
        }

    def __str__(self):
        return f"EventCollector(block_event_groups={len(self.block_event_groups)}, events={self.total_events_processed})"
