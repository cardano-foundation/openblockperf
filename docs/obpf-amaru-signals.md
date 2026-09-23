# oBPF signals for Amaru (catalogue for node team)

Hand-off for Amaru: dedicated **OpenBlockPerf (oBPF)** signals so the client
does not scrape Haskell-style tracer namespaces or EKG.

Today we stitch many log lines and compute deltas from timestamps.
Desired shape: **self-contained signals** (especially for blocksamples)
with **millisecond distances already filled**, plus a small stream of
**peer session state changes**.

## Transport (preference)

Emit oBPF signals as **JSON lines on stdout / journald** (same path as
normal Amaru logs). Mark them so we can filter cheaply, e.g.:

* `"signal": "obpf.…"` and/or
* a clear marker such as `.obpData` / `"obpData": true`

We will keep reading via journald (and optional logfile follow). No other
ingest path is planned for now.

Name prefix: `obpf.*` (or `amaru.obpf.*` if you prefer Amaru namespacing).

Related: [haskell-log-parsing.md](haskell-log-parsing.md),
[amaru-log-parsing.md](amaru-log-parsing.md), [peers.md](peers.md),
[blocksample.md](blocksample.md).

## Requests (2026-09-23)

What we ask Amaru to emit. Not a locked implementation agreement yet.

1. Prefer **one complete blocksample signal** per adopted (or fork-switched)
   block hash, with deltas already filled in ms.
2. All timings we currently derive from log `at` deltas should appear as
   **integer milliseconds** on that signal (absolute step times are fine
   for debug too).
3. Peer data stays a **session over time**. Emit discrete state-change
   signals keyed by a stable `conn_id` / connection identity.
4. Handshake options (`n2n_version`, diffusion mode, peer sharing, peras)
   belong on the **open / handshake** signal only.
5. Do not require EKG / Prometheus for oBPF. Node version comes on
   startup. While catching up, simply **do not emit oBPF data** until
   the node considers itself on tip; then start the stream.
6. Slot / height battles: **no separate battle signals**. Emit a full
   `obpf.blocksample` for **each** block hash that was announced, fetched,
   and adopted or switched-to (same idea as the Haskell path). Both
   candidates in a race can each produce a sample.

Out of scope for now: partial / incomplete blocksamples (would need
backend + Haskell client changes together). Rollback-only signals are
also not required today (Haskell does not parse them either).

## Common envelope

Every signal should carry:

| Field | Type | Notes |
|-------|------|-------|
| `signal` | string | Stable name, e.g. `obpf.blocksample` |
| `at` | string | ISO-8601 UTC, sub-ms ok |
| `network` | string | `mainnet` / `preprod` / `preview` / custom |
| `magic` | int | network magic |
| `node_id` | string | optional host / pool label if known |

Addresses: IPv4 / IPv6 strings. Ephemeral remote ports may be kept on the
wire; oBPF client will map `>= 32768` to `0` on submit when needed.

---

## 1. Startup / node context

Replaces EKG `cardano_version_*` and the sync gate.

### `obpf.node.started`

Emit once when diffusion / listen is up (after cold start or restart).

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `node_version` | string | yes | e.g. `10.11.0` (same idea as `build.version`) |
| `git_commit` | string | no | short or full sha |
| `listen_addr` | string | yes | e.g. `0.0.0.0` |
| `listen_port` | int | yes | e.g. `3000` |
| `network` | string | yes | |
| `magic` | int | yes | |
| `pid` | int | no | |

Client uses this for `/submit/clientinfo` (`node_version`) and to bump
**node generation** (close open peer sessions, same as Haskell
Server.Started).

### `obpf.node.stopping` (optional but useful)

Emit before process exit / orderly shutdown.

| Field | Type | Required |
|-------|------|----------|
| `reason` | string | no | e.g. `signal`, `cli`, `error` |

Client closes all peer sessions with `close_reason=node_restart`.

### Sync / tip gate (no progress signal needed)

We do **not** need a progress percentage stream. Prefer: while the node
is still catching up, emit **no** `obpf.blocksample` / peer oBPF signals.
Once the node is on tip (live), start emitting. That replaces the EKG
replay gate without extra chatter.

