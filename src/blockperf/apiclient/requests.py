import enum
from datetime import datetime

from pydantic import BaseModel, Field


class PeerEventRequest(BaseModel):
    """A single Peer event Request as send to the api. Must match the
    according model from the backend.
    """

    at: datetime  # datetime from originating log message
    direction: str
    local_addr: str
    local_port: int
    remote_addr: str
    remote_port: int
    change_type: str  # Any of app.models.PeerStatusChangeType
    last_seen: datetime
    last_state: str


class PeerEventResponse(BaseModel):
    pass
