import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Literal

import rich

from blockperf import __version__
from blockperf.blockeventgroup import BlockEventGroup
from blockperf.config import settings
from blockperf.errors import EventError
from blockperf.listeners.base import EventListener
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


class BlockListener(EventListener):
    """The BlockListener collects data about block propagation.

    We want to measure
        * When was a given block first seen
        * Wenn did
    """

    registered_namespaces = {
        "BlockFetch.Client.CompletedBlockFetch": CompletedBlockFetchEvent,
        "BlockFetch.Client.SendFetchRequest": SendFetchRequestEvent,
        "ChainDB.AddBlockEvent.AddedToCurrentChain": AddedToCurrentChainEvent,
        "ChainDB.AddBlockEvent.SwitchedToAFork": SwitchedToAForkEvent,
        "ChainSync.Client.DownloadedHeader": DownloadedHeaderEvent,  # DownloadedHeaderEvent,
    }

    def __init__(self):
        super().__init__()
        self.block_event_groups: dict[str, BlockEventGroup] = {}

    async def insert(self, message) -> None:
        """ """
        try:
            event = self.make_event(message)
            if not hasattr(event, "block_hash"):
                logger.error(
                    "Block event has no block_hash, skipping!", event=event
                )
                return

            # Find the group or create it before adding the event to it
            block_hash = event.block_hash
            if block_hash not in self.block_event_groups:
                self.block_event_groups[block_hash] = BlockEventGroup(
                    block_hash=block_hash
                )
            group = self.block_event_groups[block_hash]
            group.add_event(event)
        except EventError as e:
            logger.exception("Add event raised exception")

    async def send_block_samples(self, api):
        ready_groups = {}
        for k, group in self.block_event_groups.items():
            if group.is_complete() and group.age_seconds > settings().min_age:
                ready_groups[k] = group

        for k, group in ready_groups.items():
            if group.is_sane():
                sample = group.sample()
                resp = await api.post("/submit/blocksample", sample)
                rich.print(
                    f"[bold green]Sample {group.block_hash[:8]} published. Id: {resp.get('id')}.[/]"
                )
                del self.block_event_groups[k]
