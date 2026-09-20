# Backend briefing: peerevent sessions

**Audience:** backend agent / API maintainers
**From:** openblockperf client (session model, 2026-09-20)
**Endpoint:** existing `POST /submit/peerevent` (same API key)
**No new endpoint.** Dial-fail / PromoteColdFailed still out of scope.

This is the handoff for ingest + storage. The client already POSTs session
fields. The backend (checked 2026-09-20 against `openblockperf-backend`
`src/app/schemas/requests.py`, `src/app/api/v0/endpoints.py`,
`src/app/models/client.py`, `src/app/crud/network.py`) does **not** persist
them. HTTP still returns **201**. That is why monitoring does not show more
submit failures.

Related:

* Blocksample 2nd/3rd announcers: `docs/backend-blocksample.md`
* Plan overview: `docs/peer-data-plan.md`
* Operator local list: `docs/peers.md`

---

## Decisions (2026-09-20)

1. Keep the four `change_type` values so v0.0.42 ingest still works.
2. Client adds omit-none fields: `node_generation`, `session_id`, `event_role`,
   `close_reason`, `we_dialed`. Handshake fields stay optional too.
3. Identity is a **session** (`session_id` + `node_generation` + connection).
   Remote IP is still the catalog / geo key. Ephemeral `remote_port` is
   submitted as `0`.
4. **Do not** use `duplex`. Ignore it if still present (`false`).
5. On `event_role=node_restart` (and/or `close_reason=node_restart` on each
   session): mark all still-open sessions for that client terminated.
   Idempotent. **Do not** insert a fake `peer` row for `0.0.0.0`.
6. Handshake fields missing = unknown, not "feature off".
7. Traceroute / PromoteColdFailed still out of scope for this endpoint.
8. Extra JSON fields must not 422 until the schema is deployed. After
   columns exist, persist them. **Do not** return **201** on `AppError`.

---

## Why it looks like nothing arrives

Pydantic `PeerEventRequest` on the backend only has:

`at`, `direction`, `local_addr`, `local_port`, `remote_addr`, `remote_port`,
`change_type`, `last_seen`, `last_state`

Default extra handling is **ignore**. The client dumps with `exclude_none`
and also sends `duplex=false` plus (when known) `n2n_version`,
`diffusion_mode`, `peer_sharing`, `peras_support`, `node_generation`, `session_id`,
`event_role`, `close_reason`, `we_dialed`. Those keys never land in the
request model. FastAPI still answers **201**.

Tables today:

* `peer`: unique-ish on `(client_id, address_id, port)`. Direction is stored
  on create only. Lookup in `create_peer()` does **not** include direction.
  Inbound and outbound to the same IP:listen-port collapse onto one row.
* `peer_event`: `peer_id`, `at`, `change_type` only.

So a successful POST writes another temperature tick on an IP+port peer.
It does not create a session, does not store HS options, does not store
`we_dialed`. A dashboard that looks for handshake / session columns will
look empty even while `peer_event` row counts go up.

`submit_peersample` also swallows `AppError` and still returns
`PeerEventResponse()` (**201**). Example: `create_address` raises
"Not a valid IP address". That never hits HTTP error metrics.

SQLAlchemy / unexpected exceptions currently `rollback()` and do not return
a body. Those might 500. Quiet monitoring plus missing session fields
points at extra=ignore, not at 422.

### How to confirm in ops (no code)

1. Client journal: lines like
   `{ip} open cold_to_warm inbound gen=… session=…`
   mean the client did call `POST /submit/peerevent`.
2. Edge access log: `POST /{network}/api/v0/submit/peerevent` → **201**.
3. DB: `\d peer_event` / `\d peer`. If there is no `session_id` column,
   the new payload cannot be stored.
4. Count `peer_event` for that client for today. If counts rise, ingest of
   the **old** four fields works. If counts stay flat while journal shows
   submits, look at swallowed `AppError` warnings.

---

## 1. Client behaviour (what we POST)