Optional: a single `obpf.node.live` (or a flag on the first post-sync
signal) is enough if you want an explicit edge. Continuous
`progress_pct` is not required.

---

## 2. Block propagation

### Design (match Haskell behaviour)

For **each** block hash that this node fully observed through the four
steps, emit one `obpf.blocksample`:

1. first header (and up to 2 more unique announcers)
2. send fetch request **(important!)** that later matches the successful
   body download
3. completed block fetch
4. adopt (`added_to_current_chain` or `switched_to_fork`)

In a slot or height battle, **both** (all) competing hashes that were
fetched and adopted / switched-to should each get their own complete
sample. A later rollback is rare; today we do not parse rollbacks on
Haskell. The next successful tip extension is enough context for now.

Deltas we need on the signal (ms):

* `header_delta_ms` = first_header_at − slot_time
* `block_request_delta_ms` = fetch_request_at − first_header_at
* `block_response_delta_ms` = fetch_complete_at − fetch_request_at
* `block_adopt_delta_ms` = adopt_at − fetch_complete_at

### `obpf.blocksample` (primary)

Emit **once per completed path** for a block hash (adopt or switch to
fork), with a measurable remote fetch when applicable.

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `block_hash` | string | yes | hex header/block hash |
| `block_number` | int | yes | height / blockNo |
| `slot` | int | yes | |
| `slot_time` | string | yes | ISO UTC of slot start (or emit `slot` only; client can derive from network genesis) |
| `block_size` | int | yes | bytes of body |
| `adopt_kind` | string | yes | `added_to_current_chain` \| `switched_to_fork` |
| **Header announcers (unique remotes, first-seen order, max 3)** | | | |
| `header1_addr` / `header1_port` | string / int | yes | earliest header source |
| `header1_at` | string | yes | when first header was received |
| `header2_addr` / `header2_port` | string / int | no | 2nd unique announcer; empty/`0` if none |
| `header2_at` | string | no | |
| `header3_addr` / `header3_port` | string / int | no | 3rd unique |
| `header3_at` | string | no | |
| **Successful fetch path** | | | |
| `fetch_peer_addr` / `fetch_peer_port` | string / int | yes | peer that served the body for this hash |
| `fetch_request_at` | string | yes | time of the **successful** fetch request (same peer as completed body; not every speculative request) |
| `fetch_completed_at` | string | yes | body download finished |
| `adopt_at` | string | yes | local adopt / fork switch for this hash |
| **Deltas (milliseconds, signed int ok)** | | | |
| `header_delta_ms` | int | yes | `header1_at − slot_time` |
| `block_request_delta_ms` | int | yes | `fetch_request_at − header1_at` |
| `block_response_delta_ms` | int | yes | `fetch_completed_at − fetch_request_at` |
| `block_adopt_delta_ms` | int | yes | `adopt_at − fetch_completed_at` |

Example (abbreviated):

```json
{
  "signal": "obpf.blocksample",
  "obpData": true,
  "at": "2026-09-22T12:10:24.564Z",
  "block_hash": "4bdc66a4…",
  "block_number": 13973679,
  "slot": 198512733,
  "block_size": 7421,
  "adopt_kind": "added_to_current_chain",
  "header1_addr": "13.41.234.173",
  "header1_port": 3001,
  "header1_at": "2026-09-22T12:10:24.100Z",
  "header2_addr": "13.127.123.204",
  "header2_port": 3001,
  "header2_at": "2026-09-22T12:10:24.140Z",
  "header3_addr": "",
  "header3_port": 0,
  "fetch_peer_addr": "13.41.234.173",
  "fetch_peer_port": 3001,
  "fetch_request_at": "2026-09-22T12:10:24.200Z",
  "fetch_completed_at": "2026-09-22T12:10:24.450Z",
  "adopt_at": "2026-09-22T12:10:24.564Z",
  "header_delta_ms": 850,
  "block_request_delta_ms": 100,
  "block_response_delta_ms": 250,
  "block_adopt_delta_ms": 114
}
```

---

## 3. Peer sessions

