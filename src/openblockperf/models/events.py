"""

Implements the BaseEvent model for all events from the log messages of the node.

"""

import enum
import re
from datetime import datetime
from ipaddress import ip_address
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
    model_validator,
)

from openblockperf.errors import EventError
from openblockperf.logging import logger
from openblockperf.models.peer import PeerConnectionSimple

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


class BaseEvent(BaseModel):
    """Base model for all block events that will be produced by the log reader.

    The below fields are what i think every message will always have. The
    sec and thread fields are not of interested for now, so i did not include
    them.
    """

    model_config = ConfigDict(populate_by_name=True)
    at: datetime
    ns: str
    data: dict[str, Any]
    # sev: str
    # thread: str
    host: str

    @field_validator("at", mode="before")
    @classmethod
    def parse_datetime(cls, value):
        """Convert ISO format string to datetime object."""
        if not isinstance(value, str):
            raise ValueError(f"Timestamp is not a string [{value}]")
        return datetime.fromisoformat(value)  # this is tz aware!

    def print_debug(self):
        import rich  # noqa: PLC0415

        rich.print(self)

    def __repr__(self):
        return f"BaseEvent(at={self.at.strftime('%Y-%m-%d %H:%M:%S')}, ns={self.ns})"


class BlockSampleEvent(BaseEvent):
    """Base Class for all block sample events."""

    pass


class DownloadedHeaderEvent(BlockSampleEvent):
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

    class Data(BaseModel):
        block: str
        blockNo: int  # noqa
        kind: str
        peer: PeerConnectionSimple
        slot: int

    data: Data

    @property
    def block_hash(self) -> str:
        return self.data.block

    @property
    def block_number(self) -> int:
        return self.data.blockNo

    @property
    def slot(self) -> int:
        return self.data.slot

    @property
    def remote_addr(self) -> str:
        """Ip address of peer the header was downloaded from"""
        return self.data.peer.connectionId.remote_addr

    @property
    def remote_port(self) -> int:
        """Port number of peer the header was downloaded from"""
        return self.data.peer.connectionId.remote_port

    def __repr__(self):
        return f"DownloadedHeader(at={self.at.strftime('%Y-%m-%d %H:%M:%S')}, hash={self.block_hash[0:10]}, from={self.remote_addr}:{self.remote_port})"


class SendFetchRequestEvent(BlockSampleEvent):
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

    class Data(BaseModel):
        head: str
        kind: str
        length: int
        peer: PeerConnectionSimple

    data: Data

    @property
    def block_hash(self):
        """The block hash this fetch request tries to receive"""
        return self.data.head

    @property
    def remote_addr(self) -> str:
        """Ip address of peer asked to download the block from"""
        return self.data.peer.connectionId.remote_addr

    @property
    def remote_port(self) -> int:
        """Port number of peer asked to download the block from"""
        return self.data.peer.connectionId.remote_port

    def __repr__(self):
        return f"SendFetchRequest(at={self.at.strftime('%Y-%m-%d %H:%M:%S')}, hash={self.block_hash[0:10]}, from={self.remote_addr}:{self.remote_port})"


class CompletedBlockFetchEvent(BlockSampleEvent):
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

    class Data(BaseModel):
        block: str
        delay: float
        kind: str
        size: int
        peer: PeerConnectionSimple

    data: Data

    @property
    def block_hash(self) -> str:
        return self.data.block

    @property
    def delay(self) -> float:
        return self.data.delay

    @property
    def block_size(self) -> int:
        return self.data.size

    @property
    def remote_addr(self) -> str:
        """Ip address of peer the block was downloaded from"""
        return self.data.peer.connectionId.remote_addr

    @property
    def remote_port(self) -> int:
        """Port number of peer the block was downloaded from"""
        return self.data.peer.connectionId.remote_port

    def __repr__(self):
        return f"CompletedBlockFetch(at={self.at.strftime('%Y-%m-%d %H:%M:%S')}, hash={self.block_hash[0:10]}, from={self.remote_addr}:{self.remote_port})"


class AddedToCurrentChainEvent(BlockSampleEvent):
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
        newtip = self.data.get("newtip")
        if not newtip:
            raise EventError(f"No newtip found in {self}")
        return newtip.split("@")[0]

    def __repr__(self):
        return f"AddedToCurrentChain(at={self.at.strftime('%Y-%m-%d %H:%M:%S')}, hash={self.block_hash[0:10]})"


class SwitchedToAForkEvent(BlockSampleEvent):
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
        newtip = self.data.get("newtip")
        if not newtip:
            raise EventError(f"No newtip found in {self}")
        return newtip.split("@")[0]

    def __repr__(self):
        return f"SwitchedToAFork(at={self.at.strftime('%Y-%m-%d %H:%M:%S')}, hash={self.block_hash[0:10]})"


class StartedEvent(BaseEvent):
    pass


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
            raise ValueError(f"Unrecognized format (no 'Just' or 'ConnectionId'): {psct}")

        # Check if we actually extraced something that is an ip address
        try:
            ip_address(local_addr)
            ip_address(remote_addr)
        except ValueError as e:
            raise ValueError(f"Invalid IP address in connection string: {e}") from e

        # Assuming the StatusChange is alwasy from the local peer
        direction = "outbound"

        # Change Type
        #

        data["change_type"] = PeerEventChangeType(f"{from_state.lower()}_to_{to_state.lower()}")

        # Pack everything back into data and return
        data["state"] = to_state
        data["direction"] = direction
        data["local_addr"] = local_addr
        data["local_port"] = local_port
        data["remote_addr"] = remote_addr
        data["remote_port"] = remote_port
        return data

    @property
    def key(self):
        """Returns the key for this peer whihc is a tuple of the remote addr and port."""
        return (self.remote_addr, self.remote_port)

    def __repr__(self):
        # Shouldn't this be better be the namespace? instead of just generic PeerEvent?
        # ... well in theory this should never get called directly.
        # Instead all the PeerEvent subclasses __repr__() functions are ...
        return f"PeerEvent(at={self.at.strftime('%Y-%m-%d %H:%M:%S')}, state={self.state}, direction={self.direction}, change_type={self.change_type}, from={self.remote_addr}:{self.remote_port})"


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

    # def __str__(self):
    #    return f"<{self.__class__.__name__}, idle: {self.idle_peers}, cold: {self.cold_peers}, warm: {self.warm_peers} hot: {self.hot_peers}>"

    def __repr__(self):
        return f"InboundGovernorCounters(at={self.at.strftime('%Y-%m-%d %H:%M:%S')}, idle={self.idle_peers}, cold={self.cold_peers}, warm={self.warm_peers}, hot={self.hot_peers}>)"


class StatusChangedEvent(PeerEvent):
    """ """

    def __repr__(self):
        return f"StatusChanged(at={self.at.strftime('%Y-%m-%d %H:%M:%S')}, state={self.state}, direction={self.direction}, change_type={self.change_type}, from={self.remote_addr}:{self.remote_port})"


class PromotedPeerEvent(PeerEvent):
    """ """

    def __repr__(self):
        return f"PromotedPeer(at={self.at.strftime('%Y-%m-%d %H:%M:%S')}, state={self.state}, direction={self.direction}, change_type={self.change_type}, from={self.remote_addr}:{self.remote_port})"


class DemotedPeerEvent(PeerEvent):
    """ """

    def __repr__(self):
        return f"DemotedPeer(at={self.at.strftime('%Y-%m-%d %H:%M:%S')}, state={self.state}, direction={self.direction}, change_type={self.change_type}, from={self.remote_addr}:{self.remote_port})"