1. HandshakeSuccess opens a session and submits `event_role=open`
   (`change_type=cold_to_warm`).
2. IG Remote promote/demote, PeerSelection StatusChanged, and Selection
   Promote/Demote *Done update temperatures (`event_role=temperature`).
   ChainSync/BlockFetch **client** lines attach or open a we-dialed session
   at outbound Hot.
3. MuxErrored / Handler.Error / ResponderErrored / DemotedToCold /
   CoolingToCold close the session (`event_role=close` + `close_reason`).
4. Server Stopped / CM Shutdown close **all** open sessions with
   `node_restart`. Server Started increments `node_generation` and submits
   `event_role=node_restart` with dummy remote `0.0.0.0` / port `0`.
5. Useful / debounce is **local `/peers` only**. Short HS flicker is still
   submitted (open then close).

Typical session:

`open` → optional `warm_to_hot` → `close`

Handshake fields are on the open event when HS arrived first.

`n2n_version` / `diffusion_mode` / `peer_sharing` / `peras_support` exist
**only** on HandshakeSuccess (`versionNumber` + `agreedOptions`). No other
`Net.*` line repeats them. Omitted / null means we did not see HS for that
TCP session (typical after mid-run attach; startup replay is currently
off). Treat omitted as **unknown**, not as `PeerSharingDisabled`. **Do not**
copy HS from another session of the same IP. Options are per connection.
If HS arrives later on the same `connectionId`, the client enriches the
open session (no second open submit).

---

## 2. Payload

```json
{
  "at": "2026-09-20T17:00:00.123456+00:00",
  "direction": "inbound",
  "local_addr": "<string>",
  "local_port": 3001,
  "remote_addr": "<ip>",
  "remote_port": 0,
  "change_type": "cold_to_warm",
  "last_seen": "2026-09-20T17:00:00.123456+00:00",
  "last_state": "Warm",
  "n2n_version": 14,
  "diffusion_mode": "InitiatorAndResponderDiffusionMode",
  "peer_sharing": "PeerSharingEnabled",
  "peras_support": "PerasUnsupported",
  "node_generation": 1,
  "session_id": "a1b2c3...",
  "event_role": "open",
  "we_dialed": true
}
```

Client uses `exclude_none`. Unknown optional fields are omitted.
`duplex` is still sent as `false` for old code paths. Ignore it.

| Field | Type | Required | Meaning |
|--------|------|----------|---------|
| `at` / `last_seen` | datetime | yes | Event time (ISO) |
| `direction` | `inbound` \| `outbound` | yes | Track that moved (open/close: outbound if `we_dialed`) |
| `local_addr` / `local_port` | string / int | yes | This relay (may be obfuscated to `0.0.0.0`) |
| `remote_addr` | string | yes | Peer IP. `node_restart` event uses `0.0.0.0` |
| `remote_port` | int | yes | Listen port, or **0** if ephemeral / restart |
| `change_type` | string | yes | Four values below (compat) |
| `last_state` | `Warm` \| `Hot` \| `Cold` | yes | After the event |
| `duplex` | bool | no | Always false if present. Ignore. |
| `n2n_version` | int \| absent | no | From HandshakeSuccess |
| `diffusion_mode` | string \| absent | no | e.g. `InitiatorAndResponderDiffusionMode` |
| `peer_sharing` | string \| absent | no | e.g. `PeerSharingEnabled` |
| `peras_support` | string \| absent | no | e.g. `PerasUnsupported` |
| `node_generation` | int \| absent | no | Cardano-node / diffusion start count. 0 until first Started. Not a chain epoch. |
| `session_id` | string \| absent | no | Hex id. Absent on `event_role=node_restart` |
| `event_role` | `open` \| `temperature` \| `close` \| `node_restart` | no | If absent, treat as old temperature-only client |
| `close_reason` | string \| absent | no | Set on close / restart. See table |
| `we_dialed` | bool \| absent | no | True if we initiated. Absent = unknown |

### `change_type` (compat)

