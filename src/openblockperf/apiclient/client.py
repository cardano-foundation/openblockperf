import rich
import httpx

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
    PeerEventRequest,
    RegistrationChallengeRequest,
    RegistrationChallengeResponse,
    RelayIpProbeRequest,
    RelayIpProbeResponse,
    RelayIpSubmitRequest,
    RelayIpSubmitResponse,
    SubmitSignedChallengeRequest,
    SubmitSignedChallengeResponse,
)


class BlockperfApiClient:
    def __init__(self, settings: AppSettings):
        self._api = BlockperfApiBase(
            full_api_url=settings.full_api_url, client_id=settings.api_clientid, api_key=settings.api_key
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
        response = await self._api.post("/registration/challenge", rcr, RegistrationChallengeResponse)
        return response.challenge

    async def request_relay_ip_probe(self, family: str) -> RelayIpProbeResponse:
        if family not in ("v4", "v6"):
            raise ValueError("family must be 'v4' or 'v6'")
        local_address = "0.0.0.0" if family == "v4" else "::"
        probe_api = BlockperfApiBase(
            full_api_url=self._api.full_api_url,
            client_id=self._api.clientid,
            api_key=self._api.api_key,
            transport=httpx.AsyncHTTPTransport(local_address=local_address),
        )
        request = RelayIpProbeRequest(family=family)
        try:
            return await probe_api.post("/registration/relayip/probe", request, RelayIpProbeResponse)
        finally:
            await probe_api.close()

    async def submit_relay_ip_registration(
        self,
        cookie_v4: str | None = None,
        cookie_v6: str | None = None,
    ) -> RelayIpSubmitResponse:
        request = RelayIpSubmitRequest(cookie_v4=cookie_v4, cookie_v6=cookie_v6)
        return await self._api.post("/registration/relayip/submit", request, RelayIpSubmitResponse)

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
