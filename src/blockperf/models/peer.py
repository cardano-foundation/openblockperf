# from __future__ import annotations


from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from loguru import logger
from pydantic import (
    BaseModel,
    ValidationError,
    model_validator,
)


@dataclass(frozen=True)
class Connection:
    lip: str  # Local IP
    lport: int  # Local Port
    rip: str  # Remote IP
    rport: int  # Remote Port


class PeerDirection(Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class PeerState(Enum):
    UNKNOWN = "Unknown"
    UNCONNECTED = "Unconnected"
    COLD = "Cold"
    WARM = "Warm"
    HOT = "Hot"
    COOLING = "Cooling"


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

    ns: str | None  # The namespace of the event, kept for later debugging
    local_addr: str
    local_port: int
    remote_addr: str  # IP address of the remote
    remote_port: int  # Port number of remote
    state_inbound: PeerState = PeerState.UNCONNECTED
    state_outbound: PeerState = PeerState.UNCONNECTED
    last_updated: datetime = field(default_factory=datetime.now)
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
