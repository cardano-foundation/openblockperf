import rich

from blockperf.apiclient.requests import (
    PeerEventRequest,
    PeerEventResponse,
)
from blockperf.models.events.peer import PeerEvent
from blockperf.models.peer import Peer

from .base import BlockperfApiBase


class BlockperfApiClient(BlockperfApiBase):
    async def post_block_sample(self, sample):
        return await self.post("/submit/blocksample", sample)

    async def post_status_change(self):
        return await self.post("/submit/peerstatuschange")

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

        rich.print(
            "---\nRequest:", per.model_dump(mode="json", exclude_none=True)
        )
        resp = await self.post("/submit/peerevent", per)
        rich.print("Response:", resp)
        print()
