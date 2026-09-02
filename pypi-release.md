# OpenBlockperf

A CLI tool and systemd service that captures and shares network metrics from a
[Cardano](https://developers.cardano.org/docs/operators/) relay node.

The client collects selected tracer and peering data from a local relay so
stake pool operators can contribute to a shared view of block propagation
and connectivity. It is intended for relay nodes that sit between a stake pool
producer and the rest of the network. Running it on a producer is possible
but not recommended. In normal operation it runs as a systemd service.

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
