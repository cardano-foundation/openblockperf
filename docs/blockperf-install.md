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

- `--install` (default): install to a new target directory.
- `--reinstall`: replace install directory and reinstall artifacts.
- `--update`: update only the installed `openblockperf` package in the existing venv.
- `--remove`: remove service, wrapper, and install directory.

## Common options

- `--yes`: non-interactive mode, accepts prompts automatically (required for unattended installs when stdin is not a TTY).
- `--version`: print installer script version and exit.
- `--user-context <username>`: service user.
- `--node-unit-name <unit>`: cardano-node systemd unit.
- `--tracer-log-file <path>`: optional path to a cardano-tracer logfile. When set, blockperf reads this file instead of journald.
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

## API key flow

- Preferred: `--api-key-file /path/to/keyfile`
- Alternative: export `OPENBLOCKPERF_API_KEY` before install (written to `api_key` in the config file) and run with `sudo -E`
- Interactive mode can prompt for the key with hidden input.
- `--api-key-mode relay` triggers public-IP based auto-registration after package install.

If no key is provided, register after install:

```bash
<INSTALL_DIR>/venv/bin/blockperf register
```

Relay/IP registration (for unattended relays):

```bash
<INSTALL_DIR>/venv/bin/blockperf register --relay-ip
```

In relay mode, the client probes IPv4 and IPv6 separately (as available), then submits short-lived cookies to obtain one API key bound to the validated public IP(s).

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
- `node_unit_name` (used to select the cardano-node stream in journald or logfile mode)
- `tracer_log_file` (optional; if set, read tracer JSON from this file and follow rotations)
- `local_addr` (default `0.0.0.0`)
- `local_port` (default `3001`)

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

## Reliability behavior

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

