"""
blockperf.models.block

The blockperf.models.block module implements the pydantic model that represents
a "block sample event". It combines the different event types into a single
object for easier access and maintenance. While this
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

from blockperf.errors import EventError
from blockperf.models.peer import (
    PeerConnectionComplex,
    PeerConnectionSimple,
    PeerState,
    PeerStatusChange,
)
