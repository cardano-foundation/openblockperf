# OpenBlockPerf Installer Guide

This document describes how to install, reinstall, remove, and validate the OpenBlockPerf client with `blockperf-install.sh`.

## Quick start

```bash
sudo ./blockperf-install.sh
```

Recommended first run:

```bash
sudo ./blockperf-install.sh --dry-run
```

Then run without `--dry-run` to apply changes.

## Modes

- `--install` (default): install to a new target directory.
- `--reinstall`: replace install directory and reinstall artifacts.
- `--remove`: remove service, wrapper, and install directory.

## Common options

- `--yes`: non-interactive mode, accepts prompts automatically.
- `--dry-run`: resolve and display settings only, no system changes.
- `--user-context <username>`: service user.
- `--node-unit-name <unit>`: cardano-node systemd unit.
- `--node-name <name>`: operator node label (defaults to OS hostname).
- `--node-config <path>`: path to node `config.json`.
- `--network mainnet|preprod|preview`: network override.
- `--api-key-file <path>`: read API key from file (recommended).
- `--api-key <value>`: provide API key directly (less secure, visible in process list).

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

When the env file already exists:

- Interactive mode (without `--yes`): asks whether to keep or replace.
- Non-interactive (`--yes` or no TTY): renames existing file to:
  - `<envfile>-YYYY-MM-DD_HH-MM.backup`
  - falls back to seconds suffix if needed
  - then writes a fresh env file.

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

