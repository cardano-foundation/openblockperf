# OpenBlockPerf Installer Guide

This document describes how to install, reinstall, remove, and validate the OpenBlockPerf client with `blockperf-install.sh`.

## Quick start

```bash
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
- `--node-name <name>`: operator node label (defaults to OS hostname).
- `--node-config <path>`: path to node `config.json`.
- `--network mainnet|preprod|preview`: network override.
- `--api-key-file <path>`: read API key from file (recommended).
- `--api-key <value>`: provide API key directly (less secure, visible in process list).

The installer also performs an online installer-version check and can offer a self-update if a newer script is available.

**Node config path:** the script derives `config.json` from the unit’s `ExecStart` and expands variables such as `$CONFIG` using the unit’s merged `Environment` and `EnvironmentFiles`. If the path is still wrong or missing, interactive mode asks for the absolute path; an empty answer exits the installer.

## API key flow

- Preferred: `--api-key-file /path/to/keyfile`
- Alternative: export `OPENBLOCKPERF_API_KEY` and run with `sudo -E`
- Interactive mode can prompt for the key with hidden input.

If no key is provided, register after install:

```bash
<INSTALL_DIR>/venv/bin/blockperf register
```

Calidus-key documentation placeholder:
- https://openblockperf.cardano.org/docs#TODO

## Env file behavior

Env file path defaults to `/etc/default/openblockperf`.

When a new env file is written, the installer sets:

- `OPENBLOCKPERF_API_KEY` (if provided)
- `OPENBLOCKPERF_NETWORK`
- `OPENBLOCKPERF_LOG_LEVEL` (default `WARNING`; valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `EXCEPTION`)
- `OPENBLOCKPERF_NODE_NAME`
- `OPENBLOCKPERF_NODE_CONFIG`
- `OPENBLOCKPERF_NODE_UNIT_NAME` (used to identify cardano-node journald messages)

When the env file already exists:

- Interactive mode (without `--yes`): asks whether to keep or replace.
- Non-interactive (`--yes` or no TTY): renames existing file to:
  - `<envfile>-YYYY-MM-DD_HH-MM.backup`
  - falls back to seconds suffix if needed
  - then writes a fresh env file.

If you choose to keep the existing env file, update these manually as needed:

- `OPENBLOCKPERF_NETWORK`
- `OPENBLOCKPERF_NODE_NAME`
- `OPENBLOCKPERF_NODE_CONFIG`
- `OPENBLOCKPERF_NODE_UNIT_NAME`

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

