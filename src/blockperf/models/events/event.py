"""
Block sample events

The logevent module
"""

from typing import Any

from pydantic import BaseModel, model_validator

from blockperf.errors import EventError
from blockperf.models.peer import (
    PeerConnectionSimple,
)

from .base import BaseEvent


class BlockSampleEvent(BaseEvent):
    """Any of the events relevant for taking block sample data"""

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


class StartedEvent(BaseEvent):
    pass
