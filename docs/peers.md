# Tracking peer sessions

The client watches cardano-node tracer logs and builds **connection sessions**,
not an IP-keyed temperature map. Block samples stay the first data type we
parse and report. Peer sessions are the second.

A session is one TCP `connectionId` (local + remote addr/port) in one node
generation (cardano-node / diffusion start, not a chain epoch).
HandshakeSuccess opens it. InboundGovernor and PeerSelection temperatures
fill it. MuxErrored, orderly demote, CoolingToCold, or a node restart close it.

## Decisions (2026-09-20)

1. Key by **connection**, not by remote IP. Same IP can be we-dialed `:3001`
   and they-dialed `:54329` at once. Same IP:port can die and come back as
   session 2.
2. **HandshakeSuccess** is session open and the n2n sign of life
   (`n2n_version`, `diffusion_mode`, `peer_sharing`, `peras_support`).
3. Two temperature tracks on the same session when `connectionId` matches:
   `ig_temperature` (InboundGovernor Remote) and `outbound_temperature`
   (PeerSelection StatusChanged or Selection Promote/Demote *Done).
4. **Do not** treat `InboundGovernor.Local` as outbound n2n. That namespace
   is n2c / unix. Outbound n2n is PeerSelection.
5. `we_dialed` is true after StatusChanged `ColdToWarm`, PromoteColdDone,
   or a ChainSync/BlockFetch **client** line on that connection. Otherwise
   unknown or they dialed.
6. Useful is a **local list flag** only: Hot on either track, or Warm held
   for `peer_event_stable_seconds` (default 15). Backend always gets open
   and close, including short HS flicker.
7. **Do not** submit or name CM `duplex` / `fullDuplex` / `unidirectional`.
   Drop `duplex` from `/peers` and journal lines.
8. Restart: `Server.Remote.Stopped` / `Shutdown` close every open session
   with `close_reason=node_restart`. `Server.Remote.Started` (debounced with
   Local.Started / `Startup.DiffusionInit`) increments `node_generation` and
   submits `event_role=node_restart`. Not a Cardano chain epoch.
9. Traceroute / RTT stay later. Trigger would be first Warm. Not in these
   logs (`TraceEmitDeltaQ` is empty).
10. Outbound n2n is **not** InboundGovernor. `Promote*Done` / `Demote*Done`
    under `Net.PeerSelection.Selection` are the outbound governor steps
    (needed when `Actions.StatusChanged` is missing). `ChainSync.Client`
    and `BlockFetch.Client` also mark that session we-dialed and outbound
    Hot. Those IPs were showing up as `/peers` relevance orphans.
11. `/peers` has `opened_at` and `last_signal`. **Do not** export
    `first_seen` (it was a copy of `opened_at`).
12. Handshake options (`n2n_version`, `diffusion_mode`, `peer_sharing`,
    `peras_support`) come **only** from HandshakeSuccess on that connection.
    Null means we did not see that HS (typical when the client attaches
    after the TCP session already exists). Not "feature off".

## What is submitted (`POST /submit/peerevent`)

Same endpoint as v0.0.42. Four `change_type` values stay for older backends.
New fields are omit-none.

| `event_role` | Meaning | Typical `change_type` |
|--------------|---------|------------------------|
| `open` | HandshakeSuccess (or first temperature if we attached mid-run) | `cold_to_warm` |
| `temperature` | IG or outbound Warm/Hot change | `warm_to_hot` / `hot_to_warm` |
| `close` | Session ended | `warm_to_cold` |
| `node_restart` | Node started from empty. Dummy remote `0.0.0.0`. | `warm_to_cold` |

| `close_reason` | Kind |
|----------------|------|
| `ig_mux_error` / `ig_responder_error` / `handler_error` | unexpected |
| `demoted_cold` / `cooling_to_cold` | planned churn |
| `node_restart` | cardano-node restart |
| `ttl` | no leave line for `peer_signal_ttl_seconds` (default 1800) |

Ephemeral remote ports (`>= 32768`) are submitted as `0`. Listen ports are kept.

## Log namespaces we use

**Session truth**

- `Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess`
- `Net.InboundGovernor.Remote.PromotedToWarmRemote` / `PromotedToHotRemote`
- `Net.InboundGovernor.Remote.DemotedToWarmRemote` / `DemotedToColdRemote`
- `Net.PeerSelection.Actions.StatusChanged`
- `Net.PeerSelection.Selection.PromoteColdDone` / `PromoteWarmDone`
  (and BigLedgerPeerDone variants)
- `Net.PeerSelection.Selection.DemoteHotDone` / `DemoteWarmDone`
  (and BigLedgerPeerDone variants)
- `ChainSync.Client.DownloadedHeader` and `BlockFetch.Client.*` (outbound
  Hot; we are the initiator)
- `Net.InboundGovernor.Remote.MuxErrored` / `ResponderErrored`
- `Net.ConnectionManager.Remote.ConnectionHandler.Error`
- `Net.Server.Remote.Stopped` / `Net.Server.Local.Stopped`
- `Net.ConnectionManager.Remote.Shutdown`
- `Net.Server.Remote.Started` / `Net.Server.Local.Started`
- `Startup.DiffusionInit` (optional non-Net restart confirm)

**Not used to drive the FSM:** ConnectionManagerCounters, Mux.State,
TraceEmitDeltaQ, MaturedConnections. HandshakeQuery is ignored (query-only).
PromoteColdFailed stays out of scope.

Parent `Net.ConnectionManager.Remote` should stay Info **without**
`maxFrequency`. Throttle **only** `ConnectionManagerCounters`.

## Operator endpoints

Enable with `local_metrics_enabled: true` (default bind `127.0.0.1:14041`).

```bash
curl -s http://127.0.0.1:14041/peers
curl -s http://127.0.0.1:14041/peers?all=1
curl -s http://127.0.0.1:14041/peers/sessions
curl -s http://127.0.0.1:14041/metrics
```

`GET /peers` is **useful open** sessions (IP, listen port if known, ig and
outbound temperatures, HS options, `opened_at`, `last_signal`, local 30m
header/body relevance). No `duplex` field. No `first_seen`. Outbound Hot
comes from PeerSelection *Done / StatusChanged or from header/body
**client** lines.

`?all=1` or `/peers/sessions` includes short HS that are not yet useful.

Prometheus: `openblockperf_sessions_open`, `openblockperf_sessions_useful`,
`openblockperf_node_generation`, `openblockperf_sessions_closed{reason=...}`.
Not node Warm/Hot box names.

## Config

```json
{
  "peer_event_stable_seconds": 15,
  "peer_signal_ttl_seconds": 1800,
  "peer_traceroute_enabled": false,
  "peer_count_stats_interval": 5,
  "peer_prune_idle_seconds": 600,
  "local_metrics_enabled": false,
  "local_metrics_bind": "127.0.0.1",
  "local_metrics_port": 14041
}
```

`peer_event_stable_seconds` only gates the useful flag / `/peers` list.
Handshake open and close are always submitted.

See [local-peer-metrics.md](local-peer-metrics.md) and
[backend-peer-events.md](backend-peer-events.md).
