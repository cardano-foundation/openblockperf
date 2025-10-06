from datetime import datetime
from functools import singledispatchmethod

import rich
from loguru import logger

from blockperf.errors import EventError
from blockperf.listeners.base import EventListener
from blockperf.models.events.event import InboundGovernorCountersEvent
from blockperf.models.events.peer import PeerEvent
from blockperf.models.peer import Peer, PeerDirection, PeerState


class PeerListener(EventListener):
    registered_namespaces = {
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

    peers: dict[tuple, Peer]

    def __init__(self):
        self.peers = {}

    async def insert(self, message) -> None:
        """Insert a new"""
        try:
            rich.print("New Insert")
            rich.print(message)
            event = self.make_event(message)
            # if hasattr(event, "peer_addr_port"):
            #    addr, port = event.peer_addr_port()
            #    key = (addr, port)
            #    if key not in self.peers:
            #        self.peers[key] = Peer(addr=addr, port=port)
            #        logger.debug(f"{self.peers[key]} created")
            #    peer = self.peers[key]
            #    peer.state = event.state
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
    def _(self, event: PeerEvent):
        """Handles a peer event.

        Either:
        * Creates a new Peer (if not alerady there)
        * Updates the existing Peer (if not just created)

        """
        logger.info("Handling PeerEvent")
        if event.key not in self.peers:
            # Creates a new peer
            self.peers[event.key] = Peer(
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
        rich.print(event)
        rich.print(peer)

    @_handle_event.register
    def _(self, event: InboundGovernorCountersEvent):
        logger.info(f"Handling {event}")

    def get_peer_statistics(self):
        raise Exception("Not Working atm")
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
                )
            connection_keys.append(key)  # store keys to know which are new

        # Find the keys (peers) that
        keys_to_remove = [pk for pk in self.peers if pk not in connection_keys]
        for peer_key in keys_to_remove:
            logger.debug(
                f"Removed {self.peers[peer_key]} from peers because it has no connection"
            )
            del self.peers[peer_key]
