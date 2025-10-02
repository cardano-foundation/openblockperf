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

from blockperf.config import settings
from blockperf.listeners.base import EventListener
from blockperf.logging import logger
from blockperf.logreader import NodeLogReader, create_log_reader
from blockperf.models.event import (
    AddedToCurrentChainEvent,
    BaseEvent,
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

"""
Added some of the events that i think are of interest. See here for more:
https://github.com/input-output-hk/cardano-node-wiki/blob/main/docs/new-tracing/tracers_doc_generated.md
"""


class EventProcessor:
    listeners: list  # List of its registered listeners
    log_reader: NodeLogReader  # the log reader this processor is using

    def __init__(
        self,
        log_reader: NodeLogReader | None = None,
    ):
        self.log_reader = log_reader or create_log_reader(
            "journalctl", "cardano-tracer"
        )
        # The collector is now a listener, a listener holds the logic
        # what to do with a bunch of events
        # self.collector = collector or EventCollector()
        # The listeners receive the messages they are interested in
        self.listeners = []
        # self.lock = asyncio.Lock() # remove?

    def add_listener(self, listener: EventListener):
        self.listeners.append(listener)

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
                # event = parse_log_message(message)
                ns = message.get("ns")
                # if ns == "Net.Server.Local.Started":
                #    # Do some special thing on a restart?
                #    continue
                for listener in self.listeners:
                    if ns in listener.registered_namespaces:
                        await listener.insert(message)
                # self.collector.add_event(event)
