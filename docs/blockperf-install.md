# OpenBlockPerf Installer Guide

This document describes how to install, reinstall, remove, and validate the OpenBlockPerf client with `blockperf-install.sh`.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/cardano-foundation/openblockperf/main/blockperf-install.sh -o blockperf-install.sh
chmod +x blockperf-install.sh
sudo ./blockperf-install.sh
```

In interactive mode, the installer asks whether you want **preview-only** mode first: it resolves settings and prints the plan but skips installing the package, writing systemd files, and starting the service. (OS package installs during preflight may still run if dependencies are missing.) Answer **No** to run a full install.

Piped or non-interactive runs (for example `curl ... | sudo bash`) have no terminal for prompts — use **`--yes`** for a fully unattended install.

## Modes

- `--install` (default): install to a new target directory. Fails immediately if
  `${INSTALL_DIR}` already exists (before the configuration wizard).
- `--reinstall`: replace install directory and reinstall artifacts.
- `--update`: update only the installed `openblockperf` package in the existing
  venv. After a successful upgrade, interactive mode asks whether to restart
  `openblockperf.service` (with `--yes`, restart is automatic when the unit is
  already active).
- `--remove`: remove service, wrapper, and install directory.

## Common options

- `--yes`: non-interactive mode, accepts prompts automatically (required for unattended installs when stdin is not a TTY).
- `--version`: print installer script version and exit.
- `--user-context <username>`: service user.
- `--node-unit-name <unit>`: cardano-node systemd unit.
- `--tracer-log-file <path>`: optional path to a cardano-tracer / node JSON logfile. When set, blockperf reads this file instead of journald. In logfile mode the installer also sets config `node_unit_name` to a line filter (JSON `host` when detectable, otherwise empty).
- `--node-name <name>`: operator node label (defaults to OS hostname).
- `--node-config <path>`: path to node `config.json`.
- `--network mainnet|preprod|preview`: network override.
- `--api-key-file <path>`: read API key from file (recommended).
- `--api-key <value>`: provide API key directly (less secure, visible in process list).
- `--api-key-mode <calidus|relay>`: fallback mode when no explicit key is provided.
  - default without `--yes`: `calidus`
  - default with `--yes`: `relay`

The installer also performs an online installer-version check and can offer a self-update if a newer script is available.

**Node config path:** the script derives `config.json` from the unit’s `ExecStart` and expands variables such as `$CONFIG` using the unit’s merged `Environment` and `EnvironmentFiles`. If the path is still wrong or missing, interactive mode asks for the absolute path; an empty answer exits the installer.

**Log source selection:** interactive installs ask whether blockperf should read tracer messages from journald (default) or a logfile path. If logfile mode is selected, the installer stores `tracer_log_file` in config and blockperf follows rotation on that file path.

In logfile mode, config `node_unit_name` is **not** the systemd unit. It is a content filter used to select lines from (possibly mixed) JSON logfiles:

- The installer tries to read a recent line from the logfile and proposes the JSON `host` field (for example `hh-hongkong`).
- You can also leave `node_unit_name` empty (`""`) to accept every line (typical for a single-node dedicated file such as `/opt/cardano/cnode/logs/cnode/node.json`).
- Do **not** keep a systemd unit name like `cnode.service` as the logfile filter unless that exact string appears in each log line. Otherwise every line is skipped and no peer/block events are processed.

The systemd unit discovered as `NODE_UNIT_NAME` is still used for `After=` / `PartOf=` (start after the node; stop/restart when the node unit is stopped or restarted) and for deriving the cardano-node `config.json` path. Only the value written into config as `node_unit_name` changes meaning in logfile mode.

### Switching an existing install to logfile mode

Edit `${INSTALL_DIR}/config.json` (default `/opt/cardano/openblockperf/config.json`):

1. Set `tracer_log_file` to the absolute path of the active JSON logfile.
2. Set `node_unit_name` to the tracer JSON `host` value, or to `""` to accept all lines.
3. Restart the service: `sudo systemctl restart openblockperf.service`

Example:

```json
{
  "tracer_log_file": "/opt/cardano/cnode/logs/cnode/node.json",
  "node_unit_name": "hh-hongkong"
}
```

Or, for a dedicated single-node logfile:

```json
{
  "tracer_log_file": "/opt/cardano/cnode/logs/cnode/node.json",
  "node_unit_name": ""
}
```

Confirm startup prints `Tracer Log File: ...` and that header/blocksample
or peer submit lines (`outbound`/`inbound` … `duplex=`) appear shortly after
new tracer activity. A quiet journal alone does not prove log parsing is working.

## API key flow

- Preferred: `--api-key-file /path/to/keyfile`
- Alternative: export `OPENBLOCKPERF_API_KEY` before install (written to `api_key` in the config file) and run with `sudo -E`
- Interactive mode can prompt for the key with hidden input. If you do not
  already have a key, it asks whether to register an IP-address bound key
  for this node and, if confirmed, stores it in the config file after
  package install.
- `--yes` without an explicit key defaults to `--api-key-mode relay` and
  runs `blockperf register-ip` after package install.
- `--api-key-mode relay` triggers public-IP based auto-registration after package install.

If no key is provided, register after install:

```bash
<INSTALL_DIR>/venv/bin/blockperf --config ${INSTALL_DIR}/config.json register-ip
```

Relay/IP registration (for unattended relays):

```bash
<INSTALL_DIR>/venv/bin/blockperf --config ${INSTALL_DIR}/config.json register-ip
```

In relay mode, the client proves IPv4 and IPv6 separately (as available) via
`/registration/ip/proof`, then submits short-lived proof tokens to
`/registration/ip` so one API key is bound to the validated public IP(s). If a
proof fails, it falls back to legacy single-stack registration.

Calidus-key information:
- https://forum.cardano.org/t/new-calidus-pool-key-for-spos-and-services-interacting-with-pools/143812/27

## Config file behavior

The config file path defaults to `${INSTALL_DIR}/config.json` (installer default install dir: `/opt/cardano/openblockperf/config.json`).

When a new config file is written, the installer sets:

- `api_key` (if provided)
- `network`
- `log_level` (default `WARNING`; valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `EXCEPTION`)
- `node_name`
- `node_config` (path to cardano-node `config.json`)
- `node_unit_name` (journald: systemd unit to follow; logfile: line filter, usually JSON `host` or empty)
- `tracer_log_file` (optional; if set, read tracer JSON from this file and follow rotations)
- `local_addr` (default `0.0.0.0`)
- `local_port` (default `3001`)
- `peer_event_stable_seconds` (default `15`)
- `peer_traceroute_enabled` (default `false`)
- `peer_count_stats_interval` (default `5`)
- `peer_prune_idle_seconds` (default `600`)
- `local_metrics_enabled` (default `false`)
- `local_metrics_bind` (default `127.0.0.1`)
- `local_metrics_port` (default `14041`)

Further optional keys (not written by the installer; defaults apply if omitted).
All keys also accept matching `OPENBLOCKPERF_*` environment variables.

**Shell / CLI convenience:**

- `OPENBLOCKPERF_CONFIG` path to the client config file. Used when `--config`
  is omitted. The installer wrapper always exports this; the installer can also
  add it to the service user's `.bashrc` / `.profile` if not already set.

**API discovery and HTTP:**

- `api_srv` (default `_obpf._tcp.network.cardano.org`) DNS SRV name used to
  discover API edges
- `api_url` skip SRV discovery and use a full API base URL (for example a
  local backend)
- `api_request_timeout_ms` (default `8000`) HTTP timeout per API request in
  milliseconds (submit, registration, health probes)
- `api_request_retries` (default `2`) extra retries on the same host after a
  timeout or connection error; after those fail, service mode fails over to
  the next ranked edge

**Privacy:**

- `obfuscate_ips` (default `[]`) extra IP addresses that must never be sent to
  the backend. Private, loopback, and link-local addresses are always
  obfuscated to `0.0.0.0` without listing them here.

**Sync gate (EKG):**

- `ekg_url` (default `http://localhost:12798/metrics`) EKG metrics endpoint
  used to decide whether the node is synced
