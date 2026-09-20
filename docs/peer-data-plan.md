# Peer / blocksample data plan (client + backend)

Living plan for peer sessions, local relevance, and what we send upstream.

## Decisions (2026-09-20)

1. Peer tracking is a **connection session** store, not an IP-keyed
   temperature map. Keep the existing parsers. Rewrite the tracker and submit.
2. HandshakeSuccess **opens** a session (sign of life). IG Remote and
   PeerSelection StatusChanged are two temperature tracks on that session.
3. `InboundGovernor.Local` is n2c / unix, not outbound n2n. Outbound n2n is
   PeerSelection.
4. Debounce (`peer_event_stable_seconds`) only flags **useful** for `/peers`.
   Backend always gets open/close, including short HS flicker.
5. Restart: Stopped/Shutdown close all with `node_restart`. Started increments
   `node_generation` and submits `event_role=node_restart`. Not a chain epoch.
6. **Do not** name or submit CM duplex / bi-dir. Drop `duplex` from `/peers`.
7. Do not chase node Warm/Hot counter boxes. Count useful open sessions.
8. Traceroute / RTT still later, on first Warm, our own probe.
9. Phase 4 ConnectionManagerCounters gauges: skip. Counters are noise when
   unthrottled and they are not our product numbers.
10. Backend `POST /submit/peerevent` (checked 2026-09-20) still stores
    `(client, address, port)` + `change_type` only. Extra JSON including
    session/HS fields is ignored. HTTP **201**. Briefing:
    `docs/backend-peer-events.md`.
11. `/peers` drops `first_seen` (duplicate of `opened_at`).
12. Handshake options stay null unless we saw HandshakeSuccess for that
    connection. Startup log replay is implemented but currently disabled.

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
7. Presence + soft TTL (**2026-09-19**): `first_seen` / `last_signal`; demote
   Warm/Hot after `peer_signal_ttl_seconds` (default 1800) without peerevent /
   handshake / header / body signal.

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
| `docs/backend-peer-events.md` | **Active** – session fields + HandshakeSuccess + node_generation |
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

### Phase 3c – connection sessions (**client done, backend ingest not**)

* Session store keyed by connectionId + node_generation.
* Submit `event_role` / `session_id` / `node_generation` / `close_reason` / `we_dialed`.
* Close all open sessions on node restart. Local `/peers` is useful open sessions.
* Backend still IP+port event log until Stage A/B in `backend-peer-events.md`.

### Phase 4 – ConnectionManager counters

* **Cancelled.** Do not parse Counters for gLiveView-like gauges.

### Out of scope for now

* Traceroute / geo pull-back.
* Dial-fail / PromoteColdFailed submits (still out of scope).
* Merging IPv4/IPv6 into one peer identity on the client.

Abrupt inbound drops (`MuxErrored` / `ConnectionHandler.Error` /
`ResponderErrored`) close the session. Restart Stopped/Shutdown submit
`close_reason=node_restart` instead of a silent wipe.
