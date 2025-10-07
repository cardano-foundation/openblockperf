from pydantic import BaseModel, Field

from blockperf.models.peer import Peer


class BlockSample(BaseModel):
    host: str = Field(..., description="Hostname of client")
    block_hash: str = Field(..., description="Block hash")
    block_number: int = Field(..., description="Block number")
    block_size: int = Field(..., description="Block size")
    block_g: float = Field(..., description="Block G value")
    slot: int = Field(..., description="Slot number")
    slot_time: str = Field(..., description="ISO 8601 datetime string")
    header_remote_addr: str = Field(..., description="Header remote address")
    header_remote_port: int = Field(..., description="Header remote port")
    header_delta: int = Field(..., description="Header delta")
    block_remote_addr: str = Field(..., description="Block remote address")
    block_remote_port: int = Field(..., description="Block remote port")
    block_request_delta: int = Field(..., description="Block request delta")
    block_response_delta: int = Field(..., description="Block response delta")
    block_adopt_delta: int = Field(..., description="Block adopt delta")
    local_addr: str = Field(..., description="Address of node")
    local_port: int = Field(..., description="Port of node")
    magic: int = Field(..., description="network magic")
    client_version: str = Field(..., description="client version")


class PeerSample(BaseModel):
    peers: list[Peer]
