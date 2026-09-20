# Local peer metrics and relevance (design)

Status: **session export** on `/peers` (useful open sessions) plus sliding
30m relevance on the client. Relevance is **local only** – not POSTed.

Upstream relevance / 2nd–3rd analysis: extend blocksamples
(`docs/backend-blocksample.md`). Plan overview: `docs/peer-data-plan.md`.

## Goals

1. Report connection sessions to the backend (open / temperature / close / epoch).
2. Give SPOs a local peer list of **useful open** sessions, not 2s HS flicker.
3. Enrich local rows with blocksample relevance over a fixed 30m window.
4. Optionally expose Prometheus + JSON on a dedicated local port.

## Locked decisions

### Export set

Operator-facing `GET /peers` exports **useful open sessions**:
Hot on ig or outbound, or Warm held for `peer_event_stable_seconds`.
Each row includes `session_id`, `epoch_id`, `we_dialed`, ig/outbound
temperatures, HS options, `first_seen`, `last_signal`.

`GET /peers?all=1` or `/peers/sessions` includes all currently open
sessions (short HS too).

**Do not** expose a `duplex` field. Soft TTL (`peer_signal_ttl_seconds`,
default 30m) closes stale open sessions when leave lines are missing.

### Local HTTP endpoint

| Setting | Default | Notes |
|---------|---------|--------|
| `local_metrics_enabled` | `false` | Opt-in |
| `local_metrics_bind` | `127.0.0.1` | SPO may set any interface |
| `local_metrics_port` | `14041` | Avoid node `12798` and Prometheus `9090` |

```bash
curl -s http://127.0.0.1:14041/health
curl -s http://127.0.0.1:14041/peers | jq .
curl -s http://127.0.0.1:14041/peers?all=1 | jq .
curl -s http://127.0.0.1:14041/metrics
```

### Relevance window (local only)

* Sliding **30 minutes** (not configurable), for SPO / local JSON.
* **Do not** POST relevance snapshots. That endpoint plan is cancelled
  (`docs/backend-peer-relevance.md`).
* Backend derives relevance from blocksamples joined to session intervals.

### Header / body scoring (local window)

| Signal | Rule | Points |
|--------|------|--------|
| Header announcer 1st | counted + scored | 10 |
| Header announcer 2nd | local score; also on blocksample submit | 5 |
| Header announcer 3rd | local score; also on blocksample submit | 3 |
| Body server (1st) | node usually logs only one successful fetch | 10 |

### Remote IPv4 vs IPv6

One session per connectionId. Do not merge IPv4 and IPv6 into one peer
on the client.

## Prometheus

Gauges: `openblockperf_sessions_open`, `openblockperf_sessions_useful`,
`openblockperf_epoch`, `openblockperf_session_temperature{track,state}`,
`openblockperf_sessions_closed{reason}`.

Not `in_hot_live` named like the node.

## Comparing to gLiveView

We do **not** aim to match gLiveView Warm/Hot or Bi-Dir boxes.
Use `/peers` plus `last_signal` and local relevance for “who is useful”.
Use backend sessions for replay and signs of life.
