"""
logevent

The logevent module
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field, ValidationError, validator


class EventError(RuntimeError):
    pass


@dataclass(frozen=True)
class Connection:
    lip: str  # Local IP
    lport: int  # Local Port
    rip: str  # Remote IP
    rport: int  # Remote Port


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
            raise RuntimeError(f"No connection_string defined in {self.__class__.__name__}")  # fmt: off
        connection = parse_connectionid(self.connection_string)
        return connection


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


"""
Added some of the events that i think are of interest. See here for more:
https://github.com/input-output-hk/cardano-node-wiki/blob/main/docs/new-tracing/tracers_doc_generated.md
"""
EVENT_REGISTRY = {
    "BlockFetch.Client.CompletedBlockFetch": CompletedBlockFetchEvent,
    "BlockFetch.Client.SendFetchRequest": SendFetchRequestEvent,
    # "BlockFetch.Remote.Receive.ClientDone": ClientDoneEvent,
    # "BlockFetch.Remote.Send.Block": None,
    "ChainDB.AddBlockEvent.AddedToCurrentChain": AddedToCurrentChainEvent,
    # "ChainDB.AddBlockEvent.BlockInTheFuture": BlockInTheFutureEvent,
    "ChainDB.AddBlockEvent.SwitchedToAFork": SwitchedToAForkEvent,
    # "ChainDB.AddBlockEvent.TrySwitchToAFork": TrySwitchToAForkEvent,
    # "ChainDB.AddBlockEvent.TryAddToCurrentChain": TryAddToCurrentChainEvent,
    "ChainSync.Client.DownloadedHeader": DownloadedHeaderEvent,
    # "ChainSync.Client.RolledBack": RolledBackEvent,
    # "ChainSync.Remote.Send.RequestNext":
    # "NodeState.NodeAddBlock": NodeAddBlockEvent,
}


def parse_log_message(log_message: Mapping[str, Any]) -> Any:
    """Parse a log message JSON into the appropriate event model.

    The EVENT_REGISTRY dictionary provides a mapping of event namespaces
    to pydantic models. The code below first retrieves the namespace from the
    incoming (base) event. It then tries to get that namespaces entry from the
    registry and returns and instance of the model configured or returns the
    base event created in the beginning.
    """

    base_event = BaseBlockEvent(**log_message)
    namespace = base_event.namespace

    if event_class := EVENT_REGISTRY.get(namespace):
        return event_class(**log_message)

    # No event class found for namespace
    return base_event


def parse_connectionid(connectionid: str) -> Connection:
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
