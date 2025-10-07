from datetime import datetime
from functools import singledispatchmethod

import rich
from loguru import logger

from blockperf.blocksamplegroup import BlockSampleGroup
from blockperf.errors import EventError
from blockperf.models.events.base import BaseEvent
from blockperf.models.events.event import (
    AddedToCurrentChainEvent,
    CompletedBlockFetchEvent,
    DownloadedHeaderEvent,
    InboundGovernorCountersEvent,
    SendFetchRequestEvent,
    SwitchedToAForkEvent,
)
from blockperf.models.events.peer import PeerEvent
from blockperf.models.peer import Peer, PeerDirection, PeerState


class EventHandler:
    """
    The event handler handles the events.

    Provides a function to create an event from a log message `make_event()`
    """

    block_sample_groups: dict[str, BlockSampleGroup]  # Groups of block samples
    peers: dict[tuple, Peer]  # The nodes peer list (actually a dictionary)

    registered_namespaces = {
        "BlockFetch.Client.CompletedBlockFetch": CompletedBlockFetchEvent,
        "BlockFetch.Client.SendFetchRequest": SendFetchRequestEvent,
        "ChainDB.AddBlockEvent.AddedToCurrentChain": AddedToCurrentChainEvent,
        "ChainDB.AddBlockEvent.SwitchedToAFork": SwitchedToAForkEvent,
        "ChainSync.Client.DownloadedHeader": DownloadedHeaderEvent,  # DownloadedHeaderEvent,
        "Net.InboundGovernor.Local.DemotedToColdRemote": PeerEvent,
        "Net.InboundGovernor.Local.DemotedToWarmRemote": PeerEvent,
        "Net.InboundGovernor.Local.PromotedToHotRemote": PeerEvent,
        "Net.InboundGovernor.Local.PromotedToWarmRemote": PeerEvent,
        "Net.InboundGovernor.Local.InboundGovernorCounters": InboundGovernorCountersEvent,
        "Net.InboundGovernor.Remote.PromotedToHotRemote": PeerEvent,
        "Net.InboundGovernor.Remote.PromotedToWarmRemote": PeerEvent,
        "Net.InboundGovernor.Remote.DemotedToColdRemote": PeerEvent,
        "Net.InboundGovernor.Remote.DemotedToWarmRemote": PeerEvent,
        "Net.InboundGovernor.Remote.InboundGovernorCounters": InboundGovernorCountersEvent,
        # "Net.PeerSelection.Actions.ConnectionError": BaseEvent,
        "Net.PeerSelection.Actions.StatusChanged": PeerEvent,
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

    def make_event(self, message) -> BaseEvent | None:
        ns = message.get("ns")
        if (
            not self.registered_namespaces
            or ns not in self.registered_namespaces
        ):
            raise EventError(f"Inserted namespace '{ns}' not found in registry")

        event_model_class = self.registered_namespaces.get(ns)
        return event_model_class(**message)

    async def handle_event(self, event: BaseEvent):
        """Handles every event by calling the single dispatch method _handle_event.

        The single dispatch method inspects the type of the event and depending
        on that type it calles on of the registerd (typed) handlers.
        See https://peps.python.org/pep-0443/ for more details.
        """
        self._handle_event(event)

    @singledispatchmethod
    async def _handle_event(self, event):
        raise EventError(f"Unhandled event type: {type(event).__name__}")

    @_handle_event.register
    def _(
        self,
        event: DownloadedHeaderEvent
        | SendFetchRequestEvent
        | CompletedBlockFetchEvent
        | AddedToCurrentChainEvent
        | SwitchedToAForkEvent,
    ):
        """Handles any of the block sample events.

        Adds the event to the BlockSampleGroup for the events block_hash. Or
        creates a new group if no group if found for the given block_hash.
        """
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
    def _(self, event: PeerEvent):
        """Handles a PeerEvent."""
        # logger.debug("Handling PeerEvent", event=event)
        if event.key not in self.peers:
            # Creates a new peer
            _p = Peer(
                ns=event.ns,
                remote_addr=event.remote_addr,
                remote_port=event.remote_port,
                local_addr=event.local_addr,
                local_port=event.local_port,
            )
            rich.print(
                f"New Peer {_p.remote_addr}:{_p.remote_port}: IN '{_p.state_inbound.value}' OUT '{_p.state_outbound.value}'"
            )
            self.peers[event.key] = _p
        peer = self.peers[event.key]
        direction = PeerDirection(event.direction)
        if direction == PeerDirection.INBOUND:
            peer.state_inbound = PeerState(event.state)
        if direction == PeerDirection.OUTBOUND:
            peer.state_outbound = PeerState(event.state)

        peer.last_updated = datetime.now()

    @_handle_event.register
    def _(self, event: InboundGovernorCountersEvent):
        logger.info("Handling InboundGovernorCountersEvent", event=event)
