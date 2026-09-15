# Backend handoff: client peer-event reporting changes

**Audience:** backend agent / API maintainers  
**Client change area:** openblockperf peer temperature parsing and `/submit/peerevent`  
**Goal:** store and analyze how a relay sits in the network (especially **Hot** peers for block-sample correlation), without ingesting high-frequency Cold/Warm/Hot flicker or Cooling teardown noise.

---

## 1. What the client still sends

Endpoint unchanged: `POST /submit/peerevent`.

Existing reportable `change_type` values (unchanged strings):

| `change_type` | Meaning from client |
|---------------|---------------------|
| `cold_to_warm` | Stable **Warm** enter (only when `peer_events_level=high`) |
| `warm_to_hot` | Stable **Hot** enter (default `mid` and `high`) |
| `hot_to_warm` | Left Hot, still Warm |
| `warm_to_cold` | Left Hot/Warm path ending Cold (includes collapse of Hot→Cooling→Cold) |

Cooling transitions (`hot_to_cooling`, `warm_to_cooling`, `cooling_to_cold`) are **parsed client-side only** and **never submitted**.

Default client level is **`mid`**: only Hot enters (debounced) and leaves. Warm enters are not submitted unless the operator sets `high`.

Debounce: enter reports wait `peer_event_stable_seconds` (default 15). Leaves for a previously reported temperature are immediate. Intermediate Warm that quickly becomes Hot is not submitted as Warm.

---

## 2. Payload fields: what changed

Conceptual body (Python `PeerEventRequest`):

```json
{
  "at": "2026-09-15T19:41:17.123456+00:00",
  "direction": "inbound" | "outbound",
  "local_addr": "<obfuscated if needed>",
  "local_port": 3001,
  "remote_addr": "<remote IP>",
  "remote_port": 0,
  "change_type": "warm_to_hot",
  "last_seen": "2026-09-15T19:41:17.123456+00:00",
  "last_state": "Hot",
  "duplex": false
}
```

### 2.1 New field: `duplex` (bool, default `false`)

* **Meaning:** at submit time, this remote IP is Warm or Hot on **both** inbound and outbound.
* **Backend action:** accept the field (optional with default `false` is enough). Store it if useful for graphing “full duplex” peers; safe to ignore initially.
* **If the API rejects unknown fields today:** add `duplex: bool = False` (or equivalent) so older clients without the field still work and new clients do not 422.

### 2.2 Semantic change: `remote_port` for inbound

* **Outbound:** `remote_port` remains the remote **service** port (e.g. 3001, 6000).
* **Inbound:** client now reports **`remote_port = 0`** on purpose. Inbound log lines often carry ephemeral client ports; those must not be treated as relay listen ports.
* **Backend implication:** an inbound peer event is keyed meaningfully by **`remote_addr` (+ direction / client id)**, **not** by `ip:port` as a Cardano relay identity. You cannot reliably map an inbound peer event to a known relay catalog entry that is defined as `ip:port` unless you only use the IP (ambiguous if multiple relays share an IP).
* **Recommendation:**  
  - Outbound: keep relating to relays via `remote_addr:remote_port` when port ≠ 0.  
  - Inbound: relate by `remote_addr` only (or mark port as unknown). Do not invent a relay from ephemeral ports.

### 2.3 Unchanged fields

`at`, `direction`, `local_addr`, `local_port`, `remote_addr`, `change_type`, `last_seen`, `last_state` keep the same roles. `last_state` is the collapsed temperature string (`Warm` / `Hot` / `Cold`), never `Cooling`.

---

## 3. Volume and semantics vs previous client

| Before | After |
|--------|--------|
| Almost every StatusChanged / Promote / Demote submitted immediately | Only debounced stable enters + immediate leaves of reported temps |
| Cooling parse often failed / peers stuck Hot in local stats | Cooling tracked locally; leave collapsed to reportable types |
| Peer identity `(remote_ip, remote_port)` | Peer identity **remote IP**; inbound port not used |
| No duplex signal | Optional `duplex` flag |
| Very high submit rate possible | Much lower; mid ≈ Hot lifecycle only |

Backend storage does **not** need near-realtime peer chatter. Prefer treating each submitted event as a **stable edge lifecycle** marker (became Hot / left Hot, etc.).

---

## 4. How to use this with block samples

Block samples already identify which peer delivered headers/blocks. Correlate samples with peers that have an open **Hot** interval (`warm_to_hot` … until `hot_to_warm` / `warm_to_cold`) for the same client and remote IP (and outbound port when present).

Inbound Hot peers: correlate by IP only.

---

## 5. Suggested backend tasks

1. **Accept `duplex`** on peer-event ingest (optional boolean, default false).  
2. **Document / code** that `remote_port == 0` means “port unknown / inbound ephemeral suppressed”.  
3. **Stop assuming** every peer row is a unique relay `ip:port` when `direction=inbound` or `remote_port=0`.  
4. **Do not** expect Cooling change types from the client.  
5. Optional later: store duplex and IP-only inbound edges in whatever peer graph you build; no client ultra-level yet.

---

## 6. Client config reference (operators)

* `peer_events_level`: `off` | `low` | `mid` | `high` (default `mid`)  
* `peer_event_stable_seconds`: default `15`  
* `peer_traceroute_enabled`: orthogonal; traceroute payload not part of this handoff yet  
* `peer_prune_idle_seconds`: local list hygiene only (not an API field)

---

## 7. Compatibility summary

* **Breaking for strict APIs:** new `duplex` field if extras are forbidden → add optional field.  
* **Behavioral breaking for analytics:** fewer events; inbound ports no longer ephemeral; identity is IP-centric.  
* **Non-breaking for loose APIs:** same endpoint and same four `change_type` strings; ignore `duplex` until ready.
