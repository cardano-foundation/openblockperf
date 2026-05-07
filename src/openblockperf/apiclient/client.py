import rich

from openblockperf import __version__
from openblockperf.config import AppSettings
from openblockperf.logging import logger
from openblockperf.models.events import PeerEvent
from openblockperf.models.peer import Peer
from openblockperf.models.samples import BlockSample

from .base import BlockperfApiBase
from .models import (
    BlockSampleRequest,
    BlockSampleResponse,
    ClientInfoRequest,
    IpRegistrationResponse,
    PeerEventRequest,
    RegistrationChallengeRequest,
    RegistrationChallengeResponse,
    SubmitSignedChallengeRequest,
    SubmitSignedChallengeResponse,
)


class BlockperfApiClient:
    def __init__(self, settings: AppSettings):
        self._api = BlockperfApiBase(
            full_api_url=settings.full_api_url, api_key=settings.api_key, client_id=settings.client_id
        )

    async def submit_block_sample(self, sample: BlockSample) -> BlockSampleResponse:
        bsr = BlockSampleRequest(**sample.model_dump())
        logger.debug("Sending BlockSample", request=bsr)
        return await self._api.post("/submit/blocksample", bsr, BlockSampleResponse)

    async def post_status_change(self):
        return await self._api.post("/submit/peerstatuschange")

    async def request_registration_challenge(
        self, pool_id_bech32: str | None = None, calidus_key_id: str | None = None
    ) -> str:
        """ """

        rcr = RegistrationChallengeRequest(pool_id_bech32=pool_id_bech32)
        logger.debug("Sending registration request", request=rcr)
        response = await self._api.post("/registration/calidus/challenge", rcr, RegistrationChallengeResponse)
        return response.challenge

    async def clientip_registration(self) -> IpRegistrationResponse | None:
        """Register the client using the ip registration process.

        Returns:
            A Tuple that holds the client_id and the full_api_key.
        """
        response = await self._api.post("/registration/ip", {}, IpRegistrationResponse)
        return response

    async def submit_signed_challenge(
        self,
        signature_hex: str,
        pool_id_bech32: str | None = None,
    ):
        """ """
        sscr = SubmitSignedChallengeRequest(signature_hex=signature_hex, pool_id_bech32=pool_id_bech32)
        logger.debug("Sending signed challenge", request=sscr)
        return await self._api.post("/registration/submit", sscr, SubmitSignedChallengeResponse)

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
        logger.debug("Sending PeerEvent", request=per)
        await self._api.post("/submit/peerevent", per)

    async def send_clientinfo(self, hostname: str, node_version: str):
        info_request = ClientInfoRequest(hostname=hostname, node_version=node_version, client_version=str(__version__))
        logger.debug(
            "Sending Clientinfo",
            hostname=info_request.hostname,
            node_version=info_request.node_version,
            client_version=info_request.client_version,
        )
        await self._api.post("/submit/clientinfo", info_request)

    async def test_api_key(self):
        resp = await self._api.get("/auth/private")
        rich.print("Response:", resp)