- `sync_check_enabled` (default `true`) when `true`, the client waits until
  sync progress reaches the threshold before submitting samples
- `sync_check_interval` (default `15`) seconds between sync polls
- `sync_check_threshold` (default `99.9`) minimum replay progress percent to
  treat the node as synced

**Sampling cadence:**

- `block_sample_check_interval` (default `2`) seconds between checks for
  complete block-sample groups
- `min_age` (default `10`) seconds a complete sample group must age before
  submit

**Peer events** (written by the installer with the defaults below; edit in
place to change behaviour). See [peers.md](peers.md) and
[local-peer-metrics.md](local-peer-metrics.md).

- `peer_event_stable_seconds` (default `15`) how long Warm/Hot must last before
  an enter is submitted (all clients report cold_to_warm + warm_to_hot + leaves)
- `peer_traceroute_enabled` (default `false`) optional traceroute enrichment
  (not implemented yet)
- `peer_count_stats_interval` (default `5`) seconds to wait after peer
  counters change before logging `peerCountStats` (debounce); `0` disables
- `peer_prune_idle_seconds` (default `600`) drop fully inactive peers from the
  local list after this idle time
- `local_metrics_enabled` (default `false`) serve Prometheus + JSON peer lists
- `local_metrics_bind` (default `127.0.0.1`)
- `local_metrics_port` (default `14041`) avoid node `12798` / Prometheus `9090`

