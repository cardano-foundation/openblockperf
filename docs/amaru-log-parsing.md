# Amaru log parsing (peer events first)

Companion to [haskell-log-parsing.md](haskell-log-parsing.md).
Based on ~8h INFO from `logs/amaru/first-startup/amaru_INFO.log`
(Amaru `10.11.0`, git `33e623a0…`) plus notes in `logs/amaru/keywords.txt`.

## Verdict (2026-09-23)

1. **Peer events: yes, we can start.** INFO already has a usable
   open → use → close lifecycle keyed by `conn_id` + `peer`.
2. **Blocksamples: not yet.** Only `tip.adopt` (and rare
   `block.switch_fork`) on `amaru::consensus`. No header-from-peer,
   fetch-request, or completed-fetch equivalents in this INFO set.
3. **Do not** wait for a perfect Warm/Hot mirror. Map Amaru
   `local_use` onto our session temperatures with explicit aliases.

## Log shape

Amaru lines are JSON (tracing-subscriber style), not cardano-tracer `ns`:

```json
{
  "timestamp": "2026-09-22T11:55:29.533558Z",
  "level": "INFO",
  "target": "amaru::protocols",
  "fields": {
    "message": "manager.peer.handshake_completed",
    "conn_id": 0,
    "peer": "13.41.234.173:3001",
    "advertisable": false,
    "full_duplex": true,
    "full_duplex_capable": true,
    "message_type": "HandshakeComplete"
  }
}
```

Match key is `fields.message` (plus sometimes `target`).
Timestamp field is `timestamp`, not `at`.
Peer is a single `"addr:port"` string (IPv4 in this sample).

---

## Counts from the sample log (peer-ish)

| `fields.message` | Count | Notes |
|------------------|------:|-------|
| `manager.peer.handshake_completed` | 52 | best **session open** |
| `manager.peer.local_use_applied` | 53 | use / temperature |
| `manager.peer.connection_died_handled` | 45 | best **session close** |
| `connection.child_died` | 23 | often precedes died_handled; sometimes alone |
| `manager.peer.connect` | 3 | we tried outbound dial |
| `manager.peer.connected` | 2 | outbound TCP up (both later HS) |
| `manager.peer.set_local_use` | 4 | intent; applied may follow |
| `peer_selection.peer.demoted` | 1 | churn demote |
| `manager.listen.started` | 1 | listen up after start |
| `peer_selection.connect_initial` | 1 | diffusion start |
| `tip.adopt` | 1017 | adopt only; no peer on line |

Of 52 handshakes: **2** had prior `manager.peer.connected` on the same
`conn_id` (we-dialed). **50** opened at handshake without a connected
line (mostly inbound / they-dialed). `connection_died_handled.role`:
44× `responder`, 1× `initiator`.

`local_use` values seen: `none` (50), `diffusion`/`Diffusion` (3+3),
`Maintenance` (1).

---

## Proposed peer mapping (v0)

Align to session roles in [peers.md](peers.md): `open` / `temperature` /
`close` / `node_restart`.

### Session identity

| Concern | Amaru | Client mapping |
|---------|-------|----------------|
| Session key | `conn_id` (monotonic int) | Prefer `conn_id` as primary key while open. Also keep `peer` addr+port. |
| Remote | `fields.peer` | Split `host:port` (bracket IPv6 later). Ephemeral remote port → submit `0` like Haskell. |
| Local | only `listen_addr` on `manager.listen.started` (here `0.0.0.0:5001`) | Cache listen addr/port at start; use as `local_*` on every session. Missing → `0.0.0.0` / configured `local_port`. |
| Direction | `role` on died_handled; prior `manager.peer.connect` | `initiator` or saw `connect`/`connected` → outbound / `we_dialed=true`. Else inbound / unknown until evidence. |
| HS options | not on `handshake_completed` | `n2n_version` / `peer_sharing` / `peras_support` stay null in v0. Ignore `connection.handshake_query_reply` (no `conn_id` / peer; same as ignoring Haskell HandshakeQuery). |
| Duplex flags | `full_duplex`, `advertisable` | Log locally if useful. **Do not** submit duplex fields (same rule as Haskell). |

### Open

| Amaru `fields.message` | Role |
|------------------------|------|
| `manager.peer.handshake_completed` | **Session open** (Haskell HandshakeSuccess) |

Optional enrich (not required to open):

- `manager.peer.connect` / `manager.peer.connected` → mark `we_dialed` early
- `peer_selection.peer.added` / `resolved` → candidate bookkeeping only

### Temperature (Amaru `local_use` ≈ Hot/Warm)

