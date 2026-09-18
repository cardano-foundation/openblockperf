# Tracking peers

The client watches cardano-node tracer logs for peer temperature changes
(Cold / Warm / Hot) and reports a **debounced** view of who this node is
actually connected to. Every participant uses the **same** report set so the
backend can interpret absences correctly.

Cardano peer temperatures (simplified):

* **Cold** – known peer, no useful connection yet
* **Warm** – TCP + handshake / established connection, not fully active
* **Hot** – active mini-protocols (ChainSync, BlockFetch, …) – this is what
  block samples are correlated against
* **Cooling** – short teardown state inside the node; tracked only inside the
  client, never sent to the backend

## What is submitted (same for all clients)

| `change_type` | Meaning |
|---------------|---------|
| `cold_to_warm` | Stable Warm enter (after debounce) |
| `warm_to_hot` | Stable Hot enter (after debounce) |
| `hot_to_warm` | Left Hot, still Warm |
| `warm_to_cold` | Left Hot/Warm path ending Cold (Cooling collapsed) |

### Debounce (`peer_event_stable_seconds`, default `15`)

A Warm/Hot **enter** is submitted only if that temperature stays in place for
N seconds. Short Cold→Warm→Hot flickers collapse to a single Hot enter when
possible. **Leaves** are submitted immediately once a previously reported
temperature is gone.

### Traceroute (`peer_traceroute_enabled`, default `false`)

Separate optional switch. Not implemented yet. Does not change temperature
reporting.

## Handshake enrichment (ConnectionManager)

`Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess` is parsed
when present. Latest options per remote IP are cached and attached to later
peerevents / `/peers` rows:

* `n2n_version`
* `diffusion_mode` (e.g. `InitiatorAndResponderDiffusionMode`)
* `peer_sharing`
* `peras_support`

Ephemeral remote ports (`>= 32768`) are stored as `0` (not a relay listen port).

**TraceOptions note:** many default node configs set
`Net.ConnectionManager.Remote` with `maxFrequency: 0.0167`, which starves
HandshakeSuccess (~tens per hour). Prefer Info **without** that parent throttle
(or a child override for HandshakeSuccess). See
`logs/node-logs_Net-namespace/` for a throttled 1h sample vs an upcoming
unthrottled capture.

## Inbound vs outbound

* **Outbound** – this node initiated toward a remote relay (service port kept)
* **Inbound** – remote side toward this node (ephemeral remote ports are **not**
  used as identity; reports use `remote_port = 0`)
* **Duplex** – same remote IP is Warm/Hot on both directions at once
  (`duplex: true` on the peer event). This is temperature duplex, not
  ConnectionManager / gLiveView Bi-Dir.

Peers are keyed by **remote IP**, not by ephemeral `ip:port`.

## Abrupt connection loss (count-down)

Orderly `DemotedToColdRemote` / StatusChanged Cooling often **does not**
follow a hard drop. Without these, live Warm/Hot stay high vs gLiveView /
`InboundGovernorCounters`.

The client also treats these as inbound (or outbound for
`OutboundError`) leave to Cold, same as demote:

* `Net.InboundGovernor.Remote.MuxErrored`
* `Net.InboundGovernor.Remote.ResponderErrored`
* `Net.ConnectionManager.Remote.ConnectionHandler.Error`

On `Net.ConnectionManager.Remote.Shutdown` or `Net.Server.Remote.Stopped`
the peer FSM and handshake cache are wiped so a node restart does not keep
ghosts.

When comparing to gLiveView: **Bi-Dir / Duplex** there are CM
`duplex` / `fullDuplex` counters, not temperature `duplex`.

## Local stats (diagnostics)

`peerCountStats` is logged a few seconds after counters change
(`peer_count_stats_interval`, default `5`; `0` disables).

Fields:

* `in_warm` / `in_hot` / … – **live** FSM (every parsed event; nearer node/gLiveView)
* `*_reported` – passed debounce and submitted (operator export / API truth)
* `*_pending` – waiting for `peer_event_stable_seconds`
* `duplex` / `duplex_reported` – live vs both sides reported active
* `handshakes_cached` – HandshakeSuccess cache size

When comparing to gLiveView Warm/Hot, use **live**. When asking “what did we
tell the backend?”, use **reported**.

See [local-peer-metrics.md](local-peer-metrics.md) for the localhost
Prometheus/JSON endpoint (default port `14041`, opt-in) and the sliding
30‑minute relevance scores on `/peers`.

Enable locally:

```json
"local_metrics_enabled": true,
"local_metrics_bind": "127.0.0.1",
"local_metrics_port": 14041
```

```bash
curl -s http://127.0.0.1:14041/peers
curl -s http://127.0.0.1:14041/metrics
```

## Operator config (examples)

The installer writes these keys into `${INSTALL_DIR}/config.json` with the
defaults below so you can edit them in place.

```json
{
  "peer_event_stable_seconds": 15,
  "peer_traceroute_enabled": false,
  "peer_count_stats_interval": 5,
  "peer_prune_idle_seconds": 600,
  "local_metrics_enabled": false,
  "local_metrics_bind": "127.0.0.1",
  "local_metrics_port": 14041
}
```

Legacy `peer_events_level` in an old `config.json` is ignored (`extra=ignore`).

Environment variables use the `OPENBLOCKPERF_` prefix, for example
`OPENBLOCKPERF_PEER_EVENT_STABLE_SECONDS=30`.
