from datetime import datetime

from pydantic import BaseModel

from openblockperf.models.samples import BlockSample


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


class ClientInfoRequest(BaseModel):
    hostname: str
    node_version: str
    client_version: str


class RelayIpProbeRequest(BaseModel):
    family: str  # v4 | v6


class RelayIpProbeResponse(BaseModel):
    cookie: str
    family: str
    detected_ip: str | None = None


class RelayIpSubmitRequest(BaseModel):
    cookie_v4: str | None = None
    cookie_v6: str | None = None


class RelayIpSubmitResponse(BaseModel):
    apikey: str
