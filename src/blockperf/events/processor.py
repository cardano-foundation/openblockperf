"""
logprocessor

The eventprocessor receives the cardano-node log events and processes them.

It is implemented in a single class that takes a NodeLogReader from which
it will start reading the raw log lines. Every line is then parsed and converted
into one of the LogEvents.

"""

import asyncio
from typing import Any

import httpx
import rich

from blockperf.config import settings
from blockperf.events.collector import BlockEventGroup, EventCollector
from blockperf.events.models import (
    AddedToCurrentChainEvent,
    BaseBlockEvent,
    CompletedBlockFetchEvent,
    DownloadedHeaderEvent,
    SendFetchRequestEvent,
    SwitchedToAForkEvent,
)
from blockperf.logreader import NodeLogReader

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
}


class EventProcessor:
    def __init__(self, log_reader: NodeLogReader):
        self.running = False
        self.log_reader = log_reader
        self.event_collector = EventCollector()

    def parse_log_message(self, log_message: dict[str, Any]) -> Any:
        """Parse a log message JSON into the appropriate event model.

        The EVENT_REGISTRY dictionary provides a mapping of event namespaces
        to pydantic models. The code below first retrieves the namespace from the
        incoming (base) event. It then tries to get that namespaces entry from the
        registry and returns and instance of the model configured or returns the
        base event created in the beginning.
        """

        base_event = BaseBlockEvent(**log_message)
        namespace = base_event.namespace

        if event_class := EVENT_REGISTRY.get(namespace):
            return event_class(**log_message)

        # No event class found for namespace
        return base_event

    async def start(self):
        """Starts the event processor."""
        self.running = True
        while self.running:
            await self.process_log_messages()
            print("Does this ever get called? WHy would i need that?")
            await asyncio.sleep(0.1)

    async def stop(self):
        """Stops the event processor."""
        self.running = False

    async def process_log_messages(self):
        """Creates a task group and starts the two tasks to collect the events
        and to process them.

        """
        collection_task = asyncio.create_task(self.collect_events())
        inspection_task = asyncio.create_task(self.inspect_groups())
        # Add cleanup task?
        await asyncio.gather(collection_task, inspection_task)

    async def collect_events(self):
        """Collects events from message of the logreader."""
        async with self.log_reader as log_reader:
            print("Start processing logs ...")
            async for message in log_reader.read_messages():
                event = self.parse_log_message(message)
                if not event or type(event) is BaseBlockEvent:
                    continue

                success = self.event_collector.add_event(event)
                if not success:
                    rich.print(f"[bold red]Failed to add event {event}[/]")

    async def inspect_groups(self):
        """Inspects all groups for ones that are ready to get processed.."""
        while True:
            await asyncio.sleep(settings().check_interval)

            # Inspect all collected groups
            ready_groups = []
            for group in self.event_collector.get_all_groups():
                if group.is_complete and group.age_seconds > settings().min_age:
                    ready_groups.append(group)

            for group in ready_groups:
                await self.process_group(group)

    async def process_group(self, group: BlockEventGroup):
        sample = group.sample()
        if group.is_sane():
            rich.print("[bold green]Sample seems fine[/]")
            rep = httpx.post("http://127.0.0.1:8080/api/v0/submit", json=sample)
            # breakpoint()
            rich.print(rep)
        else:
            rich.print("[bold red]Sample is insane[/]")
        rich.print(sample)
        self.event_collector.remove_group(group)
        rich.print(
            f"[bold blue] ... {group.block_hash[:8]} processed and deleted[/]"
        )
        print()
