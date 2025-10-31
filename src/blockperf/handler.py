from datetime import datetime
from functools import singledispatchmethod

import rich
from loguru import logger
from pydantic import ValidationError

from blockperf.blocksamplegroup import BlockSampleGroup
from blockperf.errors import (
    EventError,
    InvalidEventDataError,
    UnknowEventNameSpaceError,
)
from blockperf.models.events.base import BaseEvent
from blockperf.models.events.event import (
    AddedToCurrentChainEvent,
    BlockSampleEvent,
    CompletedBlockFetchEvent,
    DownloadedHeaderEvent,
    SendFetchRequestEvent,
    SwitchedToAForkEvent,
)
from blockperf.models.events.peer import (
    DemotedPeerEvent,
    InboundGovernorCountersEvent,
    PeerEvent,
    PromotedPeerEvent,
    StatusChangedEvent,
)
from blockperf.models.peer import Peer, PeerDirection, PeerState


class EventHandler:
    """
    The event handler handles the events.

    First use `make_event()` to create an event from the provided message.
    The namespace of the event will be created into the model that is configured
    in the registered_namespaces dict. Add new events by providing them in that
    dict with the corresponding pydantic model to parse it into.
    To then handle that event, register a new singledispatch function using
    that event type in its signature. The

    """

    block_sample_groups: dict[str, BlockSampleGroup]  # Groups of block samples
    peers: dict[tuple, Peer]  # The nodes peer list (actually a dictionary)

    registered_namespaces = {
        "BlockFetch.Client.CompletedBlockFetch": CompletedBlockFetchEvent,
        "BlockFetch.Client.SendFetchRequest": SendFetchRequestEvent,
        "ChainDB.AddBlockEvent.AddedToCurrentChain": AddedToCurrentChainEvent,
        "ChainDB.AddBlockEvent.SwitchedToAFork": SwitchedToAForkEvent,
        "ChainSync.Client.DownloadedHeader": DownloadedHeaderEvent,  # DownloadedHeaderEvent,
        "Net.InboundGovernor.Local.DemotedToColdRemote": DemotedPeerEvent,
        "Net.InboundGovernor.Local.DemotedToWarmRemote": DemotedPeerEvent,
        "Net.InboundGovernor.Local.PromotedToHotRemote": PromotedPeerEvent,
        "Net.InboundGovernor.Local.PromotedToWarmRemote": PromotedPeerEvent,
        "Net.InboundGovernor.Local.InboundGovernorCounters": InboundGovernorCountersEvent,
        "Net.InboundGovernor.Remote.PromotedToHotRemote": PromotedPeerEvent,
        "Net.InboundGovernor.Remote.PromotedToWarmRemote": PromotedPeerEvent,
        "Net.InboundGovernor.Remote.DemotedToColdRemote": DemotedPeerEvent,
        "Net.InboundGovernor.Remote.DemotedToWarmRemote": DemotedPeerEvent,
        "Net.InboundGovernor.Remote.InboundGovernorCounters": InboundGovernorCountersEvent,
        # "Net.PeerSelection.Actions.ConnectionError": BaseEvent,
        "Net.PeerSelection.Actions.StatusChanged": StatusChangedEvent,
        # "Net.PeerSelection.Selection.DemoteHotDone": BaseEvent,
        # "Net.PeerSelection.Selection.DemoteHotFailed": BaseEvent,
        # "Net.PeerSelection.Selection.DemoteHotPeers": BaseEvent,
        # "": StartedEvent,
    }

    def __init__(
        self,
        block_sample_groups: dict[str, BlockSampleGroup],
        peers: dict[tuple, Peer],
    ):
        super().__init__()
        self.block_sample_groups = block_sample_groups
        self.peers = peers

    def _make_event_from_message(
        self, message: dict
    ) -> BlockSampleEvent | PeerEvent:
        """Takes a raw message as received from the LogReader and create an event."""
        try:
            ns = message.get("ns")
            if ns not in self.registered_namespaces:
                raise UnknowEventNameSpaceError()
            logger.info(ns)
            event_model_class = self.registered_namespaces.get(ns)
            return event_model_class.model_validate(message)
        except ValidationError as e:
            breakpoint()
            raise InvalidEventDataError(ns, event_model_class, message) from e

    async def handle_message(self, raw_message: dict):
        """Handles every event by calling the single dispatch method _handle_event.

        The single dispatch method inspects the type of the event and depending
        on that type it calles on of the registerd (typed) handlers.
        See https://peps.python.org/pep-0443/ for more details.
        """
        event = self._make_event_from_message(raw_message)
        if isinstance(event, BlockSampleEvent):
            print("A Block Event")
        elif isinstance(event, PeerEvent):
            print("A Peer Event")
        elif isinstance(event, InboundGovernorCountersEvent):
            print("A Governor event")
        else:
            breakpoint()
            print("ge wixen")
        return

        result = await self._handle_event(event)
        return result

    @singledispatchmethod
    async def _handle_event(self, event) -> int | None:
        raise EventError(f"Unhandled event type: {type(event).__name__}")

    @_handle_event.register
    async def blocksample_event(self, event: BlockSampleEvent):
        """Handles any of the block sample events.

        Adds the event to the BlockSampleGroup for the events block_hash. Or
        creates a new group if no group if found for the given block_hash.
        """
        logger.debug("Handling BlockEvent", event=event)
        if not hasattr(event, "block_hash"):
            raise EventError("Block event has no block_hash.")
        # Find the group or create it before adding the event to it
        block_hash = event.block_hash
        if block_hash not in self.block_sample_groups:
            self.block_sample_groups[block_hash] = BlockSampleGroup(
                block_hash=block_hash
            )
        group = self.block_sample_groups[block_hash]
        group.add_event(event)

    @_handle_event.register
    async def peer_event(self, event: PeerEvent):
        """Handles a PeerEvent."""
        logger.debug("Handling PeerEvent", event=event)
        if event.key not in self.peers:
            # Creates a new peer
            _p = Peer(
                ns=event.ns,
                remote_addr=event.remote_addr,
                remote_port=event.remote_port,
                local_addr=event.local_addr,
                local_port=event.local_port,
            )
            # rich.print(
            #    f"New Peer {_p.remote_addr}:{_p.remote_port}: IN '{_p.state_inbound.value}' OUT '{_p.state_outbound.value}'"
            # )
            self.peers[event.key] = _p
        peer = self.peers[event.key]
        direction = PeerDirection(event.direction)
        if direction == PeerDirection.INBOUND:
            peer.state_inbound = PeerState(event.state)
        if direction == PeerDirection.OUTBOUND:
            peer.state_outbound = PeerState(event.state)

        peer.last_updated = datetime.now()

    @_handle_event.register
    async def _(self, event: InboundGovernorCountersEvent):
        logger.info("Handling InboundGovernorCountersEvent", foo=event)
