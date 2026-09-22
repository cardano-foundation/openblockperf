# Haskell cardano-node log parsing

This doc is the baseline for what OpenBlockperf currently parses from a
**Haskell cardano-node** with the new tracing system (`cardano-tracer`,
JSON `ns` + `data` lines).

We match on the JSON field `ns` (namespace). That string is the keyword.
`EventHandler.REGISTERED_NAMESPACES` in `src/openblockperf/handler.py` is
the source of truth for which namespaces become typed events.

Two main product streams:

1. **Blocksamples** – four timings per adopted block (header / request /
   response / adopt), plus announcer IPs.
2. **Peering sessions** – connection open, temperature changes, close,
   and node restart / generation.

Surrounding lifecycle lines (server start/stop, CM shutdown) are not
blocksamples; they reset peer session state.

Payload shape and deltas: [blocksample.md](blocksample.md).
Session FSM and submit roles: [peers.md](peers.md).
How we read journald vs logfile: [logreader.md](logreader.md).
Required trace options: [blockperf-traceoptions.md](blockperf-traceoptions.md).

## Decisions (2026-09-22)

1. Matching is exact `ns` equality against `REGISTERED_NAMESPACES`.
   Unknown namespaces are skipped (`UnknowEventNameSpaceError`).
2. A blocksample is keyed by **block hash**. Completeness needs four
   event kinds (header, fetch request, completed fetch, adopt).
3. Peer sessions are keyed by **connectionId** (local+remote addr/port)
   inside one node generation. See [peers.md](peers.md).
4. Replay / attach searches for
   `"ns":"Net.Server.Local.Started"` as the startup marker in the log
   source (`logreader.py`).

---

## Common log line shape

Every interesting line is one JSON object roughly like:

```json
{
  "at": "2025-09-12T16:51:39.269022269Z",
  "ns": "ChainSync.Client.DownloadedHeader",
  "data": { "...": "..." },
  "sev": "Info",
  "thread": "96913",
  "host": "relay-hostname"
}
```

We care about `at`, `ns`, and `data`. Host is used in logfile mode as
the optional content filter (`node_unit_name`).

---

## Blocksamples

### Pipeline

```
DownloadedHeader
    → (optional more headers from other peers)
SendFetchRequest
CompletedBlockFetch
AddedToCurrentChain  OR  SwitchedToAFork
    → BlockSampleGroup.is_complete() → submit
```

Events for one hash land in a `BlockSampleGroup`. When the group is
complete and older than `min_age`, the client builds a `BlockSample`
and submits it.

### Keywords (namespaces)

| `ns` | Role in sample | Key `data` fields |
|------|----------------|-------------------|
| `ChainSync.Client.DownloadedHeader` | First notice of the block (header). Earliest `at` wins for primary header fields. Also records up to 3 unique announcer IPs (processing order) for local relevance + header2/header3. | `block` (hash), `blockNo`, `slot`, `peer.connectionId` |
| `BlockFetch.Client.SendFetchRequest` | When we asked for the body. Paired to the completed fetch by same remote addr+port. | `head` (hash), `peer.connectionId` |
| `BlockFetch.Client.CompletedBlockFetch` | Body download finished. Sets block size and body peer. | `block` (hash), `size`, `delay`, `peer.connectionId` |
| `ChainDB.AddBlockEvent.AddedToCurrentChain` | Adopt on tip. Completes the sample (either this or fork switch). | `newtip` (`hash@slot`) |
| `ChainDB.AddBlockEvent.SwitchedToAFork` | Adopt via fork switch. Same completeness role as AddedToCurrentChain. | `newtip` (`hash@slot`) |

Connection id on header/fetch lines is typically a string:

```text
"localAddr:localPort remoteAddr:remotePort"
```

(see `PeerConnectionSimple` in `models/peer.py`).

### What fills a complete sample

`BlockSampleGroup.is_complete()` requires all of:

