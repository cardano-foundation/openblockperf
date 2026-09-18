# OpenBlockperf

A CLI tool and systemd service that captures and shares network metrics from a
[Cardano](https://developers.cardano.org/docs/operators/) relay node.

The client collects selected tracer and peering data from a local relay so
stake pool operators can contribute to a shared view of block propagation
and connectivity. It is intended for relay nodes that sit between a stake pool
producer and the rest of the network. Running it on a producer is possible
but not recommended. In normal operation it runs as a systemd service.

## Release notes
- v0.0.42 - 2026-09-18
  - peer events unified: every client reports the same temperature lifecycle
    (`cold_to_warm`, `warm_to_hot`, `hot_to_warm`, `warm_to_cold`); no levels
  - legacy `peer_events_level` in config is ignored
  - HandshakeSuccess enrichment on peerevent submit when CM logs are present:
    optional `n2n_version`, `diffusion_mode`, `peer_sharing`, `peras_support`
  - abrupt connection loss (`MuxErrored`, `ConnectionHandler.Error`,
    `ResponderErrored`) counts as Cold leave so live peer counts track the node
  - CM / server shutdown wipes the peer FSM (no restart ghosts)
  - still no dial-fail / PromoteColdFailed submits
- v0.0.41 - 2026-09-17
  - blocksample submit adds optional 2nd/3rd header announcers:
    `header2_remote_addr/port`, `header3_remote_addr/port` (empty/`0` when missing)
  - same IP obfuscation for header2/header3 as for the primary header
  - backend can resolve two more relays on `block_prop`; no peerrelevance endpoint
- v0.0.40 - 2026-09-15
  - peer events: debounced reporting by level (`off` / `low` / `mid` / `high`, default `mid` = stable Hot)
  - peer enters wait `peer_event_stable_seconds` (default 15); leaves reported immediately
  - Cooling tracked client-side only; not submitted to the backend
  - peers keyed by remote IP; inbound reports `remote_port=0` (no ephemeral ports)
  - peer submit payload adds optional `duplex` when both directions are Warm/Hot
  - journal: only submitted peer lines (`IP direction change_type duplex=...`), no parse spam
  - `peerCountStats` logs after counters settle (`peer_count_stats_interval` default 5s); `0` disables
  - CLI: global `--version` / `-V` in addition to `blockperf version`
  - optional local metrics HTTP (`local_metrics_enabled`, default port `14041`):
    `/peers` JSON (reported peers) and `/metrics` Prometheus gauges
  - sliding 30m peer relevance (header 1st/2nd/3rd points 10/5/3, body 10);
    local only (`/peers` + journal); not POSTed
- v0.0.39 - 2026-09-09
  - dual-stack IP registration: prove IPv4/IPv6 via `/registration/ip/proof`, submit proof tokens
  - CLI uses `OPENBLOCKPERF_CONFIG` when `--config` is omitted (installer wrapper/profile sets it)
  - API HTTP errors print backend `detail` text (e.g. expressive 400s on register-ip)
  - service mode fails over on HTTP 5xx (e.g. 503 queue full) to the next edge
  - installer checks for an existing install directory before the wizard
  - installer retries relay API key registration up to three times
  - compact blocksample journal lines: short hash, block number, edge name
  - compact peer-event journal lines: remote IP and old > new status
  - register-ip / register-calidus probe healthy SRV edges and fail over on HTTP 5xx
- v0.0.37 - 2026-09-03
  - increased submit timouts
  - filter private IPs
  - installer script improved on regsiter-ip"
- v0.0.36 - 2026-09-02
  - improved logging
  - use SRV targets by RTT rank and failover;  

## Installation
You can install the package from PyPI:

```bash
pip install openblockperf
```

A plain `pip install` only provides the `blockperf` command. It does not
discover your cardano-node unit, write `config.json`, or install the systemd
service.

The recommended way on a Linux relay is the installer script. It installs the
PyPI package into a dedicated virtualenv and wires it into the existing node
installation and network configuration (systemd unit, config file, service
user, and CLI wrapper):

```bash
curl -fsSL https://raw.githubusercontent.com/cardano-foundation/openblockperf/main/blockperf-install.sh -o blockperf-install.sh
chmod +x blockperf-install.sh
sudo ./blockperf-install.sh
```

After the initial install, the best way to pick up new PyPI releases is:

```bash
sudo ./blockperf-install.sh --update
```

That upgrades only the `openblockperf` package in the existing virtualenv and
can restart the systemd service so the running client loads the new version.

## Documentation

Full guides live in the
[openblockperf GitHub repository](https://github.com/cardano-foundation/openblockperf):

- [Installer Guide](https://github.com/cardano-foundation/openblockperf/blob/main/docs/blockperf-install.md)
  for installer modes, options, API key flow, and updates
- [Manual Installation Guide](https://github.com/cardano-foundation/openblockperf/blob/main/docs/blockperf-install-manual.md)
  for a step-by-step setup that mirrors the installer
- [Client Overview](https://github.com/cardano-foundation/openblockperf/blob/main/docs/blockperf-client.md)
  for what the client reports and why the shared telemetry matters
- [Trace Options Guide](https://github.com/cardano-foundation/openblockperf/blob/main/docs/blockperf-traceoptions.md)
  for the cardano-node tracer settings the client needs
