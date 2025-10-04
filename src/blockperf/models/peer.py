# from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from ipaddress import ip_address
from typing import Any, Dict, Optional, Union

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


@dataclass(frozen=True)
class Connection:
    lip: str  # Local IP
    lport: int  # Local Port
    rip: str  # Remote IP
    rport: int  # Remote Port


class PeerDirection(Enum):
    INBOUND = "Inbound"
    OUTBOUND = "Outbound"


class PeerState(Enum):
    UNKNOWN = "Unknown"
    UNCONNECTED = "Unconnected"
    COLD = "Cold"
    WARM = "Warm"
    HOT = "Hot"
    COOLING = "Cooling"


class PeerStateTransition(Enum):
    COLD_TO_WARM = "ColdToWarm"
    WARM_TO_HOT = "WarmToHot"
    WARM_TO_COOLING = "WarmToCooling"
    HOT_TO_WARM = "HotToWarm"
    HOT_TO_COOLING = "HotToCooling"
    COOLING_TO_COLD = "CoolingToCold"


class Peer(BaseModel):
    """A Peer is a remote node this (local) node is connected with.

    The Peers are uniquely identified by the ip address and port combination.
    They are kept in a dict using a tuple of the address and port combination
    as the key.

    A Peer can be connected with this node in two ways.
    * Incoming connections: Someone opened a connection to us.
    * Outgoing connections: We opened a connetion to someone.

    The messages from the logs do not clearly indicate which connection is
    incoming or outgoing. We must try to figure it out by assuming that the
    connections are usually made to service ports in the 1000-10000 range.
    While outgoing connections



    """

    addr: str
    port: int
    state_inbound: PeerState = PeerState.UNCONNECTED
    state_outbound: PeerState = PeerState.UNCONNECTED
    last_updated: datetime = field(default_factory=datetime.now)
    direction: PeerDirection | None = None
    geo_info: dict | None = None
    probe_results: dict | None = None


class PeerConnectionString(BaseModel):
    """Represents the simple variant of the connectionId string found in the messages.

    Supports formats:
        - IPv4: "192.168.1.1:8080 10.0.0.1:443"
        - IPv6: "[2001:db8::1]:8080 [::1]:443"

    Parses the input and filles local,remote address, port fields with the
    corresponding values. {local_addr:local_port remote_addr:remote_port}
    """

    local_addr: str
    local_port: int
    remote_addr: str
    remote_port: int

    @model_validator(mode="before")
    @classmethod
    def parse_connection_string(cls, data: Any) -> dict[str, Any]:
        """Parse connection ID string containing IPv4 or IPv6 addresses with ports."""
        # If already a dict, pass through (allows normal instantiation)
        if not isinstance(data, str):
            raise ValidationError("Given connectionId is not a str")

        local_str, remote_str = data.split(" ", 1)

        def parse_address_port(addr_port: str) -> tuple[str, int]:
            if addr_port.startswith("["):
                # IPv6 format: [address]:port
                bracket_end = addr_port.rfind("]")
                if bracket_end == -1:
                    raise ValueError(f"Invalid IPv6 format: {addr_port}")
                address = addr_port[1:bracket_end]
                port = int(addr_port[bracket_end + 2 :])  # Skip ']:'
            else:
                # IPv4 format: address:port
                address, port_str = addr_port.rsplit(":", 1)
                port = int(port_str)
            return address, port

        local_addr, local_port = parse_address_port(local_str)
        remote_addr, remote_port = parse_address_port(remote_str)
        return {
            "local_addr": local_addr,
            "local_port": int(local_port),
            "remote_addr": remote_addr,
            "remote_port": int(remote_port),
        }


class PeerConnectionSimple(BaseModel):
    """Represents a peer in the simple string format.

    Example:
            "connectionId": "172.0.118.125:30002 73.222.122.247:23002"


    Found in:
        * DownloadedHeaderEvent
        * SendFetchRequestEvent
        * CompletedBlockFetchEvent

    """

    connectionId: PeerConnectionString  # noqa: N815


class PeerConnectionComplex(BaseModel):
    """Represents a peer in the complex format.

    Example:
        "connectionId": {
            "localAddress": {
                "address": "172.0.118.125",
                "port": "3001"
            },
            "remoteAddress": {
                "address": "85.106.4.146",
                "port": "3001"
            }
        }

    """

    class PeerConnectionComplexAddrPort(BaseModel):
        address: str
        port: int

    localAddress: PeerConnectionComplexAddrPort
    remoteAddress: PeerConnectionComplexAddrPort


