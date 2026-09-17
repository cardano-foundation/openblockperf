# Peer / blocksample data plan (client + backend)

Living plan for peer events, local relevance, and what we send upstream.

## Decisions (2026-09-17)

1. **No** `/submit/peerrelevance` and no relevance snapshot table.
2. Extend **blocksamples** with 2nd and 3rd header announcer
   (`header2_remote_addr/port`, `header3_remote_addr/port`).
3. Backend computes peer relevance from blocksample (+ `block_prop`
   relay ids). Client relevance stays **local metrics only**.
4. Prefer raw per-block fields over client-precomputed aggregates so
   manipulated submits are harder to disguise.
5. Empty relevance snapshots are not a backend concern anymore.
6. Peerevent `duplex` and inbound `remote_port=0` stay as in
   `backend-peer-events.md` (temperature duplex, not CM Bi-Dir).
7. ConnectionManager counters / true Bi-Dir explore later (local first);
   not required for blocksample 2nd/3rd.

## Handoff docs (backend agent)

| Doc | Status |
|-----|--------|
| `docs/backend-blocksample.md` | **Active** – 2nd/3rd announcer fields |
| `docs/backend-peer-events.md` | Active – peerevent + `duplex` |
| `docs/backend-peer-relevance.md` | **Cancelled** |

## Phases

### Phase 1 – specs / handoff (this change)

* Freeze decisions above.
* Publish `backend-blocksample.md`.
* Mark peerrelevance handoff cancelled.
* Align local-metrics docs (relevance local-only).

### Phase 2 – client blocksample fields

* Track 2nd/3rd announcer **addr+port** in `BlockSampleGroup`
  (today we only keep IPs for local ranks).
* Add four fields to `BlockSample` / submit payload.
* Obfuscate `header2` / `header3` addrs like the 1st header.
* Ship only after backend accepts the optional fields.

### Phase 3 – backend ingest + `block_prop`

* Optional fields on blocksample API.
* Persist + two relay lookups → `header2_relay_id`, `header3_relay_id`.
* Post-analyze relevance / size×peer as needed.

### Phase 4 – ConnectionManager light (optional, local first)

* Parse `ConnectionManagerCounters` for gLiveView-like gauges.
* Decide later if any of that is worth submitting.

### Out of scope for now

* Traceroute / geo pull-back.
* Changing peerevent `change_type` set.
* Merging IPv4/IPv6 into one peer identity on the client.
