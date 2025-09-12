"""
logprocessor

The eventprocessor receives the cardano-node log events and processes them.

It is implemented in a single class that takes a NodeLogReader from which
it will start reading the raw log lines. Every line is then parsed and converted
into one of the LogEvents.

"""

import asyncio

import rich

from blockperf.core.eventcollector import EventCollector, EventGroup
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
        self.collector = EventCollector()

    async def start(self):
        print("Started Event Processor")
        self.running = True
        while self.running:
            await self.process_log_messages()
            await asyncio.sleep(0.1)

    async def stop(self):
        self.running = False

    async def process_log_messages(self):
        """Uses the logreader to process the logs."""
        async with self.log_reader as log_reader:
            print("Start processing logs ...")
            async for message in log_reader.read_messages():
                event = parse_log_message(message)
                if not event or type(event) is BaseLogEvent:
                    continue
                self.handle_event(event)
        # await asyncio.sleep(1)

    def handle_event(self, event):
        # group is either the group the event was added to or None if it could
        # not get added.
        group = self.collector.add_event(event)
        if group and group.event_count() == 1:
            rich.print(
                f"[bold magenta]New block {group.block_hash[:8]} [/bold magenta]"
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
            self.handle_added_to_chain(group)
        elif isinstance(event, SwitchedToAForkEvent):
            rich.print(f"Switched to fork {event.block_hash[:8]} to chain")
        else:
            event.print_debug()

    def handle_added_to_chain(self, group: EventGroup):
        # process the group by calculating the blockperf values
        print(f"Calculate blockperf payload for {group.block_hash[:8]}")
