""" """

import re
from enum import Enum
from ipaddress import ip_address
from typing import Any

import rich
from loguru import logger
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
    validator,
)

from blockperf.errors import EventError

from .base import BaseEvent

# Used strings here and not the PeerState enum to keep the events simple
# as well as not coupled to the event module.
STATES = {
    "Net.InboundGovernor.Local.DemotedToColdRemote": "Cold",
    "Net.InboundGovernor.Local.DemotedToWarmRemote": "Warm",
    "Net.InboundGovernor.Local.PromotedToHotRemote": "Hot",
    "Net.InboundGovernor.Local.PromotedToWarmRemote": "Warm",
    "Net.InboundGovernor.Remote.PromotedToHotRemote": "Hot",
    "Net.InboundGovernor.Remote.PromotedToWarmRemote": "Warm",
    "Net.InboundGovernor.Remote.DemotedToColdRemote": "Cold",
    "Net.InboundGovernor.Remote.DemotedToWarmRemote": "Warm",
}


class PeerEvent(BaseEvent):
    """The PeerEvent combines all events from the logs that provide Peer
    status change relevant data.

    The BaseEvent handles all toplevel fields. This Model uses the model validator
    To parse the data field and grab the needed values into this models attributes.

    """

    state: str
    direction: str
    local_addr: str
    local_port: int
    remote_addr: str
    remote_port: int

    @model_validator(mode="before")
    @classmethod
    def parse(cls, data: Any):
        ns = data.get("ns")
        _data = data.get("data")
        if ns == "Net.PeerSelection.Actions.StatusChanged":
            data = cls.parse_statuschange_data(data)
        else:
            data = cls.parse_simple_data(data)

        return data

    def remote_addr_port(self) -> (str, int):
        logger.info("Do i really need that?")
        return (self.remote_addr, self.remote_port)

    def key(self):
        """Returns the key for this peer whihc is a tuple of the remote addr and port."""
        return (self.remote_addr, self.remote_port)

    @classmethod
    def parse_simple_data(cls, data) -> dict:
        """Parses the simple data that is found in most events.

        Assumes
            DemotedToColdRemote
            DemotedToWarmRemote
            PromotedToHotRemote
            PromotedToWarmRemote
        """
        ns = data.get("ns")

        # State
        if ns not in STATES:
            _msg = "Event not in supported events"
            logger.exception(_msg, namespace=ns)
            raise EventError(_msg)
        data["state"] = STATES.get(ns)

        # Direction
        if ".Remote" in ns:
            data["direction"] = "Inbound"
        elif ".Local" in ns:
            data["direction"] = "Outbound"
        else:
            # This should not happen ... as far as i can tell right now...
            _msg = "Event does not have a direction"
            logger.exception(_msg, namespace=ns)
            raise EventError(_msg)

        # Remote and Local address and port
        conid = data.get("data").get("connectionId")
        data["local_addr"] = conid.get("localAddress").get("address")
        data["local_port"] = conid.get("localAddress").get("port")
        data["remote_addr"] = conid.get("remoteAddress").get("address")
        data["remote_port"] = conid.get("remoteAddress").get("port")
        return data

    @classmethod
    def parse_statuschange_data(cls, data) -> dict:
        # data["local_addr"] = conid.get("localAddress").get("address")
        # data["local_port"] = conid.get("localAddress").get("port")
        # data["remote_addr"] = conid.get("remoteAddress").get("address")
        # data["remote_port"] = conid.get("remoteAddress").get("port")
        # return data

        """Parse a peer status change string into a structured PeerStatusChange object.

        Damn this is ugly... examples:
            * "ColdToWarm (Just 172.0.118.125:3001) 118.153.253.133:17314"
            * "WarmToCooling (ConnectionId {localAddress = [2a05:d014:1105:a503:8406:964c:5278:4c24]:3001, remoteAddress = [2600:4040:b4fd:f40:42e5:c5de:7ed3:ce19]:33525})"

        I am assuming that there are two distinct variants of "Transitions". The ones
            * For new connections -> Containing  "Just"
            * For (existing?) connections -> Containing "ConnectionId"
        If we cant find those, we are screwed.

        """
        psct = data.get("data").get("peerStatusChangeType")

        # Extract from_state and to_state
        state_match = re.match(r"(\w+)To(\w+)", psct)
        if not state_match:
            raise ValueError(f"Invalid state transition format: {psct}")
        from_state, to_state = state_match.groups()[0], state_match.groups()[1]  # fmt: off
        logger.debug(f"{from_state=},{to_state=}")

        # Pattern for IPv6 address (with brackets) or IPv4 address
        # i dont understand this, i asked ai
        addr_pattern = r"(?:\[([^\]]+)\]|([^:\s]+)):(\d+)"

        # Now either search a 'Just' variant or the 'ConnectionId' one
        if "Just" in psct:
            # Build new pattern for 'Just' string to extract local and remote ip and port
            # e.g.: "StateToState (Just local_addr:port) remote_addr:port"
            pattern = rf"{from_state}To{to_state} \(Just {addr_pattern}\) {addr_pattern}"
            match = re.match(pattern, psct)
            if not match:
                raise ValueError(f"Invalid 'Just' format: {psct}")

            # Groups: (ipv6_local, ipv4_local, port_local, ipv6_remote, ipv4_remote, port_remote)
            groups = match.groups()
            local_addr = groups[0] or groups[1]
            local_port = int(groups[2])
            remote_addr = groups[3] or groups[4]
            remote_port = int(groups[5])
        elif "ConnectionId" in psct:
            # Same thing, build new pattern for 'ConnectionId' string
            # Pattern: "StateToState (ConnectionId {localAddress = addr:port, remoteAddress = addr:port})"
            pattern = rf"{from_state}To{to_state} \(ConnectionId \{{localAddress = {addr_pattern}, remoteAddress = {addr_pattern}\}}\)"
            match = re.match(pattern, psct)
            if not match:
                raise ValueError(f"Invalid 'ConnectionId' format: {psct}")

            # Groups: (ipv6_local, ipv4_local, port_local, ipv6_remote, ipv4_remote, port_remote)
            groups = match.groups()
            local_addr = groups[0] or groups[1]
            local_port = int(groups[2])
            remote_addr = groups[3] or groups[4]
            remote_port = int(groups[5])
        else:
            raise ValueError(
                f"Unrecognized format (no 'Just' or 'ConnectionId'): {psct}"
            )

        # Check if we actually extraced something that is an ip address
        try:
            ip_address(local_addr)
            ip_address(remote_addr)
        except ValueError as e:
            raise ValueError(
                f"Invalid IP address in connection string: {e}"
            ) from e

        # Assuming the StatusChange is alwasy from the local peer
        direction = "Outbound"

        # Pack everything back into data and return
        data["state"] = to_state
        data["direction"] = direction
        data["local_addr"] = local_addr
        data["local_port"] = local_port
        data["remote_addr"] = remote_addr
        data["remote_port"] = remote_port
        return data


class InboundGovernorCountersEvent(BaseEvent):
    """ """

    idle_peers: int
    cold_peers: int
    warm_peers: int
    hot_peers: int

    @model_validator(mode="before")
    @classmethod
    def parse(cls, data: Any):
        data["idle_peers"] = data.get("data").get("idlePeers")
        data["cold_peers"] = data.get("data").get("coldPeers")
        data["warm_peers"] = data.get("data").get("warmPeers")
        data["hot_peers"] = data.get("data").get("hotPeers")

        return data

    def __str__(self):
        return f"<{self.__class__.__name__}, idle: {self.idle_peers}, cold: {self.cold_peers}, warm: {self.warm_peers} hot: {self.hot_peers}>"


class StatusChangedEvent(PeerEvent):
    """ """

    pass


class PromotedPeerEvent(PeerEvent):
    """ """

    pass


class DemotedPeerEvent(PeerEvent):
    """ """

    pass
