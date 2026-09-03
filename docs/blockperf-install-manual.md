# OpenBlockPerf Manual Installation

This guide describes a manual installation flow that mirrors what `blockperf-install.sh` does.

Use this when you want full control over each installation step instead of running the installer wizard.

## 1) Define installation variables

Set the same core values that the installer resolves automatically.

```bash
export INSTALL_DIR="/opt/cardano/openblockperf"
export PYTHON_BIN="python3"
export SERVICE_USER="<non-root-user>"
export SERVICE_GROUP="$(id -gn "${SERVICE_USER}")"
export NODE_NAME="$(hostname)"
export NODE_UNIT_NAME="cnode.service"
export TRACER_LOG_FILE=""  # optional, e.g. /var/log/cardano/tracer.log
export NODE_CONFIG_PATH="/opt/cardano/cnode/files/config.json"
export NETWORK="mainnet"  # mainnet | preprod | preview
```

## 2) Install OS prerequisites

Install required dependencies (`python3`, `jq`, `curl`, `systemd`) and ensure `venv/pip` support is available.

```bash
# Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-full jq curl systemd

# RHEL-family (Rocky/Alma/CentOS/Fedora)
sudo dnf install -y python3 python3-pip jq curl systemd
```

Verify Python can bootstrap pip in a virtual environment:

```bash
${PYTHON_BIN} -m ensurepip --version
```

## 3) Validate cardano-node config input

Confirm that the node config file exists, is valid JSON, and has expected Cardano config keys.

```bash
test -r "${NODE_CONFIG_PATH}"
jq -e '.' "${NODE_CONFIG_PATH}" >/dev/null
jq -e 'has("ShelleyGenesisFile") or has("ByronGenesisFile") or has("TraceOptions")' "${NODE_CONFIG_PATH}" >/dev/null
```

If trace options are not configured yet, see [Trace Options Guide](blockperf-traceoptions.md).

## 4) Create install directory and virtual environment

Create the target directory and install `openblockperf` into a venv.

```bash
sudo mkdir -p "${INSTALL_DIR}"
sudo ${PYTHON_BIN} -m venv "${INSTALL_DIR}/venv"
sudo "${INSTALL_DIR}/venv/bin/pip" install --upgrade pip setuptools wheel
sudo "${INSTALL_DIR}/venv/bin/pip" install --upgrade openblockperf
```

## 5) Apply ownership for runtime user

Set ownership so the configured service user owns the installation tree.

```bash
sudo chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DIR}"
```

## 6) Write config file

Create `${INSTALL_DIR}/config.json` with the same keys written by the installer.
Leave `tracer_log_file` empty/omitted for journald mode; set it to use file mode.

```bash
sudo tee "${INSTALL_DIR}/config.json" >/dev/null <<EOF
{
  "_comment": "OpenBlockPerf client configuration",
  "api_key": "",
  "network": "${NETWORK}",
  "log_level": "WARNING",
  "node_name": "${NODE_NAME}",
  "node_config": "${NODE_CONFIG_PATH}",
  "node_unit_name": "${NODE_UNIT_NAME}",
  "tracer_log_file": "${TRACER_LOG_FILE}",
  "local_addr": "0.0.0.0",
  "local_port": 3001
}
EOF
sudo chmod 664 "${INSTALL_DIR}/config.json"
```

Optional: set `"api_srv": "_obpf._tcp.network.cardano.org"` (the client default) or
point it at your own SRV name. Set `"api_url"` only when you want to skip SRV
discovery and use a full base URL such as `http://localhost:8000/mainnet/api/v0`.
Private/loopback/link-local peer addresses are always sent as `0.0.0.0`; add
extra addresses to hide with `"obfuscate_ips": ["203.0.113.10"]`.

## 7) Write systemd service unit

Create the same service unit the installer generates.

```bash
sudo tee /etc/systemd/system/openblockperf.service >/dev/null <<EOF
[Unit]
Description=OpenBlockPerf Client
Documentation=https://openblockperf.readthedocs.io
After=network-online.target
Wants=network-online.target
After=${NODE_UNIT_NAME}

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/blockperf --config ${INSTALL_DIR}/config.json run
Restart=on-failure
RestartSec=10s
TimeoutStopSec=30s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=openblockperf

[Install]
WantedBy=multi-user.target
EOF
sudo chmod 644 /etc/systemd/system/openblockperf.service
```

## 8) Write optional CLI wrapper command

Install a convenience wrapper at `/usr/local/bin/blockperf`.

```bash
sudo tee /usr/local/bin/blockperf >/dev/null <<EOF
#!/usr/bin/env bash
exec ${INSTALL_DIR}/venv/bin/blockperf "\$@"
EOF
sudo chmod 755 /usr/local/bin/blockperf
```

## 9) Reload and enable service

Load the new unit and enable it at boot.

```bash
sudo systemctl daemon-reload
sudo systemctl enable openblockperf.service
```

## 10) Register for API key (one-time)

Register with your Calidus key to obtain an API key, then place it in the config file.
Pass `--config` before the subcommand so network and `api_srv` settings are loaded.

```bash
${INSTALL_DIR}/venv/bin/blockperf --config ${INSTALL_DIR}/config.json register-calidus --pool-id <bech32> --calidus-skey /path/to/calidus.skey
```

Alternative (public relay IP based):

```bash
${INSTALL_DIR}/venv/bin/blockperf --config ${INSTALL_DIR}/config.json register-ip
```

`register-ip` picks one SRV target at random. `blockperf run` (the systemd service)
ranks healthy edges by RTT and fails over if the selected host times out.

After receiving your API key, set it in `${INSTALL_DIR}/config.json`:

```bash
sudoedit "${INSTALL_DIR}/config.json"
# set: "api_key": "<your-api-key>"
```

## 11) Start and validate

Start the service and check status/logs.

```bash
sudo systemctl start openblockperf.service
sudo systemctl status openblockperf.service
sudo journalctl -fu openblockperf.service
```
