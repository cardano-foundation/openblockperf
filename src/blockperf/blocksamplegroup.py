import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import singledispatchmethod

import rich
from loguru import logger

from blockperf import __version__
from blockperf.config import settings
from blockperf.errors import EventError
from blockperf.models.events.event import (
    AddedToCurrentChainEvent,
    BaseEvent,
    CompletedBlockFetchEvent,
    DownloadedHeaderEvent,
    SendFetchRequestEvent,
    SwitchedToAForkEvent,
)
from blockperf.models.samples import BlockSample


@dataclass
class BlockSampleGroup:
    """A group of log events for a given block hash.

    It will be created the first time a block hash is seen. It is meant
    to provide an interface to the sample and the individual values that
    are created for it. As the events come in through add_event they
    are stored and depending on their type update the values of this
    group, see below.

    """

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

    events: list[BaseEvent] = field(default_factory=list)  # list of events
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    def add_event(self, event: BaseEvent):
        """Adds an event to this group.

        Depending on the event type it will fill in missing values that
        only some of events provide. Once all needed events for this groups
        block have been recorded a block sample can be created.
        """
        self.events.append(event)
        self.last_updated = time.time()
        self._handle_event(event)

    @singledispatchmethod
    def _handle_event(self, event):
        """Default handler for unknown event types.

        Depending on the events type provided the singledispatchmethod
        will call the right one. the functions are never called directly
        thats why they are all named _
        """
        logger.error(f"Unhandled event type: {type(event).__name__}")

    @_handle_event.register
    def _(self, event: DownloadedHeaderEvent):
        """Handles DownloadedHeaderEvent,

        Stores the first header downloaded for this group/block_hash.
        If there already is a header stored and a new event comes in
        with a newer time, it will overwrite the existing stored event.
        """

        # logger.debug(
        #    f"Header\t{event.block_hash[:8]} from {event.remote_addr}:{event.remote_port}"
        # )

        # If we dont already know any header assume its the the first
        if self.block_header:
            if event.at < self.block_header.at:
                logger.warning(
                    "New first Header received",
                    old_header=self.block_header,
                    new_header=event,
                )
                self.block_header = event
        else:
            assert not self.block_header, "Header already set"
            self.block_header = event

        # these should all be the same for all header events, no?
        if not self.slot:
            self.slot = event.slot
        if not self.slot_time:
            self.slot_time = datetime.fromtimestamp(
                settings().network_config.starttime + self.slot, tz=UTC
            )
        if not self.block_number:
            self.block_number = event.block_number

    @_handle_event.register
    def _(self, event: SendFetchRequestEvent):
        """Handles SendFetchRequestEvent.

        Currently does nothing. Maybe even remove? The event itself
        is already added to the events list in add_event(). And there
        is no special logic needed for the SendFetchRequestEvent as of now.
        """
        # logger.debug(
        #    f"Requested\t{event.block_hash[:8]} from {event.remote_addr}"
        # )
        pass

    @_handle_event.register
    def _(self, event: CompletedBlockFetchEvent):
        """Handles CompletedBlockFetchEvent.

        Stores the CompletedBlockFetchEvent if not already known. What
        should happen if block is downloaded twice? Can that even happen?

        """
        # logger.debug(
        #    f"Downloaded\t{event.block_hash[:8]} from {event.remote_addr}"
        # )
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

    @_handle_event.register
    def _(self, event: AddedToCurrentChainEvent):
        """Handles AddedToCurrentChainEvent.

        No special logic yet.
        """
        # logger.debug(f"Added\t\t{event.block_hash[:8]} to chain")
        pass

    @_handle_event.register
    def _(self, event: SwitchedToAForkEvent):
        """Handles SwitchedToAForkEvent.

        No special logic yet.
        """
        # logger.debug(f"Switched \t{event.block_hash[:8]} to fork")
        pass

    @property
    def event_count(self) -> int:
        """Return the number of events in this group."""
        return len(self.events)

    @property
    def age_seconds(self) -> int:
        """Age of this group in seconds rounding to full seconds (up/down)"""
        return round(time.time() - self.created_at)

    @property
    def block_adopted(self) -> AddedToCurrentChainEvent | SwitchedToAForkEvent | None:  # fmt: skip
        """Returns the event that adopted this block or None of not yet adopted."""
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
        # TODO: This should not live here. Either in the BlockSample model validation
        # Or in the block listener....
        return BlockSample(
            host = "dummy",
            block_hash = self.block_hash,
            block_number = self.block_number,
            block_size = self.block_size,
            block_g = self.block_g,
            slot = self.slot,
            slot_time = self.slot_time.isoformat(),
            header_remote_addr = self.block_header.remote_addr,
            header_remote_port = self.block_header.remote_port,
            header_delta = int(self.header_delta.total_seconds() * 1000),
            block_remote_addr = self.block_completed.remote_addr,
            block_remote_port = self.block_completed.remote_port,
            block_request_delta = int(self.block_request_delta.total_seconds() * 1000),
            block_response_delta = int(self.block_response_delta.total_seconds() * 1000),
            block_adopt_delta = int(self.block_adopt_delta.total_seconds() * 1000),
            local_addr = settings().local_addr,
            local_port = int(settings().local_port),
            magic = settings().network_config.magic,
            client_version = __version__,
        )

    # fmt: on

    def _get_fetch_for_completed(self, event: CompletedBlockFetchEvent):
        """Searches the SendFetchRequest for the given completed block fetch event"""
        for e in self.events:
            if (
                isinstance(e, SendFetchRequestEvent)
                and e.remote_addr == event.remote_addr
                and e.remote_port == event.remote_port
            ):
                return e
        return None

    def __str__(self):
        return f"BlockSampleGroup(block_hash={self.block_hash if self.block_hash else None}, events={len(self.events)})"
