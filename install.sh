#!/usr/bin/env bash
# install.sh — Install and configure the OpenBlockPerf client on a Linux system
#
# This script:
#   1. Creates an installation directory for the virtual environment
#   2. Creates a Python virtual environment using the system Python
#   3. Installs the openblockperf package from PyPI
#   4. Writes an environment file at /etc/default/openblockperf
#   5. Writes a systemd service unit and enables it
#
# All steps are configurable via environment variables (see below).
#
# Usage:
#   sudo ./install.sh
#   sudo NETWORK=preprod ./install.sh
#   sudo INSTALL_DIR=/srv/openblockperf SERVICE_USER=ada ./install.sh
#   sudo PACKAGE_VERSION=0.0.5 ./install.sh
#
# Configurable environment variables:
#   INSTALL_DIR       Base directory for the virtual environment and data
#                     Default: /opt/cardano/openblockperf
#   PYTHON            Python interpreter to use for creating the venv
#                     Default: python3
#   PACKAGE_VERSION   Specific package version to install (empty = latest)
#                     Default: (empty)
#   SERVICE_USER      System user the service runs as
#                     Default: cardano
#   SERVICE_GROUP     System group the service runs as
#                     Default: cardano
#   SERVICE_FILE      Path for the systemd unit file
#                     Default: /etc/systemd/system/openblockperf.service
#   ENV_FILE          Path for the environment configuration file
#                     Default: /etc/default/openblockperf
#   NETWORK           Cardano network: mainnet | preprod | preview
#                     Default: mainnet

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — all values can be overridden via environment variables
# ---------------------------------------------------------------------------
INSTALL_DIR="${INSTALL_DIR:-/opt/cardano/openblockperf}"
PYTHON="${PYTHON:-python3}"
PACKAGE_NAME="openblockperf"
PACKAGE_VERSION="${PACKAGE_VERSION:-}"
SERVICE_USER="${SERVICE_USER:-cardano}"
SERVICE_GROUP="${SERVICE_GROUP:-cardano}"
SERVICE_FILE="${SERVICE_FILE:-/etc/systemd/system/openblockperf.service}"
ENV_FILE="${ENV_FILE:-/etc/default/openblockperf}"
NETWORK="${NETWORK:-mainnet}"

# Derived values
VENV_DIR="${INSTALL_DIR}/venv"
PACKAGE_SPEC="${PACKAGE_NAME}${PACKAGE_VERSION:+==${PACKAGE_VERSION}}"

# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; NC=''
fi

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()   { echo -e "${RED}[FAIL]${NC}  $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
check_root() {
    [[ $EUID -eq 0 ]] || die "This script must be run as root. Try: sudo $0"
}

check_python() {
    command -v "${PYTHON}" &>/dev/null \
        || die "Python interpreter '${PYTHON}' not found. Install python3 or set PYTHON= to a valid interpreter."
    local py_version
    py_version=$("${PYTHON}" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    # Require Python >= 3.12
    local major minor
    major=$(echo "${py_version}" | cut -d. -f1)
    minor=$(echo "${py_version}" | cut -d. -f2)
    if (( major < 3 || (major == 3 && minor < 12) )); then
        die "Python >= 3.12 is required (found ${py_version}). Set PYTHON= to a suitable interpreter."
    fi
    info "Using Python ${py_version} (${PYTHON})"
    # On Debian/Ubuntu the system Python disables ensurepip unless python3-full
    # (or python3-pip) is installed. Check early so the error is actionable.
    "${PYTHON}" -m ensurepip --version &>/dev/null \
        || die "'${PYTHON}' has no ensurepip module — pip cannot be installed into the venv.
       On Debian/Ubuntu run:  apt-get install python3-full
       Then re-run this script."
}

check_systemd() {
    command -v systemctl &>/dev/null \
        || die "systemd not found. This installer requires a systemd-based Linux distribution."
}

check_network_value() {
    case "${NETWORK}" in
        mainnet|preprod|preview) ;;
        *) die "Invalid NETWORK value '${NETWORK}'. Must be one of: mainnet, preprod, preview" ;;
    esac
}

# ---------------------------------------------------------------------------
# Installation steps
# ---------------------------------------------------------------------------
create_install_dir() {
    info "Creating installation directory: ${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}"
    ok "Directory ready."
}

create_venv() {
    if [[ -d "${VENV_DIR}" ]]; then
        warn "Virtual environment already exists at ${VENV_DIR} — reusing it."
    else
        info "Creating virtual environment at ${VENV_DIR} ..."
        "${PYTHON}" -m venv "${VENV_DIR}"
        ok "Virtual environment created."
    fi
    # Some distro Python builds create a venv without pip even when ensurepip is
    # available (e.g. when the venv was created by an older script without --upgrade-deps).
    # Bootstrap pip explicitly if it is missing, then upgrade it.
    if [[ ! -x "${VENV_DIR}/bin/pip" ]]; then
        info "pip not found in venv — bootstrapping via ensurepip ..."
        "${VENV_DIR}/bin/python" -m ensurepip --upgrade
    fi
    info "Upgrading pip inside venv ..."
    "${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
}

