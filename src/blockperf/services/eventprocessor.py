"""
logprocessor

The eventprocessor receives the cardano-node log events and processes them.

It is implemented in a single class that takes a NodeLogReader from which
it will start reading the raw log lines. Every line is then parsed and converted
into one of the LogEvents.

"""

import asyncio

from blockperf.nodelogs.logreader import NodeLogReader


class EventProcessor:
    def __init__(self, log_reader: NodeLogReader):
        self.running = False
        self.log_reader = log_reader

    async def start(self):
        print("Started Event Processor")
        self.running = True
        while self.running:
            await self.process_logs()
            await asyncio.sleep(0.1)

    async def process_logs(self):
        """Uses the logreader to process the logs."""
        async with self.log_reader as source:
            print(f"process logs from {source.syslog_identifier} ")
            print(" ### ")
            print()
            async for raw_event in source.read_events():
                print()
                print(
                    f"Now do something with this event {raw_event.get('at') + ' ' + raw_event.get('ns')}"
                )

        # await asyncio.sleep(1)

    async def stop(self):
        self.running = False
