"""
blockperf.models.events.base

The blockperf.models.events.base module implements the BaseEvent model
for all events from the log messages of the node.

"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from ipaddress import ip_address
from typing import Any, Dict, Optional, Union

import rich
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
    validator,
)


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

    @validator("at", pre=True)
    @classmethod
    def parse_datetime(cls, value):
        """Convert ISO format string to datetime object."""
        if not isinstance(value, str):
            raise ValidationError(f"Timestamp is not a string [{value}]")
        return datetime.fromisoformat(value)  # this is tz aware!

    def print_debug(self):
        import rich  # noqa: PLC0415

        rich.print(self)
