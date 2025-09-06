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
    ns: str
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
        # return ".".join(self.ns)
        return self.ns


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


def parse_log_message(log_message: Mapping[str, Any]) -> BaseLogEvent:
    """Parse a log message JSON into the appropriate Pydantic event model."""

    # First, validate it as a basic log event
    base_event = BaseLogEvent(**log_message)

    # Get the namespace path
    ns_path = base_event.namespace_path
    event = None

    print(ns_path)

    # Determine the specific event type based on namespaces
    if "Reflection.TracerInfo" in ns_path:
        event = TracerInfoEvent(**log_message)
    elif "ChainDB.OpenEvent" in ns_path:
        event = ChainDBOpenEvent(**log_message)
    elif "ChainDB.AddBlockEvent.AddBlockValidation.ValidCandidate" in ns_path:
        event = BlockValidationEvent(**log_message)
    elif "ChainDB.AddBlockEvent.AddedToCurrentChain" in ns_path:
        event = AddedToCurrentChainEvent(**log_message)
    elif "Net.PeerSelection" in ns_path:
        event = PeerSelectionEvent(**log_message)
    elif "Net.PeerSelection.Actions.ConnectionError" in ns_path:
        event = ConnectionErrorEvent(**log_message)

    if not event:
        print(f"Error: could not determine event {log_message}")

    return event or base_event
