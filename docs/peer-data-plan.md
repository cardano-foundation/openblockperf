# Peer / blocksample data plan (client + backend)

Living plan for peer events, local relevance, and what we send upstream.

## Decisions (2026-09-18)

1. **No** `peer_events_level`. Every client reports the same temperature
   lifecycle (`cold_to_warm`, `warm_to_hot`, leaves) with debounce only.
2. Traceroute stays optional (`peer_traceroute_enabled`) and unimplemented.
3. HandshakeSuccess enrichment on peerevents (`n2n_version`, `diffusion_mode`,
   `peer_sharing`, `peras_support`) when CM logs are available.
4. Typical CNTools TraceOptions log CM Remote at Info without parent
   `maxFrequency`, so HandshakeSuccess is usually available. If an install
   throttles that namespace (`maxFrequency: 0.0167` etc.), enrichment coverage
   drops; drop the throttle or override HandshakeSuccess.
5. Backend conn-explore remains complementary (global vantage), not replaced
   by client handshakes.
6. Backend peerevent ingest ready **2026-09-18**; client ships as **v0.0.42**.

## Decisions (2026-09-17)

1. **No** `/submit/peerrelevance` and no relevance snapshot table.
2. Extend **blocksamples** with 2nd and 3rd header announcer
   (`header2_remote_addr/port`, `header3_remote_addr/port`).
3. Backend computes peer relevance from blocksample (+ `block_prop`
   relay ids). Client relevance stays **local metrics only**.
4. Prefer raw per-block fields over client-precomputed aggregates so
   manipulated submits are harder to disguise.
5. Peerevent `duplex` = temperature both dirs (not CM Bi-Dir).
6. ConnectionManager handshake enrichment (see 2026-09-18).

## Handoff docs (backend agent)

| Doc | Status |
|-----|--------|
| `docs/backend-blocksample.md` | **Active** – 2nd/3rd announcer fields (v0.0.41+) |
| `docs/backend-peer-events.md` | **Active** – unified lifecycle + HandshakeSuccess (v0.0.42+) |
| `docs/backend-peer-relevance.md` | **Cancelled** |

## Phases

### Phase 1 – specs / handoff (this change)

* Freeze decisions above.
* Publish `backend-blocksample.md`.
* Mark peerrelevance handoff cancelled.
* Align local-metrics docs (relevance local-only).

### Phase 2 – client blocksample fields (**done**)

* Track 2nd/3rd announcer **addr+port** in `BlockSampleGroup`.
* Four fields on `BlockSample` / submit payload with defaults `""` / `0`.
* Obfuscate `header2` / `header3` addrs like the 1st header.
* Ship to PyPI only after backend accepts the optional fields (Phase 3).

### Phase 3 – backend ingest + `block_prop` (**ready 2026-09-17**)

* Optional fields on blocksample API accepted.
* Persist + two relay lookups → `header2_relay_id`, `header3_relay_id`.
* Client shipped PyPI with header2/header3 (v0.0.41+).
* Post-analyze relevance / size×peer as needed.

### Phase 3b – peerevent unify + HandshakeSuccess (**ready 2026-09-18**)

* Drop `peer_events_level`; same four `change_type` values for all clients.
* Optional handshake fields on peerevent ingest.
* Client ships PyPI as **v0.0.42**.

### Phase 4 – ConnectionManager light (optional, local first)

* Parse `ConnectionManagerCounters` for gLiveView-like gauges.
* Decide later if any of that is worth submitting.

### Out of scope for now

* Traceroute / geo pull-back.
* Dial-fail / PromoteColdFailed submits (still out of scope).
* Merging IPv4/IPv6 into one peer identity on the client.

Abrupt inbound drops (`MuxErrored` / `ConnectionHandler.Error` /
`ResponderErrored`) **are** parsed as Cold leaves so peerCountStats track
gLiveView / IG closer. CM Shutdown wipes the FSM.
