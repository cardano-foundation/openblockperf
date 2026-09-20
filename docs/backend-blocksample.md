# Backend handoff: blocksample 2nd / 3rd header announcers

**Audience:** backend agent / API maintainers
**Client:** openblockperf
**Endpoint:** existing `POST /submit/blocksample` (no new route)

## Why this change

We want peer relevance on the server without a new table or
`/submit/peerrelevance` endpoint.

* Blocksamples already carry 1st header announcer and 1st body server.
* 2nd and 3rd header announcers are the interesting extra signal.
* Backend can aggregate relevance (and join to block size, timing, etc.)
  from raw samples during `block_prop` import.
* Precomputed relevance snapshots would be easier for a malicious operator
  to fake. Per-block announcer fields stay closer to what the node logged.

**Do not** add a peerrelevance ingest path. That plan is cancelled.

## Decisions (2026-09-17)

1. Extend blocksample payload with 2nd and 3rd header announcer
   (`addr` + `port` each). Four optional scalar fields.
2. On import into `block_prop`, run two more relay lookups and store two
   more relay id columns (nullable when unknown / missing announcer).
3. Client keeps 30m relevance scoring for **local metrics only**.
   No periodic relevance POST.
4. Same API key auth as today. Same obfuscation rules as other remote
   addrs on this endpoint.

## New fields on `POST /submit/blocksample`

Add next to existing `header_remote_addr` / `header_remote_port`:

| Field | Type | When missing |
|-------|------|--------------|
| `header2_remote_addr` | string | `""` |
| `header2_remote_port` | int | `0` |
| `header3_remote_addr` | string | `""` |
| `header3_remote_port` | int | `0` |

Semantics:

* Ordered by first-seen unique remote IP for that block on the client
  (same order as local relevance ranks 1 / 2 / 3).
* Rank 1 remains `header_remote_*` (unchanged).
* Rank 2 → `header2_*`, rank 3 → `header3_*`.
* If fewer than 2 or 3 unique announcers were seen before the sample is
  emitted, leave the unused fields empty / 0.
* Ports are the connectionId remote ports from the header events
  (usually service ports on announcing peers). Apply the same address
  obfuscation as `header_remote_addr` if the client obfuscates.

Example (abbreviated):

```json
{
  "block_hash": "…",
  "block_number": 13945164,
  "block_size": 7421,
  "header_remote_addr": "195.49.96.164",
  "header_remote_port": 3001,
  "header2_remote_addr": "203.29.240.162",
  "header2_remote_port": 6000,
  "header3_remote_addr": "",
  "header3_remote_port": 0,
  "block_remote_addr": "195.49.96.164",
  "block_remote_port": 3001
}
```

## Backend tasks

1. **API schema:** accept the four fields as optional (defaults `""` / `0`)
   so older clients keep working.
2. **Persist** on the blocksample / ingest row (names can match the JSON).
3. **`block_prop` import:** for each of header2 / header3, if addr is
   non-empty, resolve relay (same lookup as 1st header / body) and write
   two nullable relay id columns, e.g. `header2_relay_id`,
   `header3_relay_id`.
4. **Analytics:** compute peer relevance from stored samples
   (counts / points over time windows, optionally weighted by
   `block_size`). No separate relevance table required for v1.
5. **Reject unknown-field 422:** if the API is strict, add the fields
   before new clients roll out.

## What stays unchanged

* Body fields: still first successful body server only.
* Peer events: still `POST /submit/peerevent` (see
  `backend-peer-events.md`). Session fields are optional; ignore `duplex`.
* No `/submit/peerrelevance`.
* No requirement to store Cooling or CM counters from this handoff.

## Client rollout note

Backend ingest + `block_prop` columns are ready (**2026-09-17**).
Client v0.0.41+ sends the four fields (defaults when missing announcers).

## Suggested scoring (server-side, same as local)

Optional, for dashboards / post-analysis only:

| Signal | Points |
|--------|--------|
| 1st header (`header_remote_*`) | 10 |
| 2nd header (`header2_*`) | 5 |
| 3rd header (`header3_*`) | 3 |
| 1st body (`block_remote_*`) | 10 |

Windowing and aggregation are a backend choice (per epoch, rolling 30m,
etc.). Client local metrics keep a fixed sliding 30m for SPO display.
