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
            event = self.make_event(message)
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
        logger.info(f"Handling InboundGovernorCountersEvent", event=event)

    def get_peer_statistics(self):
        peers = self.peers.values()

        in_cold = [p for p in peers if p.state_inbound == PeerState.COLD]
        out_cold = [p for p in peers if p.state_outbound == PeerState.COLD]
        in_warm = [p for p in peers if p.state_inbound == PeerState.WARM]
        out_warm = [p for p in peers if p.state_outbound == PeerState.WARM]
        in_hot = [p for p in peers if p.state_inbound == PeerState.HOT]
        out_hot = [p for p in peers if p.state_outbound == PeerState.HOT]
        in_cooling = [p for p in peers if p.state_inbound == PeerState.COOLING]
        out_cooling = [p for p in peers if p.state_outbound == PeerState.COOLING]  # fmt: off
        in_unknown = [p for p in peers if p.state_inbound == PeerState.UNKNOWN]  # fmt: off
        out_unknown = [
            p for p in peers if p.state_outbound == PeerState.UNKNOWN
        ]
        return {
            "in_cold": len(in_cold),
            "out_cold": len(out_cold),
            "in_warm": len(in_warm),
            "out_warm": len(out_warm),
            "in_hot": len(in_hot),
            "out_hot": len(out_hot),
            "in_cooling": len(in_cooling),
            "out_cooling": len(out_cooling),
            "in_unknown": len(in_unknown),
            "out_unknown": len(out_unknown),
            "total_peers": len(self.peers),
        }

    async def update_peers_from_connections(self, connections: list) -> None:
        """Takes a list of connections created from psutils net_connections().

        That is the library i use so this expects their named tuple of a
        connection.
        """

        logger.debug(f"Updating peers from {len(connections)} connections ")
        connection_keys = []
        new_peers = 0
        for conn in connections:
            raddr = conn.raddr
            laddr = conn.laddr
            local_addr, local_port = laddr.ip, int(laddr.port)
            remote_addr, remote_port = raddr.ip, int(raddr.port)
            key = (remote_addr, remote_port)
            if key not in self.peers:
                new_peers += 1
                self.peers[key] = Peer(
                    ns="CreatedFromConnections",  # Duh, hm i dont have that here
                    local_addr=local_addr,
                    local_port=local_port,
                    remote_addr=remote_addr,
                    remote_port=remote_port,
                    state_inbound=PeerState.UNKNOWN,
                    state_outbound=PeerState.UNKNOWN,
                )
            connection_keys.append(key)  # store keys to know which are new

        # Find the keys (peers) that
        keys_to_remove = [pk for pk in self.peers if pk not in connection_keys]
        for peer_key in keys_to_remove:
            logger.debug(
                f"Removed {self.peers[peer_key]} from peers because it has no connection"
            )
            del self.peers[peer_key]