Haskell Warm/Hot does not appear as words. Closest signal is
`manager.peer.set_local_use` / `manager.peer.local_use_applied`:

| `local_use` | Treat as | change_type (outbound track) |
|-------------|----------|------------------------------|
| `none` | connected, not diffusion-Hot (Warm-ish / idle) | after open: stay Warm or no temperature submit until Diffusion |
| `Diffusion` / `diffusion` | **Hot** (chainsync / diffusion active) | `warm_to_hot` |
| `Maintenance` | demoted from diffusion (Warm) | `hot_to_warm` |

Also:

| Amaru message | Role |
|---------------|------|
| `peer_selection.peer.demoted` (`reason=churn`) | temperature down; often followed by `Maintenance` then die |
| `chainsync.initialized` | confirms diffusion path on that `conn_id` (optional Hot confirm) |

v0 can drive temperature from **`local_use_applied` only** (applied is truth;
`set_local_use` is intent). Case-normalize `diffusion`/`Diffusion`.

### Close

| Amaru message | Role |
|---------------|------|
| `manager.peer.connection_died_handled` | **Preferred close** (`outcome=peer_removed` in sample). Map `role` to direction. `close_reason` ≈ mux / demoted depending on prior demote vs sudden mux. |
| `connection.child_died` | Close if no died_handled for that `conn_id` within a short window; else ignore duplicate. `child=Handshake` without prior HS → never opened (skip or count as failed attempt, no open submit). |
| `mux.failed` | ERROR; evidence for unexpected close. Prefer died_handled for submit. |

### Node restart / generation

| Amaru message | Role |
|---------------|------|
| `build.version` or `peer_selection.connect_initial` | start of node generation (marker for replay) |
| `manager.listen.started` | listen up; good debounce companion |
| (stop) | **gap in this INFO sample** – no clean Server.Stopped equivalent spotted yet. Process death / missing lines may leave sessions open until TTL. |

Replay marker candidate: `"message":"peer_selection.connect_initial"` or
`"message":"build.version"`.

---

## Example lifecycles (from keywords + counts)

### We-dialed diffusion peer (conn_id 0 / 1)

1. `peer_selection.peer.resolved` / `added`
2. `manager.peer.connect`
3. `manager.peer.connected` (`conn_id`)
4. `manager.peer.handshake_completed` → **open**
5. `local_use` Diffusion → **Hot**
6. `chainsync.initialized` / `intersect_found`
7. later: `peer_selection.peer.demoted` → Maintenance → `connection_died_handled` (`role=initiator`) → **close**

### They-dialed / idle after HS (most of the 50)

1. `manager.peer.handshake_completed` (often ephemeral remote port) → **open**
2. `local_use_applied` with `none` → not useful / not Hot
3. `connection_died_handled` (`role=responder`) → **close**

### HS never completed

`connection.child_died` with `child=Handshake` and no prior
`handshake_completed` for that `conn_id` → **no session** (do not invent open).

---

## Gaps vs Haskell peer parser

1. No agreed n2n options on the open line.
2. No structured local connectionId; listen addr only.
3. Temperature vocabulary is `local_use`, not IG/PeerSelection Warm/Hot.
4. Outbound `connected` is rare in INFO; open must not depend on it.
5. Some `conn_id`s die without any HS (failed handshake) – filter those.
6. Clean shutdown / restart close-all not confirmed in this log yet.
7. `tip.adopt` has hash/slot/height but **no peer** → cannot fill
   blocksample deltas or announcer IPs from INFO alone.

---

## Implementation (v0, 2026-09-23)

Code path:

* `src/openblockperf/amaru.py` – parse `fields.message` → `AmaruPeerBridge`
* `EventHandler` routes Amaru lines when `node_kind` is `amaru` or `auto`
  (auto: line has `fields.message` and no `ns`)
* `PeerTracker.set_outbound_temperature` / `close_connection` used for
  Amaru temperature / close without inventing Haskell PeerEvents

Config:

```json
{
  "node_kind": "amaru",
  "tracer_log_file": "/path/to/amaru.json.log",
  "node_unit_name": "",
  "local_port": 5001,
  "sync_check_enabled": false
}
```

`node_kind` default is `auto`. For logfile mode set `node_unit_name` to
`""` (Amaru lines have no `host` field). Point `local_port` at the Amaru
listen port. EKG sync gate is Haskell-oriented; disable until Amaru has
an equivalent.

Still missing for blocksamples: ask Amaru for header-from-peer, fetch
request, completed fetch (with peer + size), and prefer adopt lines that
name the peer / conn_id.