| Slot in group | Event | Sample fields driven |
|---------------|-------|----------------------|
| `block_header` | earliest `DownloadedHeader` by timestamp | `header_remote_*`, `header_delta`, `slot`, `block_number` |
| `header_announcers[1]` / `[2]` | 2nd / 3rd unique header IPs | `header2_*` / `header3_*` (optional, default empty/0) |
| `block_requested` | `SendFetchRequest` matched to completed peer | used for `block_request_delta` / `block_response_delta` |
| `block_completed` | first `CompletedBlockFetch` | `block_remote_*`, `block_size`, response/adopt deltas |
| `block_adopted` | first `AddedToCurrentChain` or `SwitchedToAFork` | `block_adopt_delta` |

Deltas (milliseconds on submit):

| Field | Meaning |
|-------|---------|
| `header_delta` | `block_header.at - slot_time` (slot_time from network starttime + slot) |
| `block_request_delta` | `block_requested.at - block_header.at` |
| `block_response_delta` | `block_completed.at - block_requested.at` |
| `block_adopt_delta` | `block_adopted.at - block_completed.at` |

`local_addr` / `local_port` / `magic` come from client settings, not from
the log line.

### Side effect on peering

`ChainSync.Client.DownloadedHeader` and `BlockFetch.Client.*` also tell
the peer tracker: we dialed that connection, outbound Hot. Same
namespaces, second consumer.

### Example sequence (one block)

1. `ChainSync.Client.DownloadedHeader` – hash H from peer A (1st announcer)
2. `ChainSync.Client.DownloadedHeader` – hash H from peer B (2nd announcer)
3. `BlockFetch.Client.SendFetchRequest` – head H to peer C
4. `BlockFetch.Client.CompletedBlockFetch` – block H from peer C, size N
5. `ChainDB.AddBlockEvent.AddedToCurrentChain` – `newtip` starts with H

After step 5 the group can submit (once age gate passes).

---

## Peering events

We do not submit every temperature line as a raw log echo. We build
**sessions**, then submit `open` / `temperature` / `close` /
`node_restart` via `POST /submit/peerevent`. Full rules: [peers.md](peers.md).

### Session open

| `ns` | Role |
|------|------|
| `Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess` | Opens session. Only source of `n2n_version`, `diffusion_mode`, `peer_sharing`, `peras_support`. |

`data` has structured `connectionId.localAddress` / `remoteAddress`
(`address` + `port`) plus `connectionHandler.agreedOptions`.

### Inbound temperature (InboundGovernor Remote)

They-dialed / inbound track on the same TCP session.

| `ns` | Resulting temperature | Change type |
|------|----------------------|-------------|
| `Net.InboundGovernor.Remote.PromotedToWarmRemote` | Warm | `cold_to_warm` |
| `Net.InboundGovernor.Remote.PromotedToHotRemote` | Hot | `warm_to_hot` |
| `Net.InboundGovernor.Remote.DemotedToWarmRemote` | Warm | `hot_to_warm` |
| `Net.InboundGovernor.Remote.DemotedToColdRemote` | Cold | `warm_to_cold` (may clear IG track only if outbound still active) |

`data.connectionId` is structured local/remote address objects.

**Do not** use `Net.InboundGovernor.Local.*` for n2n. That is n2c / unix.

### Outbound temperature (PeerSelection)

We-dialed / outbound track.

| `ns` | Role |
|------|------|
| `Net.PeerSelection.Actions.StatusChanged` | Temperature string in `data.peerStatusChangeType` (e.g. `ColdToWarm (Just …) …` or `WarmToHot (ConnectionId {…})`). Parsed with regex. Cooling transitions stay client-internal. |
| `Net.PeerSelection.Selection.PromoteColdDone` | outbound Warm (`cold_to_warm`) |
| `Net.PeerSelection.Selection.PromoteColdBigLedgerPeerDone` | same |
| `Net.PeerSelection.Selection.PromoteWarmDone` | outbound Hot (`warm_to_hot`) |
| `Net.PeerSelection.Selection.PromoteWarmBigLedgerPeerDone` | same |
| `Net.PeerSelection.Selection.DemoteHotDone` | outbound Warm (`hot_to_warm`) |
| `Net.PeerSelection.Selection.DemoteHotBigLedgerPeerDone` | same |
| `Net.PeerSelection.Selection.DemoteWarmDone` | outbound Cold (`warm_to_cold`) |
| `Net.PeerSelection.Selection.DemoteWarmBigLedgerPeerDone` | same |