| Value | Meaning |
|-------|---------|
| `cold_to_warm` | Session open or Warm enter |
| `warm_to_hot` | Hot enter |
| `hot_to_warm` | Left Hot, still Warm |
| `warm_to_cold` | Close, or `node_restart` marker |

Prefer `event_role` when present. Cooling is never submitted.

### `close_reason`

| Value | Kind |
|-------|------|
| `ig_mux_error` | unexpected (MuxErrored) |
| `ig_responder_error` | unexpected (KeepAlive etc.) |
| `handler_error` | unexpected (ConnectionHandler.Error) |
| `demoted_cold` | planned IG demote to Cold |
| `cooling_to_cold` | planned outbound CoolingToCold / DemoteWarmDone |
| `node_restart` | cardano-node restart |
| `ttl` | client soft-TTL, no leave line |

---

## 3. Backend tasks

### Stage A (needed now, or the new payload stays invisible)

1. Extend `PeerEventRequest` with the optional fields above. Keep extra
   ignore until this is deployed, then persist.
2. Stop returning **201** on `AppError`. Log and return **4xx** / **5xx**
   so ingest monitoring actually moves.
3. Persist at least: `session_id`, `node_generation`, `event_role`, `close_reason`,
   `we_dialed`, `n2n_version`, `diffusion_mode`, `peer_sharing`,
   `peras_support` on the event row (nullable).
4. `event_role=node_restart` with `remote_addr=0.0.0.0`: do **not** upsert a peer.
   Close open sessions for that `client_id` / `node_generation`.
5. Private IPs are already obfuscated by the client to `0.0.0.0`. Same
   dummy as `node_restart`. Filter those out of the peer catalog.

### Stage B (storage that matches the client)

Current `peer` keyed by `(client, address, port)` cannot represent:

* two TCP sessions to the same IP (we-dialed `:3001` and they-dialed
  ephemeral `:0`)
* session 2 after session 1 closed
* inbound and outbound tracks on one connection
* HS options as a property of the handshake, not of the IP forever

Recommended shape:

1. Keep `address` + a thin `peer` catalog per `(client_id, address_id)`
   for geo / relay join. **Drop port from uniqueness.**
2. New `peer_session`:
   * `client_id`, `session_id` (unique together), `node_generation`
   * `address_id`, `remote_port` (listen or 0)
   * `local_addr`, `local_port`
   * `we_dialed` (nullable)
   * HS fields (`n2n_version`, `diffusion_mode`, `peer_sharing`,
     `peras_support`)
   * `opened_at`, `closed_at`, `close_reason`
3. `peer_event` becomes the timeline of a session:
   * `session_id` FK (nullable for old clients)
   * `at`, `event_role`, `change_type`, `direction`, `last_state`
   * `close_reason` when `event_role=close`
4. Fallback for old clients (`event_role` absent): keep writing
   `(client, address, port)` like today.
5. Open session = `closed_at IS NULL`. On `node_restart`, set `closed_at` for all
   still-open rows of that client.

Join rules:

* Blocksamples: client + remote IP + time overlap with
  `[opened_at, closed_at]`. Prefer `we_dialed=true` sessions for header
  announcers (only outbound ChainSync client can announce to us).
* Conn-explore: by IP, not by session.

### Out of scope

Traceroute, PromoteColdFailed, CM error streams as their own types,
`/submit/peerrelevance`.

---

## 4. How to use with other data

| Source | Role |
|--------|------|
| Blocksamples (`header` / `header2` / `header3` / body) | Who announced/served blocks; overlap with session intervals |
| Backend conn-explore | Reachability + version from fixed vantage points |
| Peerevent sessions | This SPO node negotiated with peer X; open/close and HS options |

Together: successful life signals, plus session replay when a node restarts.

---

## 5. Compatibility

* Older clients without session fields must still ingest (temperature-only).
* `event_role` absent: keep previous Warm/Hot enter/leave behaviour.
* Legacy client config key `peer_events_level` is ignored on the client.
* Do not switch the request model to extra=forbid until Stage A columns
  are live, or current clients 422.
