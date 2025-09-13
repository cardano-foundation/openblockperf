"""
logprocessor

The eventprocessor receives the cardano-node log events and processes them.

It is implemented in a single class that takes a NodeLogReader from which
it will start reading the raw log lines. Every line is then parsed and converted
into one of the LogEvents.

"""

import asyncio

import rich

from blockperf.core.config import settings
from blockperf.core.eventcollector import BlockEventGroup, EventCollector
from blockperf.core.events import (
    AddedToCurrentChainEvent,
    BaseLogEvent,
    CompletedBlockFetchEvent,
    DownloadedHeaderEvent,
    SendFetchRequestEvent,
    SwitchedToAForkEvent,
    parse_log_message,
)
from blockperf.core.logreader import NodeLogReader


class EventProcessor:
    def __init__(self, log_reader: NodeLogReader):
        self.running = False
        self.log_reader = log_reader
        self.event_collector = EventCollector()

    async def start(self):
        print("Started Event Processor")
        print(f"{settings().network}")
        print(f"{settings().network_config.magic}")
        print(f"{settings().network_config.starttime}")
        self.running = True
        while self.running:
            await self.process_log_messages()
            await asyncio.sleep(0.1)

    async def stop(self):
        self.running = False

    async def process_log_messages(self):
        """Creates a task group and starts the two tasks to collect the events
        and to process them.

        """
        collection_task = asyncio.create_task(self.collect_events())
        inspection_task = asyncio.create_task(self.inspect_groups())
        await asyncio.gather(collection_task, inspection_task)

    async def collect_events(self):
        """Collects events from message of the logreader."""
        async with self.log_reader as log_reader:
            print("Start processing logs ...")
            async for message in log_reader.read_messages():
                event = parse_log_message(message)
                if not event or type(event) is BaseLogEvent:
                    continue
                self.insert_event(event)

    async def inspect_groups(self):
        """Inspects all groups for ones that are ready to get processed.."""
        while True:
            await asyncio.sleep(settings().check_interval)

            # Inspect all collected groups
            ready_groups = []
            for group in self.event_collector.get_all_groups():
                if group.is_complete() and group.age() > settings().min_age:
                    ready_groups.append(group)
            print(f"no. of ready groups {len(ready_groups)}")
            for group in ready_groups:
                await self.process_group(group)

    def insert_event(self, event):
        """Inserts given event into the event collector"""
        # group is either the group the event was added to or None if it could
        # not get added.
        # breakpoint()
        group = self.event_collector.add_event(event)
        # Print that a new block (group) was found (created)
        if group and group.event_count() == 1:
            rich.print(
                f"[bold magenta]New group for {group.block_hash[:8]} [/bold magenta]"
            )

        if isinstance(event, DownloadedHeaderEvent):
            rich.print(
                f"Header for {event.block_hash[:8]} from {event.peer_ip}"
            )
        elif isinstance(event, SendFetchRequestEvent):
            rich.print(f"Sending fetch request of {event.block_hash[:8]}")
        elif isinstance(event, CompletedBlockFetchEvent):
            rich.print(
                f"Downloaded {event.block_hash[:8]} from {event.peer_ip}"
            )
        elif isinstance(event, AddedToCurrentChainEvent):
            rich.print(f"Added {event.block_hash[:8]} to chain")
            if not group:
                # That should not happen.
                raise RuntimeError(f"No group return for {event}")
            print(f"Calculate blockperf payload for {group.block_hash[:8]}")
        elif isinstance(event, SwitchedToAForkEvent):
            rich.print(f"Switched to fork {event.block_hash[:8]} to chain")
        else:
            event.print_debug()

    async def process_group(self, group: BlockEventGroup):
        print(f"Process group {group.block_hash}")
        await asyncio.sleep(3)
        sample = group.sample()
        rich.print(sample)
        self.event_collector.remove_group(group)
