"""
logevent

The logevent module
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from ipaddress import ip_address
from typing import Any, Dict, Optional, Union

import rich
from pydantic import BaseModel, Field, ValidationError, validator

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
    LOSTCONNECTION = "LostConnection"
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


@dataclass
class Peer:
    addr: str
    port: int
    state: PeerState = PeerState.UNKNOWN
    last_updated: datetime = field(default_factory=datetime.now)
    direction: PeerDirection | None = None
    geo_info: dict | None = None
    probe_results: dict | None = None


class BaseBlockEvent(BaseModel):
    """Base model for all block events that will be produced by the log reader.

    The below fields are what i think every message will always have. The
    sec and thread fields are not of interested for now, so i did not include
    them.
    """

    at: datetime
    ns: str
    data: dict[str, Any]
    # sev: str
    # thread: str
    host: str

    @validator("at", pre=True)
    def parse_datetime(cls, value):
        """Convert ISO format string to datetime object."""
        if not isinstance(value, str):
            raise ValidationError(f"Timestamp is not a string [{value}]")
        return datetime.fromisoformat(value)  # this is tz aware!

    @property
    def namespace(self) -> str:
        """Return the namespace path as a dot-joined string."""
        return self.ns

    def print_debug(self):
        import rich  # noqa: PLC0415

        rich.print(self)

    @property
    def block_hash(self) -> str | None:
        """Return the hash of the block this event belongs to. As i dont see
        a pattern where to get that from i think every event class needs to
        implement that. Some events dont have a hash associated.
        """
        return None

    @property
    def block_number(self) -> str | None:
        return None

    @property
    def block_size(self):
        return None

    @property
    def slot(self) -> str | None:
        return None

    @property
    def peer_connection(self) -> Connection | None:
        # connection_string = self.data.get("peer").get("connectionId")
        if not self.connection_string:
            raise EventError(f"No connection_string defined in {self.__class__.__name__}")  # fmt: off
        connection = self._parse_connectionid(self.connection_string)
        return connection

    def _parse_connectionid(self, connectionid: str) -> Connection:
        """Parse connection ID string containing IPv4 or IPv6 addresses with ports.

        Supports formats:
        - IPv4: "192.168.1.1:8080 10.0.0.1:443"
        - IPv6: "[2001:db8::1]:8080 [::1]:443"
        """
        local_str, remote_str = connectionid.split(" ", 1)

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

        local_ip, local_port = parse_address_port(local_str)
        remote_ip, remote_port = parse_address_port(remote_str)

        return Connection(
            lip=local_ip,
            lport=local_port,
            rip=remote_ip,
            rport=remote_port,
        )

    def direction(self) -> PeerDirection | None:
        if ".Remote" in self.ns:
            return PeerDirection.OUTBOUND
        elif ".Local" in self.ns:
            return PeerDirection.INBOUND
        else:
            return None


class DownloadedHeaderEvent(BaseBlockEvent):
    """
    {
        "at": "2025-09-12T16:51:39.269022269Z",
        "ns": "ChainSync.Client.DownloadedHeader",
        "data": {
            "block": "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1",
            "blockNo": 3600148,
            "kind": "DownloadedHeader",
            "peer": {
                "connectionId": "172.0.118.125:30002 167.235.223.34:5355"
            },
            "slot": 91039899
        },
        "sev": "Info",
        "thread": "96913",
        "host": "openblockperf-dev-database1"
    }
    """

    @property
    def connection_string(self):
        return self.data.get("peer").get("connectionId")

    @property
    def block_hash(self) -> str:
        return self.data.get("block")

    @property
    def block_number(self) -> int:
        return int(self.data.get("blockNo"))

    @property
    def slot(self) -> int:
        return int(self.data.get("slot"))

    @property
    def peer_ip(self) -> str:
        """Ip address of peer the header was downloaded from"""
        return self.peer_connection.rip

    @property
    def peer_port(self) -> int:
        """Port number of peer the header was downloaded from"""
        return self.peer_connection.rport


class SendFetchRequestEvent(BaseBlockEvent):
    """
    {
        "at": "2025-09-12T16:52:11.098464254Z",
        "ns": "BlockFetch.Client.SendFetchRequest",
        "data": {
            "head": "e175320a3488c661d1b921b9cf4fb81d1c00d1b6650bf27536c859b90a1692b4",
            "kind": "SendFetchRequest",
            "length": 1,
            "peer": {
                "connectionId": "172.0.118.125:30002 73.222.122.247:23002"
            }
        },
        "sev": "Info",
        "thread": "88864",
        "host": "openblockperf-dev-database1"
    }
    """

    @property
    def connection_string(self):
        return self.data.get("peer").get("connectionId")

    @property
    def block_hash(self):
        """The block hash this fetch request tries to receive"""
        return self.data.get("head")

    @property
    def peer_ip(self) -> str:
        """Ip address of peer asked to download the block from"""
        return self.peer_connection.rip

    @property
    def peer_port(self) -> int:
        """Port number of peer asked to download the block from"""
        return self.peer_connection.rport


class CompletedBlockFetchEvent(BaseBlockEvent):
    """
    {
        "at": "2025-09-12T16:52:11.263418188Z",
        "ns": "BlockFetch.Client.CompletedBlockFetch",
        "data": {
            "block": "e175320a3488c661d1b921b9cf4fb81d1c00d1b6650bf27536c859b90a1692b4",
            "delay": 0.26330237,
            "kind": "CompletedBlockFetch",
            "peer": {
                "connectionId": "172.0.118.125:30002 73.222.122.247:23002"
            },
            "size": 2345
        },
        "sev": "Info",
        "thread": "88863",
        "host": "openblockperf-dev-database1"
    }
    """

    @property
    def connection_string(self):
        return self.data.get("peer").get("connectionId")

    @property
    def block_hash(self) -> str:
        return self.data.get("block")

    @property
    def delay(self) -> float:
        return float(self.data.get("delay"))

    @property
    def block_size(self) -> int:
        return int(self.data.get("size"))

    @property
    def peer_ip(self) -> str:
        """Ip address of peer the block was downloaded from"""
        return self.peer_connection.rip

    @property
    def peer_port(self) -> int:
        """Port number of peer the block was downloaded from"""
        return self.peer_connection.rport


class AddedToCurrentChainEvent(BaseBlockEvent):
    """

    {
        "at": "2025-09-12T16:51:39.255697717Z",
        "ns": "ChainDB.AddBlockEvent.AddedToCurrentChain",
        "data": {
            "headers": [
                {
                    "blockNo": "3600148",
                    "hash": "\"9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1\"",
                    "kind": "ShelleyBlock",
                    "slotNo": "91039899"
                }
            ],
            "kind": "AddedToCurrentChain",
            "newTipSelectView": {
                "chainLength": 3600148,
                "issueNo": 4,
                "issuerHash": "8019d8ef42bb1c92db7ccdbc88748625a62668ff5a0000e42bdb5030",
                "kind": "PraosChainSelectView",
                "slotNo": 91039899,
                "tieBreakVRF": "d58c41d2fd1710d5396411765743470bb13027a9c82f0d893e261b2748c404bb801587c06730834bd1e1d29c6b7abd71b1b36021f599a73526c1441d6c6a4ae6"
            },
            "newtip": "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1@91039899",
            "oldTipSelectView": {
                "chainLength": 3600147,
                "issueNo": 5,
                "issuerHash": "059388faa651bd3596c8892819c88e02a7a82e47a9df985286902566",
                "kind": "PraosChainSelectView",
                "slotNo": 91039878,
                "tieBreakVRF": "d2ee74b145193dfe6ec96dcdc2865aac42a9b14ee5b1f17d8b036be52ecf79e2f4d6de3ef9644f04e4a40dd516a299a239ee1f9c45e0311ffe1770547c87c2db"
            },
            "tipBlockHash": "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1",
            "tipBlockIssuerVKeyHash": "8019d8ef42bb1c92db7ccdbc88748625a62668ff5a0000e42bdb5030",
            "tipBlockParentHash": "838498b0cc666026ec366199ec89afd67a2febc932816acef9bbd2a1f59689a5"
        },
        "sev": "Notice",
        "thread": "27",
        "host": "openblockperf-dev-database1"
    }
    """

    @property
    def block_hash(self) -> str:
        # TODO: What if there are more or less then one header?
        # TODO: Why is this weird double quote here in the first place?
        _headers = self.data.get("headers")
        if not _headers:
            raise EventError(
                f"No or invalid headers in {self.__class__.__name__} at: '{self.at}' "
            )
        _hash = _headers[0].get("hash")
        if _hash.startswith('"'):
            _hash = _hash[1:]
        if _hash.endswith('"'):
            _hash = _hash[:-1]
        return _hash


class TrySwitchToAForkEvent:
    """
    {
        "at": "2025-09-12T16:51:18.695700181Z",
        "ns": "ChainDB.AddBlockEvent.TrySwitchToAFork",
        "data": {
            "block": {
                "hash": "838498b0cc666026ec366199ec89afd67a2febc932816acef9bbd2a1f59689a5",
                "kind": "Point",
                "slot": 91039878
            },
            "kind": "TraceAddBlockEvent.TrySwitchToAFork"
        },
        "sev": "Info",
        "thread": "27",
        "host": "openblockperf-dev-database1"
    }
    """

    pass


class SwitchedToAForkEvent(BaseBlockEvent):
    """
    {
        "at": "2025-09-12T16:51:18.698911267Z",
        "ns": "ChainDB.AddBlockEvent.SwitchedToAFork",
        "data": {
            "headers": [
                {
                    "blockNo": "3600147",
                    "hash": "\"838498b0cc666026ec366199ec89afd67a2febc932816acef9bbd2a1f59689a5\"",
                    "kind": "ShelleyBlock",
                    "slotNo": "91039878"
                }
            ],
            "kind": "TraceAddBlockEvent.SwitchedToAFork",
            "newTipSelectView": {
                "chainLength": 3600147,
                "issueNo": 5,
                "issuerHash": "059388faa651bd3596c8892819c88e02a7a82e47a9df985286902566",
                "kind": "PraosChainSelectView",
                "slotNo": 91039878,
                "tieBreakVRF": "d2ee74b145193dfe6ec96dcdc2865aac42a9b14ee5b1f17d8b036be52ecf79e2f4d6de3ef9644f04e4a40dd516a299a239ee1f9c45e0311ffe1770547c87c2db"
            },
            "newtip": "838498b0cc666026ec366199ec89afd67a2febc932816acef9bbd2a1f59689a5@91039878",
            "oldTipSelectView": {
                "chainLength": 3600147,
                "issueNo": 11,
                "issuerHash": "3867a09729a1f954762eea035a82e2d9d3a14f1fa791a022ef0da242",
                "kind": "PraosChainSelectView",
                "slotNo": 91039878,
                "tieBreakVRF": "d4e7a472bd5d387277867906dbbed1d0a4a7d261043384f7728000f87b095d4b7b6924fc6207ee615b537361d2b2007f4f16147a4668035b433e559d4702abb1"
            },
            "tipBlockHash": "838498b0cc666026ec366199ec89afd67a2febc932816acef9bbd2a1f59689a5",
            "tipBlockIssuerVKeyHash": "059388faa651bd3596c8892819c88e02a7a82e47a9df985286902566",
            "tipBlockParentHash": "9bea882f9be9bcce376eb16e263e9e0aa9a488a46fccbcae3c9e449378b35ee5"
        },
        "sev": "Notice",
        "thread": "27",
        "host": "openblockperf-dev-database1"
    }
    """

    @property
    def block_hash(self) -> str:
        # TODO: Thats so ugly, Why is the header block hash with extra
        #       double quotes ???
        _headers = self.data.get("headers")
        if not _headers:
            raise EventError(
                f"No or invalid headers in {self.__class__.__name__} at: '{self.at}' "
            )
        _hash = _headers[0].get("hash")
        if _hash.startswith('"'):
            _hash = _hash[1:]
        if _hash.endswith('"'):
            _hash = _hash[:-1]
        return _hash


@dataclass
class PeerStatusChange:
    """Represents the change of the peer in a StatusChangedEvent.

    That event needs more logic to determine which final state of the peer
    it represents. The _parse_peer_status_change() function parses that
    status change message into this change object. Which then can tell
    the state the event is in."""

    transition: PeerStateTransition
    state: PeerState
    local_addr: str
    local_port: int
    remote_addr: str
    remote_port: int


class InboundGovernorCountersEvent(BaseBlockEvent):
    """
    {
        "at": "2025-09-24T13:32:19.517600273Z",
        "ns": "Net.InboundGovernor.Remote.InboundGovernorCounters",
        "data": {
            "coldPeers": 53,
            "hotPeers": 0,
            "idlePeers": 1,
            "kind": "InboundGovernorCounters",
            "warmPeers": 1
        },
        "sev": "Info",
        "thread": "124",
        "host": "openblockperf-dev-database1"
    }
    """

    pass


class StatusChangedEvent(BaseBlockEvent):
    """
    {
        "at": "2025-09-24T13:04:05.509293074Z",
        "ns": "Net.PeerSelection.Actions.StatusChanged",
        "data": {
            "kind": "PeerStatusChanged",
            "peerStatusChangeType": "ColdToWarm (Just 172.0.118.125:3001) 3.228.174.253:6000"
        },
        "sev": "Info",
        "thread": "8915",
        "host":"openblockperf-dev-database1"
    }
    """

    @property
    def peer_status_change(self):
        return self._parse_peer_status_change(
            self.data.get("peerStatusChangeType")
        )

    @property  # Must be property because its an attribute on the other events!
    def state(self) -> PeerState:
        return self.peer_status_change.state

    def peer_addr_port(self) -> (str, int):
        return (
            self.peer_status_change.remote_addr,
            int(self.peer_status_change.remote_port),
        )

    def _parse_peer_status_change(
        self, status_change_string: str
    ) -> PeerStatusChange:
        """Parse a peer status change string into a structured PeerStatusChange object.

        Damn this is ugly... examples:
            * "ColdToWarm (Just 172.0.118.125:3001) 118.153.253.133:17314"
            * "WarmToCooling (ConnectionId {localAddress = [2a05:d014:1105:a503:8406:964c:5278:4c24]:3001, remoteAddress = [2600:4040:b4fd:f40:42e5:c5de:7ed3:ce19]:33525})"

        I am assuming that there are two distinct variants of "Transitions". The ones
            * For new connections? -> Containing Just
            * For existing connections? -> Containing ConnectionId
        If we cant find those, we are screwed.
        """

        # Extract state transition
        state_match = re.match(r"(\w+)To(\w+)", status_change_string)
        if not state_match:
            raise ValueError(
                f"Invalid state transition format: {status_change_string}"
            )

        from_state, to_state = state_match.groups()[0], state_match.groups()[1]  # fmt: off
        rich.print(f"{from_state=},{to_state=}")

        # Pattern for IPv6 address (with brackets) or IPv4 address
        # i dont understand this, i asked ai
        addr_pattern = r"(?:\[([^\]]+)\]|([^:\s]+)):(\d+)"

        # Now either search a 'Just' variant or the 'ConnectionId' one
        if "Just" in status_change_string:
            # Build new pattern for 'Just' string to extract local and remote ip and port
            # e.g.: "StateToState (Just local_addr:port) remote_addr:port"
            pattern = rf"{from_state}To{to_state} \(Just {addr_pattern}\) {addr_pattern}"
            match = re.match(pattern, status_change_string)
            if not match:
                raise ValueError(
                    f"Invalid 'Just' format: {status_change_string}"
                )

            # Groups: (ipv6_local, ipv4_local, port_local, ipv6_remote, ipv4_remote, port_remote)
            groups = match.groups()
            local_addr = groups[0] or groups[1]
            local_port = int(groups[2])
            remote_addr = groups[3] or groups[4]
            remote_port = int(groups[5])

        elif "ConnectionId" in status_change_string:
            # Same thing, build new pattern for 'ConnectionId' string
            # Pattern: "StateToState (ConnectionId {localAddress = addr:port, remoteAddress = addr:port})"
            pattern = rf"{from_state}To{to_state} \(ConnectionId \{{localAddress = {addr_pattern}, remoteAddress = {addr_pattern}\}}\)"
            match = re.match(pattern, status_change_string)
            if not match:
                raise ValueError(
                    f"Invalid 'ConnectionId' format: {status_change_string}"
                )

            # Groups: (ipv6_local, ipv4_local, port_local, ipv6_remote, ipv4_remote, port_remote)
            groups = match.groups()
            local_addr = groups[0] or groups[1]
            local_port = int(groups[2])
            remote_addr = groups[3] or groups[4]
            remote_port = int(groups[5])
        else:
            raise ValueError(
                f"Unrecognized format (no 'Just' or 'ConnectionId'): {status_change_string}"
            )

        # Check if we actually extraced something that is an ip address
        try:
            ip_address(local_addr)
            ip_address(remote_addr)
        except ValueError as e:
            raise ValueError(
                f"Invalid IP address in connection string: {e}"
            ) from e

        # Return the finished change this event represents
        return PeerStatusChange(
            transition=PeerStateTransition(f"{from_state}To{to_state}"),
            state=PeerState(to_state),
            local_addr=local_addr,
            local_port=local_port,
            remote_addr=remote_addr,
            remote_port=remote_port,
        )


class PromotedToWarmRemoteEvent(BaseBlockEvent):
    """
        {
        "at": "2025-09-24T13:32:19.859124767Z",
        "ns": "Net.InboundGovernor.Remote.PromotedToWarmRemote",
        "data": {
            "connectionId": {
                "localAddress": {
                    "address": "172.0.118.125",
                    "port": "3001"
                },
                "remoteAddress": {
                    "address": "85.106.4.146",
                    "port": "3001"
                }
            },
            "kind": "PromotedToWarmRemote",
            "result": {
                "kind": "OperationSuccess",
                "operationSuccess": {
                    "dataFlow": "Duplex",
                    "kind": "InboundIdleSt"
                }
            }
        },
        "sev": "Info",
        "thread": "124",
        "host": "openblockperf-dev-database1"
    }
    """

    state: PeerState = PeerState.WARM

    def peer_addr_port(self) -> (str, int):
        con_id = self.data.get("connectionId")
        remote = con_id.get("remoteAddress")
        return (remote.get("address"), int(remote.get("port")))

    def __repr__(self):
        addr, port = self.peer_addr_port()
        return f"{self.__class__.__name__}(addr={addr}, port={port}, at={self.at.isoformat()})"


class PromotedToHotRemoteEvent(BaseBlockEvent):
    """
    {
        "at": "2025-09-24T13:32:19.888897773Z",
        "ns": "Net.InboundGovernor.Remote.PromotedToHotRemote",
        "data": {
            "connectionId": {
                "localAddress": {
                    "address": "172.0.118.125",
                    "port": "3001"
                },
                "remoteAddress": {
                    "address": "85.106.4.146",
                    "port": "3001"
                }
            },
            "kind": "PromotedToHotRemote"
        },
        "sev": "Info",
        "thread": "124",
        "host": "openblockperf-dev-database1"
    }
    """

    state: PeerState = PeerState.HOT

    def peer_addr_port(self) -> (str, int):
        con_id = self.data.get("connectionId")
        remote = con_id.get("remoteAddress")
        return (remote.get("address"), int(remote.get("port")))

    def __repr__(self):
        addr, port = self.peer_addr_port()
        return f"{self.__class__.__name__}(addr={addr}, port={port}, at={self.at.isoformat()})"


class DemotedToColdRemoteEvent(BaseBlockEvent):
    state: PeerState = PeerState.COLD

    def peer_addr_port(self) -> (str, int):
        con_id = self.data.get("connectionId")
        remote = con_id.get("remoteAddress")
        return (remote.get("address"), int(remote.get("port")))

    def __repr__(self):
        addr, port = self.peer_addr_port()
        return f"{self.__class__.__name__}(addr={addr}, port={port}, at={self.at.isoformat()})"


class DemotedToWarmRemoteEvent(BaseBlockEvent):
    state: PeerState = PeerState.WARM

    def peer_addr_port(self) -> (str, int):
        con_id = self.data.get("connectionId")
        remote = con_id.get("remoteAddress")
        return (remote.get("address"), int(remote.get("port")))

    def __repr__(self):
        addr, port = self.peer_addr_port()
        return f"{self.__class__.__name__}(addr={addr}, port={port}, at={self.at.isoformat()})"


class StartedEvent(BaseBlockEvent):
    pass
