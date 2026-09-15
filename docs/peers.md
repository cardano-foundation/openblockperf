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

## Local stats

`peerCountStats` is logged a few seconds after the local peer counters
change (`peer_count_stats_interval` is that settle/debounce delay; default
`5`, `0` disables). Idle fully-inactive peers are pruned after
`peer_prune_idle_seconds`.

## Operator config (examples)

```json
{
  "peer_events_level": "mid",
  "peer_event_stable_seconds": 15,
  "peer_traceroute_enabled": false,
  "peer_count_stats_interval": 5,
  "peer_prune_idle_seconds": 600
}
```

Environment variables use the `OPENBLOCKPERF_` prefix, for example
`OPENBLOCKPERF_PEER_EVENTS_LEVEL=high`.
