# Backend handoff: client peer-event reporting

**Audience:** backend agent / API maintainers
**Endpoint:** `POST /submit/peerevent`
**Goal:** one comparable peer lifecycle stream from every client (no per-operator
detail levels), plus optional handshake capability flags.

Related: blocksample 2nd/3rd announcers in `docs/backend-blocksample.md`.
Plan overview: `docs/peer-data-plan.md`.

---

## 1. What every client sends

All installs use the same temperature policy (debounce via
`peer_event_stable_seconds`, default 15). There is **no** `peer_events_level`.

| `change_type` | Meaning |
|---------------|---------|
| `cold_to_warm` | Stable **Warm** enter |
| `warm_to_hot` | Stable **Hot** enter |
| `hot_to_warm` | Left Hot, still Warm |
| `warm_to_cold` | Left Hot/Warm path ending Cold (Cooling collapsed) |

Cooling types are never submitted.

---

## 2. Payload

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
  "duplex": false,
  "n2n_version": 14,
  "diffusion_mode": "InitiatorAndResponderDiffusionMode",
  "peer_sharing": "PeerSharingEnabled",
  "peras_support": "PerasUnsupported"
}
```

### Fields

| Field | Notes |
|-------|--------|
| `duplex` | bool; Warm/Hot on **both** inbound and outbound at submit time (temperature duplex, not CM Bi-Dir) |
| `remote_port` | outbound: service port; inbound: always `0` |
| `n2n_version` | optional int from HandshakeSuccess; `null` if unknown |
| `diffusion_mode` | optional string; `null` if unknown |
| `peer_sharing` | optional string; `null` if unknown |
| `peras_support` | optional string; `null` if unknown |

Handshake fields come from
`Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess` when the
node actually logs it. Under a parent `maxFrequency: 0.0167` they are often
sparse. Treat `null` as unknown, not as “unsupported”.

`exclude_none` on the client HTTP layer omits null enrichment fields from JSON.

---

## 3. Backend tasks

1. Accept optional handshake fields (`n2n_version`, `diffusion_mode`,
   `peer_sharing`, `peras_support`) with null/absent = unknown.
2. Keep accepting `duplex` (bool, default false).
3. Expect **all four** `change_type` values from current clients (including
   `cold_to_warm`). Do not assume mid-only Hot traffic anymore.
4. `remote_port == 0` means unknown / inbound ephemeral suppressed.
5. Optional traceroute remains a future separate payload; not part of peerevent.

---

## 4. Compatibility

* Old clients without handshake fields still work.
* Old `peer_events_level` on the client config is ignored; behaviour is the
  unified policy above.
* Strict APIs must add the optional fields before new clients roll out widely
  (same pattern as `duplex` / `header2_*`).
