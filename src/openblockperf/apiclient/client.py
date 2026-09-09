import httpx
import rich

from openblockperf import __version__
from openblockperf.config import AppSettings
from openblockperf.discovery import EndpointPool
from openblockperf.ip_obfuscate import obfuscate_ip
from openblockperf.logging import logger
from openblockperf.models.events import PeerEvent
from openblockperf.models.peer import Peer
from openblockperf.models.samples import BlockSample

from .base import BlockperfApiBase
from .models import (
    BlockSampleRequest,
    BlockSampleResponse,
    ClientInfoRequest,
    IpProofResponse,
    IpRegistrationRequest,
    IpRegistrationResponse,
    PeerEventRequest,
    RegistrationChallengeRequest,
    RegistrationChallengeResponse,
    SubmitSignedChallengeRequest,
    SubmitSignedChallengeResponse,
)


class BlockperfApiClient:
    def __init__(self, settings: AppSettings, *, service_mode: bool = False):
        self.settings = settings
        self.pool = EndpointPool(settings, service_mode=service_mode)
        self._api = BlockperfApiBase(
            pool=self.pool,
            api_key=settings.api_key,
            hostname=settings.node_name,
            timeout=settings.api_request_timeout_ms / 1000.0,
            retries=settings.api_request_retries,
        )

    def _obfuscate(self, addr: str | None) -> str:
        return obfuscate_ip(addr, self.settings.obfuscate_ips)

    @property
    def current_api_url(self) -> str | None:
        current = self.pool.current
        return current.base_url if current else None

    async def prepare(self) -> str:
        endpoint = await self.pool.ensure_ready()
        return endpoint.base_url

    async def refresh_endpoints(self) -> str:
        endpoint = await self.pool.refresh()
        await self._api.rebuild_client()
        return endpoint.base_url

    async def close(self) -> None:
        await self._api.close()

    async def submit_block_sample(self, sample: BlockSample) -> BlockSampleResponse:
        payload = sample.model_dump()
        payload["header_remote_addr"] = self._obfuscate(payload.get("header_remote_addr"))
        payload["block_remote_addr"] = self._obfuscate(payload.get("block_remote_addr"))
        payload["local_addr"] = self._obfuscate(payload.get("local_addr"))
        bsr = BlockSampleRequest(**payload)
        logger.debug("Sending BlockSample", block_hash=sample.block_hash, slot=sample.slot)
        return await self._api.post("/submit/blocksample", bsr, BlockSampleResponse)

    async def post_status_change(self):
        return await self._api.post("/submit/peerstatuschange")

    async def request_registration_challenge(
        self, pool_id_bech32: str | None = None, calidus_key_id: str | None = None
    ) -> str:
        """"""
        rcr = RegistrationChallengeRequest(pool_id_bech32=pool_id_bech32)
        logger.debug("Sending registration request", request=rcr)
        response = await self._api.post("/registration/calidus/challenge", rcr, RegistrationChallengeResponse)
        return response.challenge

    async def request_ip_proof(self, family: str) -> IpProofResponse:
        """Prove this host's public IP for one address family.

        Forces AF_INET (``v4``) or AF_INET6 (``v6``) via the local bind address so
        E records the source IP it actually sees. Uses the same selected edge and
        ``X-Hostname`` as later ``/registration/ip``.
        """
        if family not in ("v4", "v6"):
            raise ValueError("family must be 'v4' or 'v6'")
        endpoint = await self.pool.ensure_ready()
        local_address = "0.0.0.0" if family == "v4" else "::"
        hostname = self.settings.node_name or ""
        transport = httpx.AsyncHTTPTransport(local_address=local_address)
        headers = {
            "X-Hostname": hostname,
            "X-Api-Key": "",
        }
        async with httpx.AsyncClient(
            base_url=endpoint.base_url,
            timeout=httpx.Timeout(self._api.timeout),
            transport=transport,
            headers=headers,
        ) as client:
            response = await client.post("registration/ip/proof")
            response.raise_for_status()
            return IpProofResponse.model_validate(response.json())

    async def collect_ip_proofs(self) -> dict[str, IpProofResponse]:
        """Try IPv4 and IPv6 proofs. Returns only families that succeeded."""
        proofs: dict[str, IpProofResponse] = {}
        for family in ("v4", "v6"):
            try:
                proof = await self.request_ip_proof(family)
                proofs[family] = proof
                logger.info("IP proof accepted", family=family, ip=proof.ip)
            except Exception as exc:
                logger.warning("IP proof unavailable", family=family, error=repr(exc))
        return proofs

    async def clientip_registration(
        self,
        force: bool,
        update_ip: bool,
        proof_tokens: list[str] | None = None,
    ) -> IpRegistrationResponse | None:
        """Register (or update) an ApiKey using IP proofs or legacy single-stack.

        Args:
            force: Issue a new ApiKey (invalidates the previous one for this host).
            update_ip: Replace all IP bindings on an existing ApiKey with the proven set.
            proof_tokens: Tokens from ``/registration/ip/proof``. Empty/None uses legacy
                registration that binds only the request source IP.
        """
        headers = {"X-Force-Renewal": str(force), "X-Update-Ip": str(update_ip)}
        body: IpRegistrationRequest | None
        if proof_tokens:
            body = IpRegistrationRequest(proof_tokens=proof_tokens)
        else:
            # Legacy: no body (backend binds the single observed source IP).
            body = None
        response = await self._api.post("/registration/ip", body, IpRegistrationResponse, headers=headers)
        return response

    async def register_ip(
        self,
        *,
        force: bool = False,
        update_ip: bool = False,
    ) -> tuple[IpRegistrationResponse | None, dict[str, IpProofResponse], bool]:
        """Dual-stack register: collect proofs, then submit them.

        Returns ``(response, proofs, used_legacy)``. If no proof succeeds, falls back
        to legacy ``/registration/ip`` without tokens.
        """
        proofs = await self.collect_ip_proofs()
        tokens = [proofs[family].token for family in ("v4", "v6") if family in proofs]
        if not tokens:
            logger.warning(
                "No IP proofs collected; falling back to legacy single-stack registration"
            )
            response = await self.clientip_registration(force, update_ip, proof_tokens=None)
            return response, proofs, True
        if len(tokens) < 2:
            logger.warning(
                "Only one address family proved; the other family may get 401 until "
                "update-ip is run with both proofs"
            )
        response = await self.clientip_registration(force, update_ip, proof_tokens=tokens)
        return response, proofs, False

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
            local_addr=self._obfuscate(peer.local_addr),
            local_port=peer.local_port,
            remote_addr=self._obfuscate(peer.remote_addr),
            remote_port=peer.remote_port,
            change_type=event.change_type.value,
            last_seen=event.at.isoformat(),
            last_state=event.state,
        )
        logger.debug("Sending PeerEvent", request=per)
        await self._api.post("/submit/peerevent", per)

    async def send_clientinfo(self, node_version: str):
        info_request = ClientInfoRequest(node_version=node_version, client_version=str(__version__))
        logger.debug(
            "Sending Clientinfo",
            node_version=info_request.node_version,
            client_version=info_request.client_version,
        )
        await self._api.post("/submit/clientinfo", info_request)

    async def test_api_key(self):
        resp = await self._api.get("/auth/private")
        rich.print("Response:", resp)
