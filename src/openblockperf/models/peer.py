from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

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


class EventRole(Enum):
    """What a submitted peerevent means in the session model."""

    OPEN = "open"
    TEMPERATURE = "temperature"
    CLOSE = "close"
    EPOCH = "epoch"


class CloseReason(Enum):
    """Why a session ended. Unexpected vs planned is derived from these."""

    IG_MUX_ERROR = "ig_mux_error"
    IG_RESPONDER_ERROR = "ig_responder_error"
    HANDLER_ERROR = "handler_error"
    DEMOTED_COLD = "demoted_cold"
    COOLING_TO_COLD = "cooling_to_cold"
    NODE_EPOCH = "node_epoch"
    TTL = "ttl"


# TCP source ports in this range are not relay listen ports.
EPHEMERAL_PORT_MIN = 32768


def is_ephemeral_port(port: int) -> bool:
    return port >= EPHEMERAL_PORT_MIN


class Peer(BaseModel):
    """IP-level view derived from connection sessions.

    Sessions are keyed by connectionId (local+remote addr/port). This object
    is the per-remote-IP rollup used for last_signal from blocksamples and
    for submit field mapping.
    """

    ns: str | None  # The namespace of the event, kept for later debugging
    local_addr: str
    local_port: int
    remote_addr: str  # IP address of the remote
    remote_port: int  # Listen port when known; 0 if ephemeral / unknown
    state_inbound: PeerState = PeerState.UNCONNECTED
    state_outbound: PeerState = PeerState.UNCONNECTED
    # Unused leftover for API default; not a product field.
    duplex: bool = False
    # Latest ConnectionManager HandshakeSuccess enrichment (optional).
    n2n_version: int | None = None
    diffusion_mode: str | None = None
    peer_sharing: str | None = None
    peras_support: str | None = None
    # Presence: first time we learned about this IP; last peerevent / HS / header / body.
    first_seen: datetime | None = None
    last_signal: datetime | None = None
    # Alias bumped with last_signal (prune / diagnostics).
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
