"""
logprocessor

The eventprocessor receives the cardano-node log events and processes them.

It is implemented in a single class that takes a NodeLogReader from which
it will start reading the raw log lines. Every line is then parsed and converted
into one of the LogEvents.

"""

import asyncio

import httpx
import rich

from blockperf.core.config import settings
from blockperf.core.eventcollector import BlockEventGroup, EventCollector
from blockperf.core.events import BaseBlockEvent, parse_log_message
from blockperf.core.logreader import NodeLogReader


class EventProcessor:
    def __init__(self, log_reader: NodeLogReader):
        self.running = False
        self.log_reader = log_reader
        self.event_collector = EventCollector()

    async def start(self):
        print("Started Event Processor")
        self.running = True
        while self.running:
            await self.process_log_messages()
            print("Does this ever get called? WHy would i need that?")
            await asyncio.sleep(0.1)

    async def stop(self):
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
                event = parse_log_message(message)
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
