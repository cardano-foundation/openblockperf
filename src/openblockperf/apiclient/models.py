from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

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
    node_version: str
    client_version: str


class IpRegistrationResponseStatus(StrEnum):
    ALREADY_REGISTERED = "already_registered"
    FORCE_RENEWAL = "force_renewal"
    UPDATE_IP = "update_ip"
    REGISTERED = "registered"
    ERROR = "error"


class IpProofResponse(BaseModel):
    """Short-lived proof that E observed this client's source IP for X-Hostname."""

    token: str
    ip: str | None = None
    hostname: str | None = None
    expires_at: datetime | str | None = None


class IpRegistrationRequest(BaseModel):
    """Body for POST /registration/ip. Empty proof_tokens is legacy single-stack."""

    proof_tokens: list[str] = Field(default_factory=list)


class IpRegistrationResponse(BaseModel):
    status: IpRegistrationResponseStatus
    msg: str | None = None
    apikey: str | None = None  # The full apikey string
    ipaddress: str | None = None  # primary / legacy single bound IP
    ipaddresses: list[str] | None = None  # all bound IPs (prefer this when present)
