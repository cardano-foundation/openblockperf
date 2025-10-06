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
from blockperf.logging import logger
from blockperf.models.event import (
    AddedToCurrentChainEvent,
    BaseEvent,
    BlockSample,
    CompletedBlockFetchEvent,
    DemotedToColdRemoteEvent,
    DemotedToWarmRemoteEvent,
    DownloadedHeaderEvent,
    InboundGovernorCountersEvent,
    PromotedToHotRemoteEvent,
    PromotedToWarmRemoteEvent,
    SendFetchRequestEvent,
    StartedEvent,
    StatusChangedEvent,
    SwitchedToAForkEvent,
)
from blockperf.models.peer import Peer, PeerDirection, PeerState


class EventCollector:
    """
    Main data structure for collecting and organizing all log events for a specific host.

    Groups events by block number and hash, and provides various ways to
    access and analyze these groups.
    """

    host: str

    def __init__(self):
        # Groups of events indexed by the block hash they belong to
        self.block_event_groups: dict[str, str] = {}

        # Statistics
        self.total_events_processed = 0
        self.total_groups_created = 0

    def add_event(self, event: BaseEvent) -> None:
        """
        Add an event to the collector, depending on the events type.

        If the event is one of the block sample events it will be stored in
        an instance of a BlockEventGroup.

        If the event is a change in the nodes peers the peers list of
        the collector will be updated accordingly. These events are not stored.
        """
        # Events relevant for block sample calculation

        # Events relevant for peers calculation
        peer_events = (
            PromotedToHotRemoteEvent,
            PromotedToWarmRemoteEvent,
            DemotedToColdRemoteEvent,
            DemotedToWarmRemoteEvent,
            StatusChangedEvent,
        )

        if isinstance(event, peer_events):
            rich.print(event)
            self.add_peer_event(event)
        elif isinstance(event, StartedEvent):
            rich.print("[bold blue]Node restarted[/]")
            self.peers = {}
        elif isinstance(event, InboundGovernorCountersEvent):
            rich.print(event)
        else:
            rich.print(event)

    def add_peer_event(self, event: BaseEvent):
        """Add given peer event"""
        logger.info(f"Adding peer event {event.__class__.__name__}")
        # Get addr and port of peer to identify in peers list
        addr, port = event.remote_addr_port()
        key = (addr, port)
        if key not in self.peers:
            self.peers[key] = Peer(addr=addr, port=port)
            logger.debug(f"{self.peers[key]} created")
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

    def __str__(self):
        return f"<EventCollector(block_event_groups={len(self.block_event_groups)}, events={self.total_events_processed})>"