Selection `*Done` payloads use `data.peer.{address,port}` (no full
connectionId). Direction is always outbound. Local addr is filled as
`0.0.0.0` / `::` with port `0` when missing.

### Abrupt connection loss (treated as leave)

| `ns` | close_reason style |
|------|--------------------|
| `Net.InboundGovernor.Remote.MuxErrored` | mux error → Cold |
| `Net.InboundGovernor.Remote.ResponderErrored` | responder error → Cold |
| `Net.ConnectionManager.Remote.ConnectionHandler.Error` | handler error → Cold; direction from `connectionHandler.context` (`OutboundError` vs inbound) |

### Counters (registered, soft)

| `ns` | Role |
|------|------|
| `Net.InboundGovernor.Remote.InboundGovernorCounters` | Parsed (`idle`/`cold`/`warm`/`hot` peers). Currently debug only, not a session driver. |

### Cross-link from blocksample namespaces

Same client fetch/header lines as above also refresh outbound Hot /
`we_dialed` on the matching open session.

---

## Node restart / generation (surrounding events)

These bracket peer sessions around a cardano-node (re)start. Not a
Cardano chain epoch.

### Shutdown (close all open sessions)

| `ns` | Effect |
|------|--------|
| `Net.Server.Remote.Stopped` | close open sessions, `close_reason=node_restart` |
| `Net.Server.Local.Stopped` | same |
| `Net.ConnectionManager.Remote.Shutdown` | same |

### Start (new node generation)

| `ns` | Effect |
|------|--------|
| `Net.Server.Remote.Started` | increment `node_generation`, submit `event_role=node_restart` |
| `Net.Server.Local.Started` | same (debounced with Remote / DiffusionInit) |
| `Startup.DiffusionInit` | optional confirm of the same start burst |

Log attach / historical replay looks for the literal substring
`"ns":"Net.Server.Local.Started"` so the client can start after the
latest node start rather than from an empty void.

---

## Full registered namespace checklist

Everything below must appear (at Info, with sensible frequency) for a
full Haskell install. Source: `EventHandler.REGISTERED_NAMESPACES`.

**Blocksample**

- `ChainSync.Client.DownloadedHeader`
- `BlockFetch.Client.SendFetchRequest`
- `BlockFetch.Client.CompletedBlockFetch`
- `ChainDB.AddBlockEvent.AddedToCurrentChain`
- `ChainDB.AddBlockEvent.SwitchedToAFork`

**Peering**

- `Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess`
- `Net.InboundGovernor.Remote.PromotedToWarmRemote`
- `Net.InboundGovernor.Remote.PromotedToHotRemote`
- `Net.InboundGovernor.Remote.DemotedToWarmRemote`
- `Net.InboundGovernor.Remote.DemotedToColdRemote`
- `Net.InboundGovernor.Remote.MuxErrored`
- `Net.InboundGovernor.Remote.ResponderErrored`
- `Net.InboundGovernor.Remote.InboundGovernorCounters`
- `Net.PeerSelection.Actions.StatusChanged`
- `Net.PeerSelection.Selection.PromoteColdDone`
- `Net.PeerSelection.Selection.PromoteColdBigLedgerPeerDone`
- `Net.PeerSelection.Selection.PromoteWarmDone`
- `Net.PeerSelection.Selection.PromoteWarmBigLedgerPeerDone`
- `Net.PeerSelection.Selection.DemoteHotDone`
- `Net.PeerSelection.Selection.DemoteHotBigLedgerPeerDone`
- `Net.PeerSelection.Selection.DemoteWarmDone`
- `Net.PeerSelection.Selection.DemoteWarmBigLedgerPeerDone`
- `Net.ConnectionManager.Remote.ConnectionHandler.Error`

**Restart / generation**

- `Net.Server.Remote.Stopped` / `Net.Server.Local.Stopped`
- `Net.ConnectionManager.Remote.Shutdown`
- `Net.Server.Remote.Started` / `Net.Server.Local.Started`
- `Startup.DiffusionInit`

---

## Next: Amaru mapping

For Amaru (Rust) we need equivalent lines that can fill the same
`BlockSampleGroup` slots and the same peer session roles (open /
temperature / close / restart). Work from this checklist: same semantic
field, different `ns` / payload shape is fine as long as we can map it
in a second logreader / event factory path.
