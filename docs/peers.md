# Tracking peers

The client watches cardano-node tracer logs for peer temperature changes
(Cold / Warm / Hot) and reports a **debounced** view of who this node is
actually connected to.

Cardano peer temperatures (simplified):

* **Cold** – known peer, no useful connection yet (not reported as an “active” peer)
* **Warm** – TCP + handshake / established connection, not fully active
* **Hot** – active mini-protocols (ChainSync, BlockFetch, …) – this is what
  block samples are correlated against
* **Cooling** – short teardown state inside the node; tracked only inside the
  client, never sent to the backend

## Reporting levels (`peer_events_level`)

| Level | Meaning |
|-------|---------|
| `off` | Do not parse or submit peer temperature events |
| `low` | Keep a local peer picture for stats; do not submit temperature changes |
| `mid` (default) | Submit **stable Hot** enters (after debounce) and Hot leaves immediately |
| `high` | Like `mid`, plus **stable Warm** enters |

`peer_traceroute_enabled` is a separate switch (any level except when peer
events are off). Traceroute enrichment is optional and not required for
normal operation.

### Debounce (`peer_event_stable_seconds`, default `15`)

A Warm/Hot **enter** is submitted only if that temperature stays in place for
N seconds. Short Cold→Warm→Hot flickers collapse to a single Hot enter when
possible. **Leaves** are submitted immediately once a previously reported
temperature is gone.

## Inbound vs outbound

* **Outbound** – this node initiated toward a remote relay (service port kept)
* **Inbound** – remote side toward this node (ephemeral remote ports are **not**
  used as identity; reports use `remote_port = 0`)
* **Duplex** – same remote IP is Warm/Hot on both directions at once
  (`duplex: true` on the peer event)

Peers are keyed by **remote IP**, not by ephemeral `ip:port`.

## Local stats (diagnostics)

`peerCountStats` is logged a few seconds after counters change
(`peer_count_stats_interval`, default `5`; `0` disables).

Fields:

* `in_warm` / `in_hot` / … – **live** FSM (every parsed event; nearer node/gLiveView)
* `*_reported` – passed debounce and submitted (operator export / API truth)
* `*_pending` – waiting for `peer_event_stable_seconds`
* `duplex` / `duplex_reported` – live vs both sides reported active

When comparing to gLiveView Warm/Hot, use **live**. When asking “what did we
tell the backend?”, use **reported**. Large `live - reported` with high
`pending` means debounce is still absorbing churn.

See [local-peer-metrics.md](local-peer-metrics.md) for the planned localhost
Prometheus/JSON endpoint (default port `14041`) and 30‑minute relevance window.

## Operator config (examples)

```json
{
  "peer_events_level": "mid",
  "peer_event_stable_seconds": 15,
  "peer_traceroute_enabled": false,
  "peer_count_stats_interval": 5,
  "peer_prune_idle_seconds": 600,
  "local_metrics_enabled": false,
  "local_metrics_bind": "127.0.0.1",
  "local_metrics_port": 14041
}
```

Environment variables use the `OPENBLOCKPERF_` prefix, for example
`OPENBLOCKPERF_PEER_EVENTS_LEVEL=high`.
