""" """

import enum
import re
from ipaddress import ip_address
from typing import Any

from loguru import logger
from pydantic import model_validator

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


class PeerEventChangeType(enum.Enum):
    COLD_WARM = "cold_to_warm"
    WARM_HOT = "warm_to_hot"
    HOT_WARM = "hot_to_warm"
    WARM_COLD = "warm_to_cold"


class PeerEvent(BaseEvent):
    """The PeerEvent combines all details from individual events that provide
    Peer status change relevant data.

    This Model uses the model validator to parse the data from the logs and
    put the needed values into this attributes. That makes the PeerEvent
    able to provide:

    * The current and previous state of the Peer -> Warm, Hot, Cold
    * The direction of the connection "inbound/outbound"
    * The remotes address / port
    * The local address / port

    This provides the detailed overview of any event and will be send to
    the api.
    """

    state: str
    direction: str
    local_addr: str
    local_port: int
    remote_addr: str
    remote_port: int
    change_type: PeerEventChangeType

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
            data["direction"] = "inbound"
        elif ".Local" in ns:
            data["direction"] = "outbound"
        else:
            # This should not happen ... as far as i can tell right now...
            _msg = "Event does not have a direction"
            logger.exception(_msg, namespace=ns)
            raise EventError(_msg)

        # Change type
        _change_type = None
        if ns in [
            "Net.InboundGovernor.Local.DemotedToColdRemote",
            "Net.InboundGovernor.Remote.DemotedToColdRemote",
        ]:
            _change_type = PeerEventChangeType.WARM_COLD
        elif ns in [
            "Net.InboundGovernor.Local.DemotedToWarmRemote",
            "Net.InboundGovernor.Remote.DemotedToWarmRemote",
        ]:
            _change_type = PeerEventChangeType.HOT_WARM
        elif ns in [
            "Net.InboundGovernor.Local.PromotedToHotRemote",
            "Net.InboundGovernor.Remote.PromotedToHotRemote",
        ]:
            _change_type = PeerEventChangeType.WARM_HOT
        elif ns in [
            "Net.InboundGovernor.Local.PromotedToWarmRemote",
            "Net.InboundGovernor.Remote.PromotedToWarmRemote",
        ]:
            _change_type = PeerEventChangeType.COLD_WARM
        else:
            pass

        if not _change_type:
            raise Exception("Event namespace notfound for change type")
        data["change_type"] = _change_type

        # Remote and Local address and port
        conid = data.get("data").get("connectionId")
        data["local_addr"] = conid.get("localAddress").get("address")
        data["local_port"] = conid.get("localAddress").get("port")
        data["remote_addr"] = conid.get("remoteAddress").get("address")
        data["remote_port"] = conid.get("remoteAddress").get("port")

        return data

    @classmethod
    def parse_statuschange_data(cls, data) -> dict:
        """Parse a peer status change string into a structured PeerStatusChange object.

        I am assuming that there are two distinct variants of "Transitions".
        One for new connections (containing the word "Just". And one for
        existing connections (containing the word "ConnectionId").

        If we cant find those, we are screwed.
        Examples:
            * "ColdToWarm (Just 172.0.118.125:3001) 118.153.253.133:17314"
            * "WarmToCooling (ConnectionId {localAddress = [2a05:d014:1105:a503:8406:964c:5278:4c24]:3001, remoteAddress = [2600:4040:b4fd:f40:42e5:c5de:7ed3:ce19]:33525})"

        """
        psct = data.get("data").get("peerStatusChangeType")

        # Extract from_state and to_state
        state_match = re.match(r"(\w+)To(\w+)", psct)
        if not state_match:
            raise ValueError(f"Invalid state transition format: {psct}")

        # Grab the from and to state from the string. E.v. "Warm", "Cold" "Hot" etc.
        from_state, to_state = state_match.groups()[0], state_match.groups()[1]  # fmt: off
        logger.debug(f"{from_state=},{to_state=}")

        # Reges pattern to match IPv4 and  IPv6 addresses
        addr_pattern = r"(?:\[([^\]]+)\]|([^:\s]+)):(\d+)"

        # Search for either "Just | ConnectionId" in the string to determine what
        # kind of transition this is. Depending on that the extraction of the ipaddress differs
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
        direction = "outbound"

        # Change Type
        #

        data["change_type"] = PeerEventChangeType(
            f"{from_state.lower()}_to_{to_state.lower()}"
        )

        # Pack everything back into data and return
        data["state"] = to_state
        data["direction"] = direction
        data["local_addr"] = local_addr
        data["local_port"] = local_port
        data["remote_addr"] = remote_addr
        data["remote_port"] = remote_port
        return data


class InboundGovernorCountersEvent(BaseEvent):
    """

    Inherits from BaseEvent because it does not have "state".
    """

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