The client resolves SRV targets as FQDNs and calls
`https://{fqdn}:{port}/{network}/api/v0/...`. `blockperf run` ranks healthy
edges by RTT; `register-ip` / `register-calidus` probe health, shuffle healthy
edges, and fail over on transport errors or HTTP 5xx.
The installer wrapper exports `OPENBLOCKPERF_CONFIG` to the installed config
file, so `--config` is optional for CLI use. You can still pass `--config`
before a subcommand to override:

```bash
blockperf register-ip
# or explicitly:
<INSTALL_DIR>/venv/bin/blockperf --config ${INSTALL_DIR}/config.json register-ip
```

When the config file already exists:

- Interactive mode (without `--yes`): asks whether to keep or replace.
- Non-interactive (`--yes` or no TTY): renames existing file to:
  - `config-YYYY-MM-DD_HH-MM.backup.json`
  - falls back to seconds suffix if needed
  - then writes a fresh config file.

If you choose to keep the existing config file, update these keys manually as needed:

- `network`
- `node_name`
- `node_config`
- `node_unit_name`
- `tracer_log_file`
- `api_srv` / `api_url` (if you override backend discovery)
- peer-event / local-metrics keys if you want the same defaults as a fresh install
  (`peer_event_stable_seconds`, `local_metrics_*`, …)

## Systemd and cardano-node

The generated `openblockperf.service` uses `After=` and `PartOf=` on the
discovered cardano-node unit (for example `cnode.service`). That means:

- openblockperf starts after the node at boot
- `systemctl restart cnode.service` (or stop) also restarts (or stops) openblockperf

This clears in-memory peer state so peer-event counts start fresh after a node
restart. Package-only `--update` does not rewrite the unit file; use
`--reinstall` (or edit the unit by hand) to pick up this dependency on an
existing host.

- Installer uses strict shell settings (`set -euo pipefail`).
- On install failures, it prints the failing command and attempts limited rollback of artifacts created in the current run.
- If `pip install` fails, it prints a verbose retry command.
- If service start fails, it prints `systemctl` error output.

## Operational commands

After install:

```bash
sudo systemctl start openblockperf.service
sudo systemctl status openblockperf.service
sudo journalctl -fu openblockperf.service
```

## Maintainer validation

Run shellcheck during development:

```bash
shellcheck blockperf-install.sh
```

