"""
logevent

The logevent module
"""

from collections import namedtuple
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field, validator

Connection = namedtuple("Connection", "lip, lport rip rport")


class BaseLogEvent(BaseModel):
    """Base model for all log events.

    T
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
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

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


class CompletedBlockFetchEvent(BaseLogEvent):
    """
    CompletedBlockFetchEvent(
        at=datetime.datetime(2025, 9, 6, 21, 27, 23, 334299, tzinfo=datetime.timezone.utc),
        ns='BlockFetch.Client.CompletedBlockFetch',
        data={
            'block': '6e3288ea3f13757b37e0b060d13236f05bb0571f0f95d0fbd3a3a237b8eb6a6b',
            'delay': 0.33412554,
            'kind': 'CompletedBlockFetch',
            'peer': {'connectionId': '172.0.118.125:30002 24.192.179.116:5000'},
            'size': 1999
        },
        sev='Info',
        thread='1456',
        host='openblockperf-dev-database1'
    )

    """

    @property
    def block_hash(self):
        return self.data.get("block")

    @property
    def delay(self) -> float:
        return self.data.get("delay")

    @property
    def block_size(self):
        return self.data.get("size")

    @property
    def peer_ip(self) -> dict:
        """Ip address of peer the block was downloaded from"""
        connection_string = self.data.get("peer").get("connectionId")
        if not connection_string:
            return None
        connection = parse_connectionid(connection_string)
        return connection.rip


class SendFetchRequestEvent(BaseLogEvent):
    """
    SendFetchRequestEvent(
        at=datetime.datetime(2025, 9, 6, 21, 31, 54, 68449, tzinfo=datetime.timezone.utc),
        ns='BlockFetch.Client.SendFetchRequest',
        data={
            'head': '695607fd6954c3dafc255f005501fa1746d1ee6ca960a56e3cc38e3cf74e09e6',
            'kind': 'SendFetchRequest',
            'length': 1,
            'peer': {'connectionId': '172.0.118.125:30002 152.53.139.165:3001'}
        },
        sev='Info',
        thread='1537',
        host='openblockperf-dev-database1'
    )
    """

    @property
    def block_hash(self):
        """The block hash this fetch request tries to receive"""
        return self.data.get("head")


class DownloadedHeaderEvent(BaseLogEvent):
    """
    DownloadedHeaderEvent(
        at=datetime.datetime(2025, 9, 6, 21, 8, 19, 564977, tzinfo=datetime.timezone.utc),
        ns='ChainSync.Client.DownloadedHeader',
        data={
            'block': 'f825861a675f36184516f5d1eba691251fc3f58ddf0256d6df9c50e4f693795d',
            'blockNo': 3583696,
            'kind': 'DownloadedHeader',
            'peer': {'connectionId': '172.0.118.125:30002 113.43.234.98:4001'},
            'slot': 90536899
        },
        sev='Info',
        thread='1408',
        host='openblockperf-dev-database1'
    )
    """

    @property
    def block_hash(self) -> str:
        return self.data.get("block")

    @property
    def slot(self) -> int:
        return self.data.get("slot")

    @property
    def peer_ip(self) -> dict:
        """Ip address of peer the header was downloaded from"""
        connection_string = self.data.get("peer").get("connectionId")
        if not connection_string:
            return None

        connection = parse_connectionid(connection_string)
        return connection.rip


class AddedToCurrentChainEvent(BaseLogEvent):
    """
        AddedToCurrentChainEvent(
        at=datetime.datetime(2025, 9, 6, 21, 22, 1, 210917, tzinfo=datetime.timezone.utc),
        ns='ChainDB.AddBlockEvent.AddedToCurrentChain',
        data={
            'headers': [
                {
                    'blockNo': '3583723',
                    'hash': '"92fbe0b805a718e9269052a37ca38fe78cc90a7a704428ed1e008be90fbf2356"',
                    'kind': 'ShelleyBlock',
                    'slotNo': '90537721'
                }
            ],
            'kind': 'AddedToCurrentChain',
            'newTipSelectView': {
                'chainLength': 3583723,
                'issueNo': 10,
                'issuerHash': '23f86b0081f90dafb554c97da5be11a33b124018863ab7308a835587',
                'kind': 'PraosChainSelectView',
                'slotNo': 90537721,
                'tieBreakVRF':
    '4500d5375faeb22da9643a189123c392ad35cd1740acf6fb7eb778c5a68f5aaeeb3d163eb3405a33101009da46eddd8f49dba8bdea05cf8b533c
    a1bb3d66c6a8'
            },
            'newtip': '92fbe0b805a718e9269052a37ca38fe78cc90a7a704428ed1e008be90fbf2356@90537721',
            'oldTipSelectView': {
                'chainLength': 3583722,
                'issueNo': 10,
                'issuerHash': '23f86b0081f90dafb554c97da5be11a33b124018863ab7308a835587',
                'kind': 'PraosChainSelectView',
                'slotNo': 90537650,
                'tieBreakVRF':
    '1a5c97cc633afac6a99a92d584ee812588f8676ca36e7b5e4412a6d7a8e28ae293edbe8a9dd030f5060231c7dcc9a40ae273a1055304008e858b
    8e7afeacc484'
            },
            'tipBlockHash': '92fbe0b805a718e9269052a37ca38fe78cc90a7a704428ed1e008be90fbf2356',
            'tipBlockIssuerVKeyHash': '23f86b0081f90dafb554c97da5be11a33b124018863ab7308a835587',
            'tipBlockParentHash': '86ea9256c637217c6ab74388802b191d5cdd7e5d830b0e7feb67a2db93ef8cfe'
        },
        sev='Notice',
        thread='34',
        host='openblockperf-dev-database1'
    )
    """

    @property
    def block_hash(self) -> str:
        # TODO: What if there are more or less then one header?
        # TODO: Where is this qeird double quote coming from?
        _hash = self.data.get("headers")[0].get("hash")
        if _hash.startswith('"'):
            _hash = _hash[1:]
        if _hash.endswith('"'):
            _hash = _hash[:-1]
        return _hash


class SwitchedToAForkEvent(BaseLogEvent):
    @property
    def block_hash(self) -> str:
        return "NotImplemented"


"""
Added some of the events that i think are of interest. See here for more:
https://github.com/input-output-hk/cardano-node-wiki/blob/main/docs/new-tracing/tracers_doc_generated.md
"""
EVENT_REGISTRY = {
    "BlockFetch.Client.CompletedBlockFetch": CompletedBlockFetchEvent,
    "BlockFetch.Client.SendFetchRequest": SendFetchRequestEvent,
    # "BlockFetch.Remote.Receive.ClientDone": ClientDoneEvent,
    "BlockFetch.Remote.Send.Block": None,
    "ChainDB.AddBlockEvent.AddedToCurrentChain": AddedToCurrentChainEvent,
    # "ChainDB.AddBlockEvent.BlockInTheFuture": BlockInTheFutureEvent,
    "ChainDB.AddBlockEvent.SwitchedToAFork": SwitchedToAForkEvent,
    # "ChainDB.AddBlockEvent.TrySwitchToAFork": TrySwitchToAForkEvent,
    # "ChainDB.AddBlockEvent.TryAddToCurrentChain": TryAddToCurrentChainEvent,
    "ChainSync.Client.DownloadedHeader": DownloadedHeaderEvent,
    # "ChainSync.Client.RolledBack": RolledBackEvent,
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

    base_event = BaseLogEvent(**log_message)
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
