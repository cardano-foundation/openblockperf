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

## 6) Write environment file

Create `/etc/default/openblockperf` with the same keys written by the installer.

```bash
sudo tee /etc/default/openblockperf >/dev/null <<EOF
# OpenBlockPerf client configuration
OPENBLOCKPERF_API_KEY=
OPENBLOCKPERF_NETWORK=${NETWORK}
OPENBLOCKPERF_LOG_LEVEL=WARNING
OPENBLOCKPERF_NODE_NAME=${NODE_NAME}
OPENBLOCKPERF_NODE_CONFIG=${NODE_CONFIG_PATH}
OPENBLOCKPERF_NODE_UNIT_NAME=${NODE_UNIT_NAME}
OPENBLOCKPERF_LOCAL_ADDR=0.0.0.0
OPENBLOCKPERF_LOCAL_PORT=3001
EOF
sudo chmod 600 /etc/default/openblockperf
```

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
EnvironmentFile=/etc/default/openblockperf
ExecStart=${INSTALL_DIR}/venv/bin/blockperf run
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

Register with your Calidus key to obtain an API key, then place it in the env file.

```bash
${INSTALL_DIR}/venv/bin/blockperf register
```

After receiving your API key, set it in `/etc/default/openblockperf`:

```bash
sudoedit /etc/default/openblockperf
# set: OPENBLOCKPERF_API_KEY=<your-api-key>
```

## 11) Start and validate

Start the service and check status/logs.

```bash
sudo systemctl start openblockperf.service
sudo systemctl status openblockperf.service
sudo journalctl -fu openblockperf.service
```