Peers are **long-lived**. Emit a signal on each meaningful state change.
Client joins by `conn_id` (preferred) or
`(local_addr, local_port, remote_addr, remote_port)` within one
`node_generation`.

Map to current submit roles: `open` / `temperature` / `close` /
`node_restart` ([peers.md](peers.md)).

### Identity on every peer signal

| Field | Type | Required |
|-------|------|----------|
| `conn_id` | int or string | yes | stable for TCP lifetime |
| `local_addr` / `local_port` | | yes | listen side |
| `remote_addr` / `remote_port` | | yes | |
| `direction` | string | yes | `inbound` \| `outbound` |
| `we_dialed` | bool | yes | true if we initiated TCP |

### `obpf.peer.handshake` → session **open**

Emit when n2n handshake completes (Haskell HandshakeSuccess).

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `n2n_version` | int | yes | agreed version number |
| `diffusion_mode` | string | yes | e.g. initiator-and-responder / initiator-only |
| `peer_sharing` | string | yes | enabled / disabled (agreed) |
| `peras_support` | string | no | if negotiated |
| `advertisable` | bool | no | Amaru already logs this |
| `full_duplex` | bool | no | optional local debug only; not required for backend |

This is the only place we need handshake options. Later signals may omit
them (client caches on the session).

### `obpf.peer.temperature` → **temperature**

Amaru `local_use` / diffusion role changes, or any Warm/Hot equivalent.

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `track` | string | yes | `inbound` \| `outbound` \| `use` (if single track) |
| `from_state` | string | yes | previous |
| `to_state` | string | yes | new |
| `change_type` | string | yes | one of: `cold_to_warm`, `warm_to_hot`, `hot_to_warm`, `warm_to_cold` |

Suggested Amaru mapping (align with current v0 parser):

| Amaru notion | `to_state` | `change_type` |
|--------------|------------|---------------|
| connected / `local_use=none` after HS | Warm | (often no extra submit; open already implies cold_to_warm) |
| `local_use=Diffusion` | Hot | `warm_to_hot` |
| `local_use=Maintenance` / demote | Warm | `hot_to_warm` |
| demote to cold / removed from use | Cold | `warm_to_cold` (usually paired with close) |

If you prefer Cold/Warm/Hot names only, emit those; oBPF will map.

### `obpf.peer.close` → **close**

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `close_reason` | string | yes | see below |
| `last_state` | string | yes | Warm/Hot/… before close |

`close_reason` values we already use / want:

| Value | When |
|-------|------|
| `demoted_cold` | orderly churn / demote |
| `ig_mux_error` | mux / connection reset / unexpected die |
| `ig_responder_error` | protocol responder death |
| `handler_error` | connection handler error |
| `node_restart` | process / diffusion stop |
| `cooling_to_cold` | if you have an explicit cooling phase |

### Optional peer signals

| Signal | When | Fields |
|--------|------|--------|
| `obpf.peer.dial` | we start outbound connect | remote addr/port, candidate origin (`static`/`snapshot`/…) |
| `obpf.peer.connected` | TCP up, before HS | `conn_id`, remotes |
| `obpf.peer.chainsync` | ChainSync initialized / intersect | `conn_id`, current/highest tip tuple |

Nice for debugging; not required if handshake + temperature + close are solid.

### Node restart vs peers

`obpf.node.started` / `obpf.node.stopping` already cover generation.

---

## Priority for Amaru

**Must have (unblocks full oBPF on Amaru):**

1. Journal JSON oBPF lines (filterable marker + `signal`)
2. `obpf.node.started` (version + listen + network)
3. Hold oBPF block/peer data until on tip
4. `obpf.blocksample` (complete, with 4× `*_delta_ms` + 3 header ranks + successful fetch; one per completed hash including battle candidates)
5. `obpf.peer.handshake` / `obpf.peer.temperature` / `obpf.peer.close`

**Should have:**

6. `obpf.node.stopping`

**Later / optional:**

7. Optional dial / connected / chainsync peer crumbs
8. Explicit `obpf.node.live` edge (only if holding all data until tip is awkward)

Haskell cardano-node keeps the existing tracer path; this catalogue is
the **Amaru-native** journal contract.
