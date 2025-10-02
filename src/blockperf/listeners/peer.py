from functools import singledispatchmethod

from loguru import logger

from blockperf.errors import EventError
from blockperf.listeners.base import EventListener
from blockperf.models.event import (
    BaseEvent,
    DemotedToColdRemoteEvent,
    DemotedToWarmRemoteEvent,
    InboundGovernorCountersEvent,
    PromotedToHotRemoteEvent,
    PromotedToWarmRemoteEvent,
    StartedEvent,
    StatusChangedEvent,
)
from blockperf.models.peer import Peer, PeerState


class PeerListener(EventListener):
    registered_namespaces = {
        "Net.InboundGovernor.Local.DemotedToColdRemote": DemotedToColdRemoteEvent,
        "Net.InboundGovernor.Local.DemotedToWarmRemote": DemotedToWarmRemoteEvent,
        "Net.InboundGovernor.Local.PromotedToHotRemote": PromotedToHotRemoteEvent,
        "Net.InboundGovernor.Local.PromotedToWarmRemote": PromotedToWarmRemoteEvent,
        "Net.InboundGovernor.Local.InboundGovernorCounters": InboundGovernorCountersEvent,
        "Net.InboundGovernor.Remote.PromotedToHotRemote": PromotedToHotRemoteEvent,
        "Net.InboundGovernor.Remote.PromotedToWarmRemote": PromotedToWarmRemoteEvent,
        "Net.InboundGovernor.Remote.DemotedToColdRemote": DemotedToColdRemoteEvent,
        "Net.InboundGovernor.Remote.DemotedToWarmRemote": DemotedToWarmRemoteEvent,
        "Net.InboundGovernor.Remote.InboundGovernorCounters": InboundGovernorCountersEvent,
        # "Net.PeerSelection.Actions.ConnectionError": BaseEvent,
        "Net.PeerSelection.Actions.StatusChanged": StatusChangedEvent,
        "Net.PeerSelection.Selection.DemoteHotDone": BaseEvent,
        "Net.PeerSelection.Selection.DemoteHotFailed": BaseEvent,
        "Net.PeerSelection.Selection.DemoteHotPeers": BaseEvent,
        # "": StartedEvent,
    }

    peers: dict[tuple, Peer]

    def __init__(self):
        self.peers = {}

    async def insert(self, message) -> None:
        """Insert a new"""
        try:
            logger.debug("Insert Peer event to listener")
            event = self.make_event(message)
            if hasattr(event, "peer_addr_port"):
                addr, port = event.peer_addr_port()
                key = (addr, port)
                if key not in self.peers:
                    self.peers[key] = Peer(addr=addr, port=port)
                    logger.debug(f"{self.peers[key]} created")
                peer = self.peers[key]
                peer.state = event.state
                logger.debug(peer)
            # Handle type specifics through _handle_event
            self._handle_event(event)
        except EventError as e:
            logger.exception("Add event raised exception")

    @singledispatchmethod
    def _handle_event(self, event):
        """Default handler for unknown event types.

        Depending on the events type provided the singledispatchmethod
        will call the right one. the functions are never called directly
        thats why they are all named _
        """
        logger.error(f"Unhandled event type: {type(event).__name__}")

    @_handle_event.register
    def _(self, event: DemotedToColdRemoteEvent):
        logger.info(f"Handling {event.__class__.__name__}")

    @_handle_event.register
    def _(self, event: DemotedToWarmRemoteEvent):
        logger.info(f"Handling {event.__class__.__name__}")

    @_handle_event.register
    def _(self, event: PromotedToHotRemoteEvent):
        logger.info(f"Handling {event.__class__.__name__}")

    @_handle_event.register
    def _(self, event: PromotedToWarmRemoteEvent):
        logger.info(f"Handling {event.__class__.__name__}")

    @_handle_event.register
    def _(self, event: StatusChangedEvent):
        logger.info(f"Handling {event.__class__.__name__}")

    @_handle_event.register
    def _(self, event: InboundGovernorCountersEvent):
        logger.info(f"Handling {event}")

    def _get_key(self, event):
        # helper
        return (1, 2)

    def get_peer_statistics(self):
        peers = self.peers.values()
        cold = [p for p in peers if p.state == PeerState.COLD]
        warm = [p for p in peers if p.state == PeerState.WARM]
        hot = [p for p in peers if p.state == PeerState.HOT]
        cooling = [p for p in peers if p.state == PeerState.COOLING]
        unknown = [p for p in peers if p.state == PeerState.UNKNOWN]
        return {
            "cold": len(cold),
            "warm": len(warm),
            "hot": len(hot),
            "cooling": len(cooling),
            "unknown": len(unknown),
            "total": len(self.peers),
        }

    async def update_peers_from_connections(self, connections: list) -> None:
        """Takes a list of connections created from psutils net_connections().

        That is the library i use so this expects their named tuple of a
        connection.
        """
        connection_keys = []
        new_peers = 0
        for conn in connections:
            raddr = conn.raddr
            addr, port = raddr.ip, int(raddr.port)
            key = (addr, port)
            if key not in self.peers:
                new_peers += 1
                self.peers[key] = Peer(
                    addr=addr,
                    port=port,
                    state=PeerState.UNKNOWN,
                )
            connection_keys.append(key)  # store keys to know which are new
        logger.debug(
            f"Created {new_peers} peers from {len(connections)} connections"
        )
        for peer_key in self.peers:
            # find peers without a connection
            if peer_key not in connection_keys:
                self.peers[peer_key].state = PeerState.LOSTCONNECTION
                # logger.debug(f"Peer {self.peers[peer_key]} lost connection")
