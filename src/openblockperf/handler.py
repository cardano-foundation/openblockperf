from functools import singledispatchmethod

from pydantic import ValidationError

from openblockperf.amaru import AmaruPeerBridge, is_amaru_message, parse_amaru_peer_action
from openblockperf.apiclient import BlockperfApiClient
from openblockperf.blocksamplegroup import BlockSampleGroup
from openblockperf.config import AppSettings
from openblockperf.errors import EventError, InvalidEventDataError, UnknowEventNameSpaceError
from openblockperf.logging import logger
from openblockperf.models.events import (
    PEER_SELECTION_DONE_NAMESPACES,
    AddedToCurrentChainEvent,
    BlockSampleEvent,
    CompletedBlockFetchEvent,
    ConnectionLostEvent,
    DemotedPeerEvent,
    DownloadedHeaderEvent,
    HandshakeSuccessEvent,
    InboundGovernorCountersEvent,
    NetworkShutdownEvent,
    NodeEpochStartEvent,
    PeerEvent,
    PeerSelectionDoneEvent,
    PromotedPeerEvent,
    SendFetchRequestEvent,
    StatusChangedEvent,
    SwitchedToAForkEvent,
)
from openblockperf.models.peer import Peer
from openblockperf.peer_audit import PeerAuditLog
from openblockperf.peer_relevance import PeerRelevanceTracker
from openblockperf.peer_tracker import PeerReport, PeerTracker

# ---------------------------------------------------------------------------
# How dispatch works in this class
# ---------------------------------------------------------------------------
# There are TWO levels of singledispatch:
#
#   Level 1 — dispatch_event(event)
#       Routes by top-level event type:
#           BlockSampleEvent             → _on_block_sample_event
#           PeerEvent                    → _on_peer_event
#           HandshakeSuccessEvent        → _on_handshake_success (opens session)
#           NetworkShutdownEvent         → _on_network_shutdown (close all)
#           NodeEpochStartEvent          → _on_node_epoch_start
#
#   Level 2 — dispatch_peer_event(peer, event)
#       Called from _on_peer_event after session state is updated.
#
# Peer API submits come from the session store (open / temperature / close / node_restart).
# ---------------------------------------------------------------------------