install_package() {
    info "Installing ${PACKAGE_SPEC} from PyPI ..."
    "${VENV_DIR}/bin/pip" install --quiet "${PACKAGE_SPEC}"
    local installed_version
    installed_version=$("${VENV_DIR}/bin/pip" show "${PACKAGE_NAME}" | awk '/^Version:/ {print $2}')
    ok "Installed ${PACKAGE_NAME} ${installed_version}."
}

configure_ownership() {
    if id "${SERVICE_USER}" &>/dev/null; then
        chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DIR}"
        ok "Ownership of ${INSTALL_DIR} set to ${SERVICE_USER}:${SERVICE_GROUP}."
    else
        warn "User '${SERVICE_USER}' does not exist — skipping ownership change."
        warn "Create the user and then run:"
        warn "  chown -R ${SERVICE_USER}:${SERVICE_GROUP} ${INSTALL_DIR}"
    fi
}

write_env_file() {
    if [[ -f "${ENV_FILE}" ]]; then
        warn "Environment file ${ENV_FILE} already exists — skipping to preserve your configuration."
        warn "Delete it and re-run to regenerate from the template."
        return
    fi

    info "Writing environment file: ${ENV_FILE}"
    cat > "${ENV_FILE}" <<EOF
# OpenBlockPerf client configuration
# Documentation: https://openblockperf.readthedocs.io
#
# All variables use the OPENBLOCKPERF_ prefix (pydantic-settings convention).
# After editing this file, restart the service:
#   systemctl restart openblockperf

# -----------------------------------------------------------------------
# Required: API key issued at https://openblockperf.cardano.org
# -----------------------------------------------------------------------
OPENBLOCKPERF_API_KEY=

# -----------------------------------------------------------------------
# Cardano network: mainnet | preprod | preview
# -----------------------------------------------------------------------
OPENBLOCKPERF_NETWORK=${NETWORK}

# -----------------------------------------------------------------------
# Local cardano-node connection address and port (EKG / cardano-tracer)
# -----------------------------------------------------------------------
OPENBLOCKPERF_LOCAL_ADDR=0.0.0.0
OPENBLOCKPERF_LOCAL_PORT=3001
EOF

    # The file may contain an API key — readable by root only.
    # systemd reads EnvironmentFile as root before dropping privileges,
    # so mode 600 is sufficient and keeps the secret off other users.
    chmod 600 "${ENV_FILE}"
    ok "Environment file written: ${ENV_FILE}"
    echo
    warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    warn " ACTION REQUIRED: Set OPENBLOCKPERF_API_KEY in ${ENV_FILE}"
    warn " before starting the service."
    warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo
}

write_service_file() {
    local bin="${VENV_DIR}/bin/blockperf"
    info "Writing systemd unit: ${SERVICE_FILE}"
    cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=OpenBlockPerf Client
Documentation=https://openblockperf.readthedocs.io
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
EnvironmentFile=${ENV_FILE}
ExecStart=${bin} run
Restart=on-failure
RestartSec=10s
TimeoutStopSec=30s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=openblockperf

[Install]
WantedBy=multi-user.target
EOF

    chmod 644 "${SERVICE_FILE}"
    ok "Service unit written: ${SERVICE_FILE}"
}

enable_service() {
    info "Reloading systemd daemon ..."
    systemctl daemon-reload
    info "Enabling openblockperf.service ..."
    systemctl enable openblockperf.service
    ok "Service enabled (will start automatically on next boot)."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    echo
    echo -e "${BOLD}OpenBlockPerf Client Installer${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf "  %-14s %s\n" "Install dir:"  "${INSTALL_DIR}"
    printf "  %-14s %s\n" "Python:"       "${PYTHON}"
    printf "  %-14s %s\n" "Package:"      "${PACKAGE_SPEC}"
    printf "  %-14s %s\n" "Service user:" "${SERVICE_USER}:${SERVICE_GROUP}"
    printf "  %-14s %s\n" "Network:"      "${NETWORK}"
    printf "  %-14s %s\n" "Service file:" "${SERVICE_FILE}"
    printf "  %-14s %s\n" "Env file:"     "${ENV_FILE}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo

    check_root
    check_python
    check_systemd
    check_network_value

    create_install_dir
    create_venv
    install_package
    configure_ownership
    write_env_file
    write_service_file
    enable_service

    echo
    echo -e "${GREEN}${BOLD}Installation complete.${NC}"
    echo
    echo "Next steps:"
    echo "  1. Set your API key:  ${ENV_FILE}"
    echo "  2. Start the service: systemctl start openblockperf"
    echo "  3. Check its status:  systemctl status openblockperf"
    echo "  4. Follow the logs:   journalctl -fu openblockperf"
    echo
}

main "$@"
