"""
logevent

The logevent module
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field, validator


class BaseLogEvent(BaseModel):
    """Base model for all log events.

    T
    """

    at: datetime
    ns: list[str]
    data: dict[str, Any]
    sev: str
    thread: str
    host: str

    @validator("at", pre=True)
    def parse_datetime(cls, value):
        """Convert ISO format string to datetime object."""
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @property
    def namespace_path(self) -> str:
        """Return the namespace path as a dot-joined string."""
        return ".".join(self.ns)


# Specific event models that all inherit from LogEvent
class TracerInfoEvent(BaseLogEvent):
    """Model for TracerInfo events."""

    pass


class ChainDBOpenEvent(BaseLogEvent):
    """Model for ChainDB.OpenEvent log entries."""

    pass


class BlockValidationEvent(BaseLogEvent):
    """Model for block validation events."""

    pass


class AddedToCurrentChainEvent(BaseLogEvent):
    """Model for events when blocks are added to the current chain."""

    pass


class PeerSelectionEvent(BaseLogEvent):
    """Model for peer selection events."""

    pass


class ConnectionErrorEvent(BaseLogEvent):
    """Model for connection error events."""

    pass


def parse_log_event(log_json: Mapping[str, Any]) -> BaseLogEvent:
    """Parse a log event JSON into the appropriate Pydantic model."""

    # First, validate it as a basic log event
    base_event = BaseLogEvent(**log_json)

    # Get the namespace path
    ns_path = base_event.namespace_path

    # Determine the specific event type based on namespaces
    if "Reflection.TracerInfo" in ns_path:
        return TracerInfoEvent(**log_json)

    elif "ChainDB.OpenEvent" in ns_path:
        return ChainDBOpenEvent(**log_json)

    elif "ChainDB.AddBlockEvent.AddBlockValidation.ValidCandidate" in ns_path:
        return BlockValidationEvent(**log_json)

    elif "ChainDB.AddBlockEvent.AddedToCurrentChain" in ns_path:
        return AddedToCurrentChainEvent(**log_json)

    elif "Net.PeerSelection" in ns_path:
        return PeerSelectionEvent(**log_json)

    elif "Net.PeerSelection.Actions.ConnectionError" in ns_path:
        return ConnectionErrorEvent(**log_json)

    # Default case - return as generic LogEvent
    return base_event