class EventHandler:
    """Routes incoming log messages to typed async event handlers via singledispatch."""

    # Maps cardano-node log namespace strings to their Pydantic event models.
    # _make_event_from_message() uses this to parse raw dicts into typed events.
    REGISTERED_NAMESPACES: dict[str, type] = {
        "BlockFetch.Client.CompletedBlockFetch": CompletedBlockFetchEvent,
        "BlockFetch.Client.SendFetchRequest": SendFetchRequestEvent,
        "ChainDB.AddBlockEvent.AddedToCurrentChain": AddedToCurrentChainEvent,
        "ChainDB.AddBlockEvent.SwitchedToAFork": SwitchedToAForkEvent,
        "ChainSync.Client.DownloadedHeader": DownloadedHeaderEvent,
        "Net.ConnectionManager.Remote.ConnectionHandler.Error": ConnectionLostEvent,
        "Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess": HandshakeSuccessEvent,
        "Net.ConnectionManager.Remote.Shutdown": NetworkShutdownEvent,
        "Net.InboundGovernor.Remote.MuxErrored": ConnectionLostEvent,
        "Net.InboundGovernor.Remote.PromotedToHotRemote": PromotedPeerEvent,
        "Net.InboundGovernor.Remote.PromotedToWarmRemote": PromotedPeerEvent,
        "Net.InboundGovernor.Remote.DemotedToColdRemote": DemotedPeerEvent,
        "Net.InboundGovernor.Remote.DemotedToWarmRemote": DemotedPeerEvent,
        "Net.InboundGovernor.Remote.InboundGovernorCounters": InboundGovernorCountersEvent,
        "Net.InboundGovernor.Remote.ResponderErrored": ConnectionLostEvent,
        "Net.PeerSelection.Actions.StatusChanged": StatusChangedEvent,
        **dict.fromkeys(PEER_SELECTION_DONE_NAMESPACES, PeerSelectionDoneEvent),
        "Net.Server.Remote.Stopped": NetworkShutdownEvent,
        "Net.Server.Local.Stopped": NetworkShutdownEvent,
        "Net.Server.Remote.Started": NodeEpochStartEvent,
        "Net.Server.Local.Started": NodeEpochStartEvent,
        "Startup.DiffusionInit": NodeEpochStartEvent,
    }

    block_sample_groups: dict[str, BlockSampleGroup]
    peers: dict[str, Peer]
    api: BlockperfApiClient
    peer_tracker: PeerTracker
    peer_relevance: PeerRelevanceTracker

    def __init__(
        self,
        block_sample_groups: dict[str, BlockSampleGroup],
        peers: dict[str, Peer],
        api: BlockperfApiClient,
        settings: AppSettings,
    ):
        super().__init__()
        self.block_sample_groups = block_sample_groups
        self.peers = peers
        self.api = api
        self.settings = settings
        self.peer_tracker = PeerTracker(
            peers,
            stable_seconds=settings.peer_event_stable_seconds,
            signal_ttl_seconds=settings.peer_signal_ttl_seconds,
            traceroute_enabled=settings.peer_traceroute_enabled,
        )
        self.peer_relevance = PeerRelevanceTracker()
        self.peer_audit: PeerAuditLog | None = None
        if settings.peer_audit_log_file is not None:
            self.peer_audit = PeerAuditLog(settings.peer_audit_log_file)
        self.amaru_bridge = AmaruPeerBridge(
            self.peer_tracker,
            default_local_addr=settings.local_addr,
            default_local_port=int(settings.local_port),
        )

    def close_peer_audit(self) -> None:
        if self.peer_audit is not None:
            self.peer_audit.close()
            self.peer_audit = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def handle_message(self, raw_message: dict):
        """Parse a raw log dict and dispatch it to the appropriate handler."""
        kind = self.settings.node_kind
        amaru = is_amaru_message(raw_message)

        if kind == "haskell" and amaru:
            raise UnknowEventNameSpaceError()
        if kind == "amaru" and not amaru:
            raise UnknowEventNameSpaceError()
        if kind == "amaru" or (kind == "auto" and amaru):
            return await self._handle_amaru_message(raw_message)

        event = self._make_event_from_message(raw_message)
        self._audit_parse(event)
        return await self.dispatch_event(event)

    async def _handle_amaru_message(self, raw_message: dict):
        """Amaru peer-session path (v0). Blocksamples not parsed yet."""
        action = parse_amaru_peer_action(raw_message)
        if action is None:
            raise UnknowEventNameSpaceError()
        reports = self.amaru_bridge.apply_action(action)
        if self.peer_audit is not None:
            self.peer_audit.parse(
                at=action.at,
                ns=action.ns,
                event_type="AmaruPeer",
                local_addr=self.amaru_bridge.listen_addr,
                local_port=self.amaru_bridge.listen_port,
                remote_addr=action.remote_addr,
                remote_port=action.remote_port,
                note=action.kind.value,
            )
        for report in reports:
            await self._submit_report(report)
        return len(reports)

    async def flush_peer_reports(self) -> int:
        """Mark useful sessions, TTL-close stale ones, prune idle. Returns submit count."""
        reports = self.peer_tracker.flush_stable()
        reports.extend(self.peer_tracker.expire_stale())
        for report in reports:
            await self._submit_report(report)
        pruned = self.peer_tracker.prune_cold(self.settings.peer_prune_idle_seconds)
        if pruned:
            logger.debug("Pruned idle cold peers", count=pruned)
        if self.peer_audit is not None:
            self.peer_audit.counts(self.peer_tracker, reason="flush")
        return len(reports)

    def _audit_parse(self, event) -> None:
        if self.peer_audit is None:
            return
        if isinstance(
            event,
            (
                PeerEvent,
                HandshakeSuccessEvent,
                NetworkShutdownEvent,
                NodeEpochStartEvent,
            ),
        ):
            extra: dict = {}
            if isinstance(event, HandshakeSuccessEvent):
                extra = {
                    "n2n_version": event.n2n_version,
                    "diffusion_mode": event.diffusion_mode,
                    "peer_sharing": event.peer_sharing,
                    "peras_support": event.peras_support,
                }
            elif isinstance(event, PeerEvent):
                extra = {
                    "state": event.state if isinstance(event.state, str) else getattr(event.state, "value", event.state),
                    "direction": event.direction.value
                    if hasattr(event.direction, "value")
                    else str(event.direction),
                    "change_type": event.change_type.value
                    if hasattr(event.change_type, "value")
                    else str(event.change_type),
                }
            self.peer_audit.parse(
                at=event.at,
                ns=getattr(event, "ns", None) or "",
                event_type=type(event).__name__,
                local_addr=getattr(event, "local_addr", None),
                local_port=getattr(event, "local_port", None),
                remote_addr=getattr(event, "remote_addr", None),
                remote_port=getattr(event, "remote_port", None),
                **extra,
            )
        elif isinstance(event, (DownloadedHeaderEvent, SendFetchRequestEvent, CompletedBlockFetchEvent)):
            self.peer_audit.parse(
                at=event.at,
                ns=event.ns,
                event_type=type(event).__name__,
                local_addr=event.local_addr,
                local_port=event.local_port,
                remote_addr=event.remote_addr,
                remote_port=event.remote_port,
                note="outbound_client_mini_protocol",
            )

    # ------------------------------------------------------------------
    # Internal: parsing
    # ------------------------------------------------------------------

    def _make_event_from_message(
        self, message: dict
    ) -> (
        BlockSampleEvent
        | PeerEvent
        | HandshakeSuccessEvent
        | InboundGovernorCountersEvent
        | NetworkShutdownEvent
        | NodeEpochStartEvent
    ):
        """Validate a raw log message dict into a typed Pydantic event model."""
        ns = message.get("ns")
        if ns not in self.REGISTERED_NAMESPACES:
            raise UnknowEventNameSpaceError()
        event_model_class = self.REGISTERED_NAMESPACES[ns]
        try:
            return event_model_class.model_validate(message)
        except ValidationError as e:
            raise InvalidEventDataError(ns, event_model_class, message) from e

    # ------------------------------------------------------------------
    # Level 1 dispatch — routes by top-level event type
    # ------------------------------------------------------------------

    @singledispatchmethod
    async def dispatch_event(self, event) -> int | None:
        """Fallback: raises if an unregistered event type reaches the dispatcher."""
        raise EventError(f"Unhandled event type: {type(event).__name__}")

    @dispatch_event.register
    async def _on_block_sample_event(self, event: BlockSampleEvent):
        """Add a block-related event to the BlockSampleGroup for its block_hash."""
        logger.debug(
            "BlockEvent",
            event_type=type(event).__name__,
            ns=getattr(event, "ns", None),
            block_hash=getattr(event, "block_hash", None),
        )
        if not hasattr(event, "block_hash"):
            raise EventError("Block event has no block_hash.")
        block_hash = event.block_hash
        if block_hash not in self.block_sample_groups:
            self.block_sample_groups[block_hash] = BlockSampleGroup(
                block_hash=block_hash,
                settings=self.settings,
            )
        group = self.block_sample_groups[block_hash]
        before_headers = list(group.header_announcer_ips)
        body_before = group.body_relevance_recorded
        group.add_event(event)

        if isinstance(event, DownloadedHeaderEvent):
            await self._note_outbound_client(event)
            if event.remote_addr not in before_headers and event.remote_addr in group.header_announcer_ips:
                rank = group.header_announcer_rank(event.remote_addr)
                if rank is not None:
                    self.peer_relevance.record_header(event.remote_addr, rank, event.at)
                    score = self.peer_relevance.score_for(event.remote_addr, now=event.at)
                    count_by_rank = {
                        1: score.headers_1st_count,
                        2: score.headers_2nd_count,
                        3: score.headers_3rd_count,
                    }
                    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(rank, f"{rank}th")
                    logger.opt(raw=True).info(
                        f"new header announced {ordinal} from {event.remote_addr} "
                        f"{count_by_rank.get(rank, 0)}\n"
                    )
        elif isinstance(event, SendFetchRequestEvent):
            await self._note_outbound_client(event)
        elif isinstance(event, CompletedBlockFetchEvent):
            await self._note_outbound_client(event)
            if not body_before and group.block_completed is event:
                group.body_relevance_recorded = True
                self.peer_relevance.record_body(event.remote_addr, event.at)
                score = self.peer_relevance.score_for(event.remote_addr, now=event.at)
                logger.opt(raw=True).info(
                    f"new body served by {event.remote_addr} {score.bodies_count}\n"
                )

    async def _note_outbound_client(self, event) -> None:
        """ChainSync/BlockFetch client lines mean we dialed and this session is Hot."""
        if not self.peer_tracker.enabled():
            return
        reports = self.peer_tracker.note_outbound_client(
            local_addr=event.local_addr,
            local_port=event.local_port,
            remote_addr=event.remote_addr,
            remote_port=event.remote_port,
            at=event.at,
            ns=event.ns,
        )
        for report in reports:
            await self._submit_report(report)

    @dispatch_event.register
    async def _on_peer_event(self, event: PeerEvent):
        """Update peer state via PeerTracker, then run subtype logging hooks."""
        if not self.peer_tracker.enabled():
            return

        reports = self.peer_tracker.apply_event(event)
        for report in reports:
            await self._submit_report(report)

        peer = self.peers.get(event.key)
        if peer is not None:
            logger.debug(
                f"Dispatching peer event, runtime type: {type(event).__name__}, ns: {event.ns}",
                event=event,
            )
            await self.dispatch_peer_event(event, peer)

    async def _submit_report(self, report: PeerReport) -> None:
        if not report.change_type.is_reportable():
            return
        if self.peer_audit is not None:
            self.peer_audit.submit(report)
        reason = report.close_reason.value if report.close_reason else "-"
        logger.opt(raw=True).info(
            f"{report.peer.remote_addr} {report.event_role.value} "
            f"{report.change_type.value} {report.direction.value} "
            f"gen={report.node_generation} session={report.session_id or '-'} "
            f"reason={reason} we_dialed={report.we_dialed} "
            f"v={report.peer.n2n_version} share={report.peer.peer_sharing} "
            f"peras={report.peer.peras_support}\n"
        )
        await self.api.submit_peer_report(
            peer=report.peer,
            at=report.at,
            direction=report.direction.value,
            change_type=report.change_type.value,
            last_state=report.state,
            remote_port=report.remote_port,
            node_generation=report.node_generation,
            session_id=report.session_id,
            close_reason=report.close_reason.value if report.close_reason else None,
            we_dialed=report.we_dialed,
            event_role=report.event_role.value,
        )

    @dispatch_event.register
    async def _on_inbound_governor_counters(self, event: InboundGovernorCountersEvent):
        logger.debug("InboundGovernorCountersEvent", event=event)

    @dispatch_event.register
    async def _on_handshake_success(self, event: HandshakeSuccessEvent):
        """Open a connection session and cache n2n options."""
        reports = self.peer_tracker.open_handshake(
            local_addr=event.local_addr,
            local_port=event.local_port,
            remote_addr=event.remote_addr,
            remote_port=event.remote_port,
            n2n_version=event.n2n_version,
            diffusion_mode=event.diffusion_mode,
            peer_sharing=event.peer_sharing,
            peras_support=event.peras_support,
            at=event.at,
            ns=event.ns,
        )
        logger.opt(raw=True).info(
            f"handshake {event.remote_addr} port={event.remote_port} "
            f"v={event.n2n_version} mode={event.diffusion_mode} "
            f"share={event.peer_sharing} peras={event.peras_support}\n"
        )
        if not reports and self.peer_audit is not None:
            existing = self.peer_tracker._find_open(
                event.local_addr, event.local_port, event.remote_addr, event.remote_port
            )
            self.peer_audit.enrich(
                at=event.at,
                session_id=existing.session_id if existing else None,
                remote_addr=event.remote_addr,
                remote_port=event.remote_port,
                n2n_version=event.n2n_version,
                diffusion_mode=event.diffusion_mode,
                peer_sharing=event.peer_sharing,
                peras_support=event.peras_support,
            )
        for report in reports:
            await self._submit_report(report)

    @dispatch_event.register
    async def _on_network_shutdown(self, event: NetworkShutdownEvent):
        """Node CM/server stopped; close open sessions with node_restart."""
        reports = self.peer_tracker.on_network_stop(event.at, ns=event.ns)
        logger.opt(raw=True).info(
            f"network shutdown {event.ns} closed_sessions={len(reports)}\n"
        )
        for report in reports:
            await self._submit_report(report)

    @dispatch_event.register
    async def _on_node_epoch_start(self, event: NodeEpochStartEvent):
        """Server started from empty. New node generation after closing leftovers."""
        reports = self.peer_tracker.on_network_start(event.at, ns=event.ns)
        logger.opt(raw=True).info(
            f"node generation {event.ns} node_generation={self.peer_tracker.node_generation} "
            f"reports={len(reports)}\n"
        )
        for report in reports:
            await self._submit_report(report)

    # ------------------------------------------------------------------
    # Level 2 dispatch — subtype hooks after tracker update (no direct submit)
    # ------------------------------------------------------------------

    @singledispatchmethod
    async def dispatch_peer_event(self, event: PeerEvent, peer: Peer):
        """Fallback: logs a warning for unregistered PeerEvent subtypes."""
        logger.warning(f"No specific handler for peer event type {type(event).__name__}")

    @dispatch_peer_event.register
    async def _on_peer_status_changed(self, event: StatusChangedEvent, peer: Peer):
        logger.debug("Peer status changed", event=event, peer=peer)

    @dispatch_peer_event.register
    async def _on_peer_selection_done(self, event: PeerSelectionDoneEvent, peer: Peer):
        logger.debug("Peer selection done", event=event, peer=peer)

    @dispatch_peer_event.register
    async def _on_peer_promoted(self, event: PromotedPeerEvent, peer: Peer):
        logger.debug("Peer promoted", event=event, peer=peer)

    @dispatch_peer_event.register
    async def _on_peer_demoted(self, event: DemotedPeerEvent, peer: Peer):
        logger.debug("Peer demoted", event=event, peer=peer)

    @dispatch_peer_event.register
    async def _on_connection_lost(self, event: ConnectionLostEvent, peer: Peer):
        logger.debug("Peer connection lost", event=event, peer=peer)