class PeerStatusChange(BaseModel):
    """Represents the change of the peer in a StatusChangedEvent.
    That event needs more logic to determine which final state of the peer
    it represents. The _parse_peer_status_change() function parses that
    status change message into this change object. Which then can tell
    the state the event is in."""

    transition: PeerStateTransition
    from_state: PeerState
    to_state: PeerState
    local_addr: str
    local_port: int
    remote_addr: str
    remote_port: int

    @model_validator(mode="before")
    @classmethod
    def parse_peer_status_change_string(cls, data: Any) -> dict[str, Any]:
        """Parse a peer status change string into a structured PeerStatusChange object.

        Damn this is ugly... examples:
            * "ColdToWarm (Just 172.0.118.125:3001) 118.153.253.133:17314"
            * "WarmToCooling (ConnectionId {localAddress = [2a05:d014:1105:a503:8406:964c:5278:4c24]:3001, remoteAddress = [2600:4040:b4fd:f40:42e5:c5de:7ed3:ce19]:33525})"

        I am assuming that there are two distinct variants of "Transitions". The ones
            * For new connections -> Containing  "Just"
            * For (existing?) connections -> Containing "ConnectionId"
        If we cant find those, we are screwed.

        """
        # If already a dict, pass through (allows normal instantiation)
        if not isinstance(data, str):
            raise ValidationError("Given connectionId is not a str")

        # Extract from_state and to_state
        state_match = re.match(r"(\w+)To(\w+)", data)
        if not state_match:
            raise ValueError(f"Invalid state transition format: {data}")
        from_state, to_state = state_match.groups()[0], state_match.groups()[1]  # fmt: off
        logger.debug(f"{from_state=},{to_state=}")

        # Pattern for IPv6 address (with brackets) or IPv4 address
        # i dont understand this, i asked ai
        addr_pattern = r"(?:\[([^\]]+)\]|([^:\s]+)):(\d+)"

        # Now either search a 'Just' variant or the 'ConnectionId' one
        if "Just" in data:
            # Build new pattern for 'Just' string to extract local and remote ip and port
            # e.g.: "StateToState (Just local_addr:port) remote_addr:port"
            pattern = rf"{from_state}To{to_state} \(Just {addr_pattern}\) {addr_pattern}"
            match = re.match(pattern, data)
            if not match:
                raise ValueError(f"Invalid 'Just' format: {data}")

            # Groups: (ipv6_local, ipv4_local, port_local, ipv6_remote, ipv4_remote, port_remote)
            groups = match.groups()
            local_addr = groups[0] or groups[1]
            local_port = int(groups[2])
            remote_addr = groups[3] or groups[4]
            remote_port = int(groups[5])

        elif "ConnectionId" in data:
            # Same thing, build new pattern for 'ConnectionId' string
            # Pattern: "StateToState (ConnectionId {localAddress = addr:port, remoteAddress = addr:port})"
            pattern = rf"{from_state}To{to_state} \(ConnectionId \{{localAddress = {addr_pattern}, remoteAddress = {addr_pattern}\}}\)"
            match = re.match(pattern, data)
            if not match:
                raise ValueError(f"Invalid 'ConnectionId' format: {data}")

            # Groups: (ipv6_local, ipv4_local, port_local, ipv6_remote, ipv4_remote, port_remote)
            groups = match.groups()
            local_addr = groups[0] or groups[1]
            local_port = int(groups[2])
            remote_addr = groups[3] or groups[4]
            remote_port = int(groups[5])
        else:
            raise ValueError(
                f"Unrecognized format (no 'Just' or 'ConnectionId'): {data}"
            )

        # Check if we actually extraced something that is an ip address
        try:
            ip_address(local_addr)
            ip_address(remote_addr)
        except ValueError as e:
            raise ValueError(
                f"Invalid IP address in connection string: {e}"
            ) from e
        return {
            "transition": PeerStateTransition(f"{from_state}To{to_state}"),
            "from_state": PeerState(from_state),
            "to_state": PeerState(to_state),
            "local_addr": local_addr,
            "local_port": local_port,
            "remote_addr": remote_addr,
            "remote_port": remote_port,
        }
