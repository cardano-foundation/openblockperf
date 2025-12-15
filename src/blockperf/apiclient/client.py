import rich

from blockperf.apiclient.models import (
    BlockSampleRequest,
    BlockSampleResponse,
    PeerEventRequest,
    PeerEventResponse,
    SubmitSignedChallengeRequest,
    SubmitSignedChallengeResponse,
)
from blockperf.config import AppSettings, settings
from blockperf.models.events.peer import PeerEvent
from blockperf.models.peer import Peer
from blockperf.models.samples import BlockSample

from .base import BlockperfApiBase
from .models import RegistrationChallengeRequest, RegistrationChallengeResponse


class BlockperfApiClient:
    def __init__(self, app_settings: AppSettings | None = None):
        _settings = app_settings or settings()
        self._api = BlockperfApiBase(
            full_api_url=_settings.full_api_url, client_id=_settings.api_clientid, api_key=_settings.api_key
        )

    async def submit_block_sample(self, sample: BlockSample) -> BlockSampleResponse:
        request = BlockSampleRequest(**sample.model_dump())
        return await self._api.post("/submit/blocksample", request, BlockSampleResponse)

    async def post_status_change(self):
        return await self._api.post("/submit/peerstatuschange")

    async def request_registration_challenge(
        self, pool_id_bech32: str | None = None, calidus_key_id: str | None = None
    ) -> str:
        """ """

        request = RegistrationChallengeRequest(pool_id_bech32=pool_id_bech32)
        response = await self._api.post("/registration/challenge", request, RegistrationChallengeResponse)
        rich.print(response)
        return response.challenge

    async def submit_signed_challenge(
        self,
        signature_hex: str,
        pool_id_bech32: str | None = None,
    ):
        """ """
        print("Sending signed challenge back")
        request = SubmitSignedChallengeRequest(signature_hex=signature_hex, pool_id_bech32=pool_id_bech32)
        rich.print(request)
        return await self._api.post("/registration/submit", request, SubmitSignedChallengeResponse)

    async def submit_peer_event(self, peer: Peer, event: PeerEvent):
        """Creates the request to submit a peer event.

        Needs to create the 'PeerEventRequest' form the backend.
        """

        per = PeerEventRequest(
            at=event.at,
            direction=event.direction,
            local_addr=peer.local_addr,
            local_port=peer.local_port,
            remote_addr=peer.remote_addr,
            remote_port=peer.remote_port,
            change_type=event.change_type.value,
            last_seen=event.at.isoformat(),
            last_state=event.state,
        )

        rich.print("---\nRequest:", per.model_dump(mode="json", exclude_none=True))
        resp = await self._api.post("/submit/peerevent", per)
        rich.print("Response:", resp)
        print()

    async def test_api_key(self):
        resp = await self._api.get("/auth/private")
        rich.print("Response:", resp)
