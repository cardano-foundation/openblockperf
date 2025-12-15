import enum
from datetime import datetime

from pydantic import BaseModel, Field

from blockperf.models.samples import BlockSample


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


class BlockSampleRequest(BlockSample):
    pass


class BlockSampleResponse(BaseModel):
    pass


class RegistrationChallengeRequest(BaseModel):
    pool_id_bech32: str


class RegistrationChallengeResponse(BaseModel):
    challenge: str


class SubmitSignedChallengeRequest(BaseModel):
    pool_id_bech32: str
    signature_hex: str


class SubmitSignedChallengeResponse(BaseModel):
    apikey: str
