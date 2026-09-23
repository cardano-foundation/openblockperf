# OpenBlockPerf Amaru installer

Dedicated installer for **Amaru** (Rust) node hosts.
Do **not** use `blockperf-install.sh` here; that script targets Haskell
cardano-node / CNTools / TraceOptions.

Phase A covers systemd + journald (typical `.deb` / `.rpm` unit with
`StandardOutput=journal`). Nix, Homebrew, Docker, and plain binaries work
if you pass the unit and/or logfile explicitly.

Parser background: [amaru-log-parsing.md](amaru-log-parsing.md).
Haskell installer: [blockperf-install.md](blockperf-install.md).

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/cardano-foundation/openblockperf/main/blockperf-install-amaru.sh -o blockperf-install-amaru.sh
chmod +x blockperf-install-amaru.sh
sudo ./blockperf-install-amaru.sh
```

Unattended example (deb-style `amaru.service` already installed):

```bash
sudo ./blockperf-install-amaru.sh --yes \
  --node-unit-name amaru.service \
  --network mainnet \
  --api-key-mode relay
```

Amaru CLI options map to env vars (`--listen-address` → `AMARU_LISTEN_ADDRESS`,
`--network` → `AMARU_NETWORK`, and so on). Stock listen default is
`0.0.0.0:3000`. The installer probes `/etc/default/amaru` and
`/etc/sysconfig/amaru` for those vars when you do not pass flags.

## What it writes

Config defaults differ from the Haskell installer:

| Key | Amaru default |
|-----|---------------|
| `node_kind` | `amaru` |
| `node_unit_name` | discovered Amaru unit (journald filter) |
| `tracer_log_file` | `null` (journald) |
| `local_port` | `3000` (or `AMARU_LISTEN_ADDRESS` / `--local-port`) |
| `sync_check_enabled` | `false` (no Haskell EKG gate yet) |

`openblockperf.service` gets `After=` / `PartOf=` the Amaru unit so a
node restart also restarts the client.

## Modes and options

Same modes as the Haskell installer: `--install` (default), `--reinstall`,
`--update`, `--remove`, `--yes`, `--purge`.

Amaru-relevant flags:

- `--node-unit-name amaru.service`
- `--local-port 3000` (override when you changed `AMARU_LISTEN_ADDRESS`)
- `--network mainnet|preprod|preview` (also from `AMARU_NETWORK` in
  `/etc/default/amaru` or `/etc/sysconfig/amaru`)
- `--tracer-log-file /path/to.json` only if you are not using journald
- `--api-key` / `--api-key-file` / `--api-key-mode` (same as Haskell)

For JSON traces from the node itself, operators typically set
`AMARU_WITH_JSON_TRACES=true` (or `--with-json-traces`) so journald lines
match what the Amaru peer parser expects.

## Coverage by Amaru install method

| Method | Support in Phase A |
|--------|--------------------|
| `.deb` + stock `amaru.service` | Primary path (auto-discover unit, journald) |
| `.rpm` + systemd unit | Same as deb |
| Pre-compiled binary + your unit | Pass `--node-unit-name` |
| Nix profile / Homebrew | Pass unit and/or `--tracer-log-file`; no package magic |
| Docker | Out of band for now (sidecar / log mount). Manual config. |

## After install

```bash
sudo systemctl start openblockperf.service
sudo systemctl status openblockperf.service
journalctl -fu openblockperf.service
```

Startup should print `Node Kind: amaru`. Peer lines (`open` /
`temperature` / `close`) appear when Amaru handshakes and dies. Blocksamples
are not expected yet (Amaru INFO lacks the four Haskell prop steps).

## Notes

- Service user defaults like the Haskell installer (`SERVICE_USER` /
  `--user-context`). The Amaru package often uses user `amaru`; you can
  run openblockperf as that user or another non-root account that can read
  the journal for the Amaru unit.
- Reading journald for another user's unit may need the openblockperf user
  in group `systemd-journal` (or equivalent). Adjust if peer events stay
  silent.
- Installer script version is independent: Amaru `0.1.0`, Haskell `0.2.4`.
