# Backend handoff: peerevent (sessions + HandshakeSuccess)

**Audience:** backend agent / API maintainers
**Client:** openblockperf after the session-model change
**Endpoint:** existing `POST /submit/peerevent` (same API key)
**No new endpoint.** Dial-fail / PromoteColdFailed still out of scope.

**Goal:** one comparable **session** stream from every SPO client. Handshake
capabilities plus temperature timeline until the session ends. Node restart
is an epoch so previously open sessions can be marked terminated.

Related:

* Blocksample 2nd/3rd announcers: `docs/backend-blocksample.md`
* Plan overview: `docs/peer-data-plan.md`
* Operator local list: `docs/peers.md`

Client peerevents mean: this relay successfully talked to peer X (HS), how
that TCP session moved Warm/Hot, and how it ended.

Typical fleet TraceOptions (CNTools and similar) log
`Net.ConnectionManager.Remote` at Info **without** a parent `maxFrequency`, so
HandshakeSuccess is available. Throttle only `ConnectionManagerCounters`.

---

## Decisions (2026-09-20)

1. Keep the four `change_type` values so v0.0.42 ingest still works.
2. Add omit-none fields: `epoch_id`, `session_id`, `event_role`,
   `close_reason`, `we_dialed`.
3. Identity is a **session** (`session_id` + `epoch_id` + connection).
   Remote IP is still the relay identity for catalog / geo. Ephemeral
   `remote_port` is submitted as `0`.
4. **Do not** use `duplex`. Ignore it if still present (`false`).
5. On `event_role=epoch` (and/or `close_reason=node_epoch` on each session):
   mark all still-open sessions for that client terminated. Idempotent.
6. Handshake fields stay optional. Missing = unknown, not "feature off".
7. Traceroute / PromoteColdFailed still out of scope for this endpoint.

---

## 1. Client behaviour

1. HandshakeSuccess opens a session and submits `event_role=open`.
2. IG Remote promote/demote, PeerSelection StatusChanged, and Selection
   Promote/Demote *Done update temperatures on that session
   (`event_role=temperature`). ChainSync/BlockFetch **client** lines attach
   or open a we-dialed session at outbound Hot.
3. MuxErrored / Handler.Error / ResponderErrored / DemotedToCold /
   CoolingToCold close the session (`event_role=close` + `close_reason`).
4. Server Stopped / CM Shutdown close **all** open sessions with
   `node_epoch`. Server Started increments `epoch_id` and submits
   `event_role=epoch`.
5. Useful / debounce is **local `/peers` only**. Short HS flicker is still
   submitted (open then close).

Typical session on the backend:

`open` → optional `warm_to_hot` → `close`

Handshake fields are on the open event when HS arrived first.

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
  "epoch_id": 1,
  "session_id": "a1b2c3...",
  "event_role": "open",
  "we_dialed": false
}
```

| Field | Type | Required | Meaning |
|--------|------|----------|---------|
| `at` / `last_seen` | datetime | yes | Event time (ISO) |
| `direction` | `inbound` \| `outbound` | yes | Track that moved (open/close: outbound if `we_dialed`) |
| `local_addr` / `local_port` | string / int | yes | This relay (may be obfuscated) |
| `remote_addr` | string | yes | Peer IP. Epoch event uses `0.0.0.0` |
| `remote_port` | int | yes | Listen port, or **0** if ephemeral / epoch |
| `change_type` | string | yes | Four values below (compat) |
| `last_state` | `Warm` \| `Hot` \| `Cold` | yes | After the event |
| `duplex` | bool | no | Always false if present. Ignore. |
| `n2n_version` | int \| absent | no | From HandshakeSuccess |
| `diffusion_mode` | string \| absent | no | e.g. `InitiatorAndResponderDiffusionMode` |
| `peer_sharing` | string \| absent | no | e.g. `PeerSharingEnabled` |
| `peras_support` | string \| absent | no | e.g. `PerasUnsupported` |
| `epoch_id` | int \| absent | no | Node generation. 0 until first Started |
| `session_id` | string \| absent | no | Hex id. Absent on `event_role=epoch` |
| `event_role` | `open` \| `temperature` \| `close` \| `epoch` | no | If absent, treat as old temperature-only client |
| `close_reason` | string \| absent | no | Set on close / epoch. See table |
| `we_dialed` | bool \| absent | no | True if we initiated. Absent = unknown |

Client uses `exclude_none`: unknown optional fields are omitted.

### `change_type` (compat)

| Value | Meaning |
|-------|---------|
| `cold_to_warm` | Session open or Warm enter |
| `warm_to_hot` | Hot enter |
| `hot_to_warm` | Left Hot, still Warm |
| `warm_to_cold` | Close, or epoch marker |

Prefer `event_role` when present. Cooling is never submitted.

### `close_reason`

| Value | Kind |
|-------|------|
| `ig_mux_error` | unexpected (MuxErrored) |
| `ig_responder_error` | unexpected (KeepAlive etc.) |
| `handler_error` | unexpected (ConnectionHandler.Error) |
| `demoted_cold` | planned IG demote to Cold |
| `cooling_to_cold` | planned outbound CoolingToCold |
| `node_epoch` | cardano-node restart |
| `ttl` | client soft-TTL, no leave line |

---

## 3. Backend tasks

1. **Schema:** optional session fields above. Keep accepting posts without them.
2. **Lifecycle:** session row per `(client, session_id)` falling back to
   `(client, remote_addr, direction)` for old clients.
3. **Epoch:** on `event_role=epoch` or any `close_reason=node_epoch`, close
   remaining open sessions for that client.
4. **Signs of life:** HS fields + session intervals. Join with conn-explore
   pings by IP. Join blocksamples by client + remote IP + time overlap.
5. **Strict validators:** add fields before new clients go wide, or posts 422.
6. **Out of scope:** traceroute, PromoteColdFailed, CM error streams as their
   own types, `/submit/peerrelevance`.

---

## 4. How to use with other data

| Source | Role |
|--------|------|
| Blocksamples (`header` / `header2` / `header3` / body) | Who announced/served blocks; overlap with session intervals |
| Backend conn-explore | Successful reachability + version/features from fixed vantage points |
| Peerevent sessions | This SPO’s node negotiated with peer X; open/close and HS options |

Together: successful life signals, plus session replay when a node restarts.

---

## 5. Compatibility

* Older clients without session fields must still ingest (temperature-only).
* `event_role` absent: keep previous Warm/Hot enter/leave behaviour.
* Legacy client config key `peer_events_level` is ignored on the client.
