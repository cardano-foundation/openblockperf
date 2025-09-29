"""
logprocessor

The eventprocessor receives the cardano-node log events and processes them.

It is implemented in a single class that takes a NodeLogReader from which
it will start reading the raw log lines. Every line is then parsed and converted
into one of the LogEvents.

"""

import asyncio
from datetime import datetime
from socket import AF_INET, AF_INET6
from typing import Any

import httpx
import psutil
import rich

from blockperf.collectors import BlockEventGroup, EventCollector
from blockperf.config import settings
from blockperf.logging import logger
from blockperf.logreader import NodeLogReader
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

"""
Added some of the events that i think are of interest. See here for more:
https://github.com/input-output-hk/cardano-node-wiki/blob/main/docs/new-tracing/tracers_doc_generated.md
"""
EVENT_REGISTRY = {
    "BlockFetch.Client.CompletedBlockFetch": CompletedBlockFetchEvent,
    "BlockFetch.Client.SendFetchRequest": SendFetchRequestEvent,
    # "BlockFetch.Remote.Receive.ClientDone": ClientDoneEvent,
    # "BlockFetch.Remote.Send.Block": None,
    "ChainDB.AddBlockEvent.AddedToCurrentChain": AddedToCurrentChainEvent,
    # "ChainDB.AddBlockEvent.BlockInTheFuture": BlockInTheFutureEvent,
    "ChainDB.AddBlockEvent.SwitchedToAFork": SwitchedToAForkEvent,
    # "ChainDB.AddBlockEvent.TrySwitchToAFork": TrySwitchToAForkEvent,
    # "ChainDB.AddBlockEvent.TryAddToCurrentChain": TryAddToCurrentChainEvent,
    "ChainSync.Client.DownloadedHeader": DownloadedHeaderEvent,
    # "ChainSync.Client.RolledBack": RolledBackEvent,
    # "ChainSync.Remote.Send.RequestNext":
    # "NodeState.NodeAddBlock": NodeAddBlockEvent,
    "Net.InboundGovernor.Local.DemotedToColdRemote": DemotedToColdRemoteEvent,
    "Net.InboundGovernor.Local.DemotedToWarmRemote": DemotedToWarmRemoteEvent,
    "Net.InboundGovernor.Local.PromotedToHotRemote": PromotedToHotRemoteEvent,
    "Net.InboundGovernor.Local.PromotedToWarmRemote": PromotedToWarmRemoteEvent,
    "Net.InboundGovernor.Local.InboundGovernorCounters": InboundGovernorCountersEvent,
    "Net.InboundGovernor.Remote.PromotedToHotRemote": PromotedToHotRemoteEvent,
    "Net.InboundGovernor.Remote.PromotedToWarmRemote": PromotedToWarmRemoteEvent,
    "Net.InboundGovernor.Remote.DemotedToColdRemote": DemotedToColdRemoteEvent,
    "Net.InboundGovernor.Remote.DemotedToWarmRemote": DemotedToWarmRemoteEvent,
    "Net.InboundGovernor.Remote.InboundGovernorCounters": InboundGovernorCountersEvent,
    # "Net.PeerSelection.Actions.ConnectionError": BaseBlockEvent,
    "Net.PeerSelection.Actions.StatusChanged": StatusChangedEvent,
    "Net.PeerSelection.Selection.DemoteHotDone": BaseBlockEvent,
    "Net.PeerSelection.Selection.DemoteHotFailed": BaseBlockEvent,
    "Net.PeerSelection.Selection.DemoteHotPeers": BaseBlockEvent,
    "Net.Server.Local.Started": StartedEvent,
}


def parse_log_message(log_message: dict[str, Any]) -> Any:
    """Parse a log message JSON into the appropriate event model.

    The EVENT_REGISTRY dictionary provides a mapping of event namespaces
    to pydantic models. The code below first retrieves the namespace from the
    incoming (base) event. It then tries to get that namespaces entry from the
    registry and returns and instance of the model configured or returns the
    base event created in the beginning.
    """

    if event_class := EVENT_REGISTRY.get(log_message.get("ns")):
        return event_class(**log_message)

    # No event class found for namespace
    return BaseBlockEvent(**log_message)


class EventProcessor:
    def __init__(self, log_reader: NodeLogReader):
        self.running = False
        self.log_reader = log_reader
        self.collector = EventCollector()
        # self.lock = asyncio.Lock() # remove?

    async def start(self):
        """Starts the event processor.

        Enters a forever loop in which it will create tasks and await their
        finish.
        """
        logger.debug("Event processor started")
        self.running = True
        while self.running:
            # Creates a bunch of tasks
            # Continiously processes the incoming message events
            _events = asyncio.create_task(self.process_events())
            # Update peers from live os network connections
            _peers = asyncio.create_task(self.update_peers())
            # Checks for and sends blocksamples if available
            _samples = asyncio.create_task(self.send_blocks())
            # Print peer state output to screen
            _state = asyncio.create_task(self.print_peer_state())
            await asyncio.gather(_events, _peers, _state)

    async def stop(self):
        """Stops the event processor."""
        self.running = False

    async def update_peers(self) -> list:
        """Update the peers list.

        Compares the list of peers with current active connections on the
        system. The idea being that especially on startup, there might already
        be alot of peers in the node, that we will never get notified about.
        This adds peers to that list with a state of unknown.

        Later on we might search for these peers in the logs to get their
        current state in the node. Since i dont see us being able to ask
        the node directly anytime soon.
        """
        while True:
            connections = []
            for conn in psutil.net_connections():
                if conn.status != "ESTABLISHED":
                    continue
                if conn.laddr.port != 3001:
                    continue
                addr, port = conn.raddr
                connections.append(conn)
            self.collector.update_peers_from_connections(connections)
            await asyncio.sleep(30)  # add peers every 5 Minutes

    async def process_events(self):
        """Continiously processes the events coming from the log reader.

        First opens the context for the logreader which calls connect() on
        it. Then enters a loop to iterate over all messages of the logreader
        forever. The read_messages() funcion is meant to be a generator which
        will continiously yield new log messages. See NodeLogReader base
        class which provides the abstract interface.
        """

        async with self.log_reader as log_reader:
            async for message in log_reader.read_messages():
                event = parse_log_message(message)
                # Skip events that failed to get parsed or do not have a
                # dedicated model class.
                if not event or type(event) is BaseBlockEvent:
                    continue

                self.collector.add_event(event)

        rich.print("[bold red]task process events ended ...")

    async def send_blocks(self):
        """Inspects all host collectors if any of them has a block sample ready to be processed"""
        while True:
            await asyncio.sleep(settings().check_interval)
            # Inspect all collected groups
            ready_groups = []
            for group in self.collector.get_all_groups():
                if group.is_complete and group.age_seconds > settings().min_age:
                    ready_groups.append(group)

            for group in ready_groups:
                await self.process_group(group)

    async def print_peer_state(self):
        while True:
            await asyncio.sleep(20)
            rich.print(self.collector.get_peer_statistics())

    async def process_group(self, group: BlockEventGroup):
        sample = group.sample()
        sample["host"] = "dummy"
        if group.is_sane():
            rich.print("[bold green]Sample seems fine[/]")
            rep = httpx.post(
                "http://127.0.0.1:8080/api/v0/submit/blocksample", json=sample
            )
            rich.print(rep)
        else:
            rich.print("[bold red]Sample is insane[/]")
        # rich.print(sample)
        rich.print(
            f"[bold blue] ... {group.block_hash[:8]} processed and deleted[/]"
        )
        print()
