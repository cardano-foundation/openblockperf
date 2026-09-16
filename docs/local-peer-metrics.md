# Local peer metrics and relevance (design)

Status: decisions locked for implementation. Local HTTP export is not
shipped yet; diagnostics in `peerCountStats` land first.

## Goals

1. Keep debounced peer reporting to the backend (noise control).
2. Give SPOs / Koios gLiveView a local peer list that matches what we
   consider “real” (reported/debounced), not raw flicker.
3. Enrich peers with blocksample relevance over a fixed comparable window.
4. Optionally expose Prometheus + JSON on a dedicated local port.

## Locked decisions

### Export set

Operator-facing peer lists export **reported/debounced** peers only
(Warm/Hot that passed `peer_event_stable_seconds`, still held as reported).

While developing, `peerCountStats` also logs **live** and **pending**
counts so we can see what debounce cuts off versus cardano-node / gLiveView.

### Local HTTP endpoint (planned)

| Setting | Default | Notes |
|---------|---------|--------|
| enabled | `false` | Opt-in |
| bind | `127.0.0.1` | SPO may set any interface |
| port | `14041` | Avoid node `12798` and Prometheus `9090` |

Surfaces:

* Prometheus text exposition
* JSON peer table (`?format=json` or `/peers.json`)

### Relevance window

* **Sliding 30 minutes** (not configurable). Spreads backend load; imperfect
  alignment across clients is acceptable.
* Every ~30 minutes the client submits a relevance snapshot to a **new**
  backend endpoint (to be specified with the backend agent).

### Header / body scoring (local window)

| Signal | Rule | Points |
|--------|------|--------|
| Header announcer 1st | counted + scored | 10 |
| Header announcer 2nd | local only (not stored as blocksample primary) | 5 |
| Header announcer 3rd | local only | 3 |
| Body server (1st) | node usually logs only one successful fetch | 10 |

Backend relevance report should include:

* `headers_count` (and optionally 2nd/3rd counts)
* `header_points` (sum of 10/5/3 in the window)
* `bodies_count` / `body_points` (first body servers in the window)

Blocksample API to the backend stays as today (first header / first body).
2nd/3rd announcers are for local relevance (+ the periodic relevance POST).

### Remote IPv4 vs IPv6

One row per **remote IP**. The node and client cannot know that an IPv4 and
IPv6 address are the same remote process without external catalog data.
Do not merge locally in v1. (Local dual-stack registration of **this**
relay is unrelated.)

### Duplex tag

Local/export `duplex`: same remote IP is Warm/Hot on both inbound and
outbound (temperature-derived). Distinct from ConnectionManager Bi-Dir /
full-Duplex counters in gLiveView.

## Implementation sequence

1. **Diagnostics** – `peerCountStats` live / reported / pending (this change)
2. **A0** – optional localhost server on `:14041`, JSON + Prom, reported peers
3. **A1** – sliding 30m relevance; 2nd/3rd header parsing for local scores
4. **A2** – Koios contract doc + backend relevance endpoint handoff
5. **B** – geo enrich pull-back into local list
6. **C** – traceroute + Web UI (later)

## Comparing to gLiveView

| gLiveView | openblockperf |
|-----------|----------------|
| Node Warm/Hot counters | `*_live` in peerCountStats |
| (no debounced view) | `*_reported` (export / API truth) |
| Bi-Dir / Duplex (handshake / use) | temperature duplex-by-IP |
| No per-peer usefulness | 30m header/body relevance |

Expect `*_live` nearer node counters; `*_reported` lower when churn is high.
