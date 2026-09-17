# Local peer metrics and relevance (design)

Status: **A0 + A1 shipped** (local metrics HTTP + sliding 30m relevance
on the client). Relevance is **local only** – not POSTed.

Upstream relevance / 2nd–3rd analysis: extend blocksamples
(`docs/backend-blocksample.md`). Plan overview: `docs/peer-data-plan.md`.

## Goals

1. Keep debounced peer reporting to the backend (noise control).
2. Give SPOs a local peer list that matches what we consider “real”
   (reported/debounced), not raw flicker.
3. Enrich local peers with blocksample relevance over a fixed 30m window.
4. Optionally expose Prometheus + JSON on a dedicated local port.

## Locked decisions

### Export set

Operator-facing peer lists export **reported/debounced** peers only
(Warm/Hot that passed `peer_event_stable_seconds`, still held as reported).

While developing, `peerCountStats` also logs **live** and **pending**
counts so we can see what debounce cuts off versus cardano-node / gLiveView.

### Local HTTP endpoint

| Setting | Default | Notes |
|---------|---------|--------|
| `local_metrics_enabled` | `false` | Opt-in |
| `local_metrics_bind` | `127.0.0.1` | SPO may set any interface |
| `local_metrics_port` | `14041` | Avoid node `12798` and Prometheus `9090` |

The installer writes these three keys into `config.json` with the defaults
above. Set `local_metrics_enabled` to `true` and restart the service to
expose the endpoints.

Surfaces (when enabled):

* `GET /metrics` – Prometheus text (aggregate live/reported/pending gauges)
* `GET /peers` or `/peers.json` – JSON peer table (**reported** peers only)
* `GET /health` – `ok`

```bash
# on the relay, after enabling local_metrics_enabled
curl -s http://127.0.0.1:14041/health
curl -s http://127.0.0.1:14041/peers | jq .
curl -s http://127.0.0.1:14041/metrics
```

### Relevance window (local only)

* Sliding **30 minutes** (not configurable), for SPO / local JSON.
* **Do not** POST relevance snapshots. That endpoint plan is cancelled
  (`docs/backend-peer-relevance.md`).
* Backend will derive relevance from blocksamples once 2nd/3rd announcer
  fields ship (`docs/backend-blocksample.md`).

### Header / body scoring (local window)

| Signal | Rule | Points |
|--------|------|--------|
| Header announcer 1st | counted + scored | 10 |
| Header announcer 2nd | local score; also planned on blocksample submit | 5 |
| Header announcer 3rd | local score; also planned on blocksample submit | 3 |
| Body server (1st) | node usually logs only one successful fetch | 10 |

Local `/peers` exposes these scores. Backend post-analysis uses the same
point idea on stored samples after `header2_*` / `header3_*` exist.

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

1. **Diagnostics** – `peerCountStats` live / reported / pending (**done**)
2. **A0** – optional localhost server on `:14041`, JSON + Prom (**done**)
3. **A1** – sliding 30m relevance; 2nd/3rd header parsing for local scores (**done**)
4. **Blocksample 2nd/3rd** – client fields + backend `block_prop` lookups
   (Phase 2/3 in `peer-data-plan.md`)
5. **B** – geo enrich pull-back into local list (later)
6. **C** – traceroute + Web UI (later)
7. **CM light** – ConnectionManagerCounters for local gauges (later)

## Comparing to gLiveView

| gLiveView | openblockperf |
|-----------|----------------|
| Node Warm/Hot counters | `*_live` in peerCountStats |
| (no debounced view) | `*_reported` (export / API truth) |
| Bi-Dir / Duplex (handshake / use) | temperature duplex-by-IP |
| No per-peer usefulness | local 30m header/body relevance |

Expect `*_live` nearer node counters; `*_reported` lower when churn is high.
