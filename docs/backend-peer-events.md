# Backend handoff: peerevent (unified + HandshakeSuccess)

**Audience:** backend agent / API maintainers  
**Client:** openblockperf v0.0.42+  
**Endpoint:** existing `POST /submit/peerevent` (same API key)  
**No new endpoint.** No dial-fail / error submits. Success life-signals only.  
**Backend ingest:** ready (2026-09-18). Client may ship on PyPI.

**Goal:** one comparable peer session stream from every SPO client: handshake
capabilities (when known) plus debounced temperature lifecycle until the
session ends. Same schema for all clients (no `peer_events_level`).

Related:

* Blocksample 2nd/3rd announcers: `docs/backend-blocksample.md`
* Plan overview: `docs/peer-data-plan.md`
* Peer relevance POST: cancelled (`docs/backend-peer-relevance.md`)

Complementary to backend conn-explore (global successful pings +
version/features). Client peerevents mean: this relay successfully talked to
peer X and how that session moved Warm/Hot.

Typical fleet TraceOptions (CNTools and similar) log
`Net.ConnectionManager.Remote` at Info **without** a parent `maxFrequency`, so
HandshakeSuccess is available in normal installs.

---

## Decisions (2026-09-18)

1. No `peer_events_level`. Every client reports the same four `change_type`
   values with debounce only (`peer_event_stable_seconds`, default 15).
2. HandshakeSuccess enriches peerevents with optional capability fields.
3. We do **not** submit connection failures, PromoteColdFailed, or CM errors
   as their own event types. The client may still emit normal `warm_to_cold`
   when MuxErrored / Handler.Error / ResponderErrored clear a reported peer.
4. Traceroute stays a future separate optional switch; not part of peerevent.

---

## 1. Client behaviour

1. Parses `Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess`
   and caches per remote IP: `n2n_version`, `diffusion_mode`, `peer_sharing`,
   `peras_support` (service port when not ephemeral).
2. Parses PeerSelection / InboundGovernor temperature changes.
   Debounced enters; immediate leaves.
3. On each peerevent submit, attaches the **latest cached handshake** for that
   IP (if any).
4. Cooling is client-only; collapsed into reportable leaves. Never submitted
   as Cooling.

Typical session on the backend:

`cold_to_warm` → (optional) `warm_to_hot` → `hot_to_warm` and/or `warm_to_cold`

Handshake fields may already be on the first enter if HS arrived earlier;
otherwise they appear on later events once HS is seen. Missing fields =
unknown (not “feature off”).

---

## 2. Payload

```json
{
  "at": "2026-09-18T17:00:00.123456+00:00",
  "direction": "inbound",
  "local_addr": "<string>",
  "local_port": 3001,
  "remote_addr": "<ip>",
  "remote_port": 0,
  "change_type": "cold_to_warm",
  "last_seen": "2026-09-18T17:00:00.123456+00:00",
  "last_state": "Warm",
  "duplex": false,
  "n2n_version": 14,
  "diffusion_mode": "InitiatorAndResponderDiffusionMode",
  "peer_sharing": "PeerSharingEnabled",
  "peras_support": "PerasUnsupported"
}
```

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `at` / `last_seen` | datetime | yes | Event time (ISO) |
| `direction` | `inbound` \| `outbound` | yes | Side of the peer |
| `local_addr` / `local_port` | string / int | yes | This relay (may be obfuscated) |
| `remote_addr` | string | yes | Peer IP (identity with client id) |
| `remote_port` | int | yes | Outbound: listen port. **Inbound: always `0`** |
| `change_type` | string | yes | See table below |
| `last_state` | `Warm` \| `Hot` \| `Cold` | yes | Temperature after change |
| `duplex` | bool | no (default false) | Warm/Hot on **both** IN and OUT (temperature duplex, not CM Bi-Dir) |
| `n2n_version` | int \| absent | no | From HandshakeSuccess |
| `diffusion_mode` | string \| absent | no | e.g. `InitiatorAndResponderDiffusionMode` |
| `peer_sharing` | string \| absent | no | e.g. `PeerSharingEnabled` |
| `peras_support` | string \| absent | no | e.g. `PerasUnsupported` |

Client uses `exclude_none`: unknown handshake fields are **omitted** from JSON.

### `change_type` (all four from all current clients)

| Value | Meaning |
|-------|---------|
| `cold_to_warm` | Stable Warm enter (session became useful) |
| `warm_to_hot` | Stable Hot enter |
| `hot_to_warm` | Left Hot, still Warm |
| `warm_to_cold` | Left to Cold (includes Cooling teardown collapse) |

Do **not** expect Cooling change types. Do **not** expect dial-fail events.

String codes as above, or map to internal enum/IDs. Low cardinality either way.

---

## 3. Backend tasks

1. **Schema:** optional `n2n_version`, `diffusion_mode`, `peer_sharing`,
   `peras_support` (absent = unknown). Keep `duplex`.
2. **Persist** them for analytics / life-signal views next to conn-explore.
3. **Lifecycle:** session markers per `(client, remote_addr, direction)`.
   Inbound port is not a relay id. Outbound may join catalog via
   `remote_addr:remote_port` when port ≠ 0.
4. **Expect `cold_to_warm`** from the whole fleet (no mid/high split).
5. **Strict validators:** add fields before new clients go wide, or posts 422.
6. **Out of scope:** traceroute, PromoteColdFailed, CM error streams,
   separate handshake-only endpoint, `/submit/peerrelevance`.

---

## 4. How to use with other data

| Source | Role |
|--------|------|
| Blocksamples (`header` / `header2` / `header3` / body) | Who announced/served blocks; correlate with Hot intervals |
| Backend conn-explore | Successful reachability + version/features from fixed vantage points |
| Peerevent + HandshakeSuccess fields | This SPO’s node negotiated with peer X; session Warm/Hot lifecycle |

Together: different sources of **successful** life signals, not error
diagnostics.

---

## 5. Compatibility

* Older clients without handshake fields must still ingest.
* Older mid-only Hot enter/leave history stays valid; new clients add Warm
  enters + optional capability fields.
* Legacy client config key `peer_events_level` is ignored on the client
  (`extra=ignore`).
