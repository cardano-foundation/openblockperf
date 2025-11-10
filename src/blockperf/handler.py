from dataclasses import dataclass
from datetime import datetime
from functools import singledispatchmethod

import rich
from loguru import logger
from pydantic import ValidationError

from blockperf.apiclient import BlockperfApiClient
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
    api: BlockperfApiClient

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
        api: BlockperfApiClient,
    ):
        super().__init__()
        self.block_sample_groups = block_sample_groups
        self.peers = peers
        self.api = api

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
            raise InvalidEventDataError(ns, event_model_class, message) from e

    async def handle_message(self, raw_message: dict):
        """Handles every event by calling the single dispatch method _handle_event.

        The single dispatch method inspects the type of the event and depending
        on that type it calles on of the registerd (typed) handlers.
        See https://peps.python.org/pep-0443/ for more details.
        """
        event = self._make_event_from_message(raw_message)
        result = await self.dispatch_event(event)
        return result

    @singledispatchmethod
    async def dispatch_event(self, event) -> int | None:
        """Calls general events like block samples, peers and others (InboundGovenor, etc)."""
        raise EventError(f"Unhandled event type: {type(event).__name__}")

    @singledispatchmethod
    async def dispatch_peer_event(
        self, peer: Peer, event: PeerEvent
    ) -> tuple[Peer, PeerEvent]:
        """Calls the PeerEvent specific handlers. Each handler returns a tuple
        providing the result and possibly some data to that result. For now
        these are just two dictionaries.
        """
        logger.warning(f"Not a PeerEvent {event}")
        return {}, {}

    # The single 'dispatch_*()' will call the hdl_*() based on their signature
    # There are handlers for, block samples, peer events and the inbound govenor
    @dispatch_event.register
    async def hdl_blocksample_event(self, event: BlockSampleEvent):
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

    @dispatch_event.register
    async def hdl_peer_event(self, event: PeerEvent):
        """Handles a PeerEvent.
        Looks up the peer and does some common peer things before handing
        it over to the peer_event_handler which will flesh out the details.
        """
        logger.debug("Handling PeerEvent", event=event)
        if event.key not in self.peers:
            # Creates a new peer
            self.peers[event.key] = Peer(
                ns=event.ns,
                remote_addr=event.remote_addr,
                remote_port=event.remote_port,
                local_addr=event.local_addr,
                local_port=event.local_port,
            )
        peer = self.peers[event.key]

        direction = PeerDirection(event.direction)
        if direction == PeerDirection.INBOUND:
            peer.state_inbound = PeerState(event.state)
        if direction == PeerDirection.OUTBOUND:
            peer.state_outbound = PeerState(event.state)

        peer.last_updated = datetime.now()
        # Call the PeerEvent specific dispatcher
        rich.print(f"{peer.ns=}", event)
        await self.dispatch_peer_event(peer, event)

    @dispatch_event.register
    async def hdl_inbound_governor(self, event: InboundGovernorCountersEvent):
        logger.info("Handling InboundGovernorCountersEvent", foo=event)

    """
    There are different handlers registered for the peer event. Each dealing
    with a different specific peer event.

    * Status changes
    * Different Promotion/Demotions from cold, warm, and hot
    * possible others soon

    All of the handlers receive the peer and original event as arguments.

    """

    @dispatch_peer_event.register
    async def hdl_peer_event__status_changed(
        self, peer: Peer, event: StatusChangedEvent
    ):
        await self.api.submit_peer_event(peer, event)

    async def hdl_peer_event__promoted_peer(
        self, peer: Peer, event: PromotedPeerEvent
    ):
        await self.api.submit_peer_event(peer, event)

    async def hdl_peer_event__demoted_peer(
        self, peer: Peer, event: DemotedPeerEvent
    ):
        await self.api.submit_peer_event(peer, event)
