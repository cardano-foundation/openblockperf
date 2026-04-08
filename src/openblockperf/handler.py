from datetime import datetime
from functools import singledispatchmethod

from pydantic import ValidationError

from openblockperf.apiclient import BlockperfApiClient
from openblockperf.blocksamplegroup import BlockSampleGroup
from openblockperf.config import AppSettings
from openblockperf.errors import EventError, InvalidEventDataError, UnknowEventNameSpaceError
from openblockperf.logging import logger
from openblockperf.models.events import (
    AddedToCurrentChainEvent,
    BlockSampleEvent,
    CompletedBlockFetchEvent,
    DemotedPeerEvent,
    DownloadedHeaderEvent,
    InboundGovernorCountersEvent,
    PeerEvent,
    PromotedPeerEvent,
    SendFetchRequestEvent,
    StatusChangedEvent,
    SwitchedToAForkEvent,
)
from openblockperf.models.peer import Peer, PeerDirection, PeerState

# ---------------------------------------------------------------------------
# How dispatch works in this class
# ---------------------------------------------------------------------------
# There are TWO levels of singledispatch:
#
#   Level 1 — dispatch_event(event)
#       Routes by top-level event type:
#           BlockSampleEvent             → _on_block_sample_event
#           PeerEvent                    → _on_peer_event          (also advances peer state)
#           InboundGovernorCountersEvent → _on_inbound_governor_counters
#
#   Level 2 — dispatch_peer_event(peer, event)
#       Called from _on_peer_event after peer state is updated.
#       Routes by specific PeerEvent subtype:
#           StatusChangedEvent  → _on_peer_status_changed
#           PromotedPeerEvent   → _on_peer_promoted
#           DemotedPeerEvent    → _on_peer_demoted
#
# To add a new event type:
#   1. Add its namespace → model mapping to REGISTERED_NAMESPACES
#   2. Register a handler with @dispatch_event.register or @dispatch_peer_event.register
# ---------------------------------------------------------------------------


class EventHandler:
    """Routes incoming log messages to typed async event handlers via singledispatch."""

    # Maps cardano-node log namespace strings to their Pydantic event models.
    # _make_event_from_message() uses this to parse raw dicts into typed events.
    REGISTERED_NAMESPACES: dict[str, type[BlockSampleEvent | PeerEvent]] = {
        "BlockFetch.Client.CompletedBlockFetch": CompletedBlockFetchEvent,
        "BlockFetch.Client.SendFetchRequest": SendFetchRequestEvent,
        "ChainDB.AddBlockEvent.AddedToCurrentChain": AddedToCurrentChainEvent,
        "ChainDB.AddBlockEvent.SwitchedToAFork": SwitchedToAForkEvent,
        "ChainSync.Client.DownloadedHeader": DownloadedHeaderEvent,
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
        "Net.PeerSelection.Actions.StatusChanged": StatusChangedEvent,
    }

    block_sample_groups: dict[str, BlockSampleGroup]
    peers: dict[tuple, Peer]
    api: BlockperfApiClient

    def __init__(
        self,
        block_sample_groups: dict[str, BlockSampleGroup],
        peers: dict[tuple, Peer],
        api: BlockperfApiClient,
        settings: AppSettings,
    ):
        super().__init__()
        self.block_sample_groups = block_sample_groups
        self.peers = peers
        self.api = api
        self.settings = settings

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def handle_message(self, raw_message: dict):
        """Parse a raw log dict and dispatch it to the appropriate handler."""
        event = self._make_event_from_message(raw_message)
        return await self.dispatch_event(event)

    # ------------------------------------------------------------------
    # Internal: parsing
    # ------------------------------------------------------------------

    def _make_event_from_message(self, message: dict) -> BlockSampleEvent | PeerEvent:
        """Validate a raw log message dict into a typed Pydantic event model."""
        ns = message.get("ns")
        if ns not in self.REGISTERED_NAMESPACES:
            raise UnknowEventNameSpaceError()
        event_model_class = self.REGISTERED_NAMESPACES[ns]
        try:
            return event_model_class.model_validate(message)
        except ValidationError as e:
            raise InvalidEventDataError(ns, event_model_class, message) from e

    # ------------------------------------------------------------------
    # Level 1 dispatch — routes by top-level event type
    # ------------------------------------------------------------------

    @singledispatchmethod
    async def dispatch_event(self, event) -> int | None:
        """Fallback: raises if an unregistered event type reaches the dispatcher."""
        raise EventError(f"Unhandled event type: {type(event).__name__}")

    @dispatch_event.register
    async def _on_block_sample_event(self, event: BlockSampleEvent):
        """Add a block-related event to the BlockSampleGroup for its block_hash."""
        logger.debug("BlockEvent", event=event)
        if not hasattr(event, "block_hash"):
            raise EventError("Block event has no block_hash.")
        block_hash = event.block_hash
        if block_hash not in self.block_sample_groups:
            self.block_sample_groups[block_hash] = BlockSampleGroup(
                block_hash=block_hash,
                settings=self.settings,
            )
        self.block_sample_groups[block_hash].add_event(event)

    @dispatch_event.register
    async def _on_peer_event(self, event: PeerEvent):
        """Update peer state, then forward to the Level 2 peer-event dispatcher."""

        if event.key not in self.peers:
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
        logger.debug(f"Dispatching peer event, runtime type: {type(event).__name__}, ns: {event.ns}", event=event)
        # Make sure the event is the first argument for singledispatch to be able to
        # properly distinguish between the types.
        await self.dispatch_peer_event(event, peer)  # → Level 2

    @dispatch_event.register
    async def _on_inbound_governor_counters(self, event: InboundGovernorCountersEvent):
        logger.debug("InboundGovernorCountersEvent", event=event)

    # ------------------------------------------------------------------
    # Level 2 dispatch — routes PeerEvent subtypes after state update
    # ------------------------------------------------------------------

    @singledispatchmethod
    async def dispatch_peer_event(self, event: PeerEvent, peer: Peer):
        """Fallback: logs a warning for unregistered PeerEvent subtypes."""
        logger.warning(f"No specific handler for peer event type {type(event).__name__}")

    @dispatch_peer_event.register
    async def _on_peer_status_changed(self, event: StatusChangedEvent, peer: Peer):
        logger.debug("Peer status changed", event=event, peer=peer)
        await self.api.submit_peer_event(peer, event)

    @dispatch_peer_event.register
    async def _on_peer_promoted(self, event: PromotedPeerEvent, peer: Peer):
        logger.debug("Peer promoted", event=event, peer=peer)
        assert isinstance(event, PromotedPeerEvent), "Event must be PromotedPeerEvent"
        await self.api.submit_peer_event(peer, event)

    @dispatch_peer_event.register
    async def _on_peer_demoted(self, event: DemotedPeerEvent, peer: Peer):
        logger.debug("Peer demoted", event=event, peer=peer)
        assert isinstance(event, DemotedPeerEvent), "Event must be DemotedPeerEvent"
        await self.api.submit_peer_event(peer, event)
