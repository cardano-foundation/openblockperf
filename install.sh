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
#   sudo ./install.sh --reinstall
#   sudo ./install.sh --remove
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
#                     Default: resolved from SUDO_USER / caller (interactive fallback)
#   SERVICE_GROUP     System group the service runs as
#                     Default: primary group of SERVICE_USER
#   SERVICE_FILE      Path for the systemd unit file
#                     Default: /etc/systemd/system/openblockperf.service
#   WRAPPER_COMMAND   Script that will start the client within its environment
#                     Default: /usr/local/bin/blockperf
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
SERVICE_USER="${SERVICE_USER:-}"
SERVICE_GROUP="${SERVICE_GROUP:-}"
SERVICE_FILE="${SERVICE_FILE:-/etc/systemd/system/openblockperf.service}"
WRAPPER_COMMAND="${WRAPPER_COMMAND:-/usr/local/bin/blockperf}"
ENV_FILE="${ENV_FILE:-/etc/default/openblockperf}"
NETWORK="${NETWORK:-mainnet}"
MODE="install"        # install | reinstall | remove
ASSUME_YES="false"    # true to skip interactive confirmations
PURGE_CONFIG="false"  # true to remove ENV_FILE on --remove

# Derived values
VENV_DIR="${INSTALL_DIR}/venv"
PACKAGE_SPEC="${PACKAGE_NAME}${PACKAGE_VERSION:+==${PACKAGE_VERSION}}"
UNIT_NAME="$(basename "${SERVICE_FILE}")"

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

usage() {
    cat <<EOF
Usage:
  sudo $0 [--install|--reinstall|--remove] [--yes] [--purge]

Modes:
  --install      Install if target paths are empty (default)
  --reinstall    Reinstall package and replace install directory
  --remove       Remove service, wrapper, and installation directory

Options:
  --yes          Non-interactive: assume "yes" for confirmations
  --purge        With --remove, also delete ${ENV_FILE}
  -h, --help     Show this help
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --install) MODE="install" ;;
            --reinstall) MODE="reinstall" ;;
            --remove) MODE="remove" ;;
            --yes|-y) ASSUME_YES="true" ;;
            --purge) PURGE_CONFIG="true" ;;
            -h|--help) usage; exit 0 ;;
            *)
                die "Unknown argument: $1 (use --help)"
                ;;
        esac
        shift
    done
}

confirm_or_die() {
    local prompt="$1"
    if [[ "${ASSUME_YES}" == "true" ]]; then
        return 0
    fi
    [[ -t 0 ]] || die "${prompt} (re-run with --yes to continue non-interactively)"
    local answer
    read -r -p "${prompt} [y/N]: " answer
    case "${answer}" in
        y|Y|yes|YES) return 0 ;;
        *) die "Aborted by user." ;;
    esac
}

resolve_service_identity() {
    local guessed_user=""

    if [[ -n "${SERVICE_USER}" ]]; then
        guessed_user="${SERVICE_USER}"
    elif [[ -n "${SUDO_USER:-}" ]]; then
        guessed_user="${SUDO_USER}"
    elif command -v logname &>/dev/null; then
        guessed_user="$(logname 2>/dev/null || true)"
    fi

    if [[ -z "${guessed_user}" ]]; then
        guessed_user="$(whoami 2>/dev/null || true)"
    fi

    if [[ -z "${guessed_user}" || "${guessed_user}" == "root" ]]; then
        if [[ "${ASSUME_YES}" == "true" ]]; then
            die "Could not infer non-root service user. Set SERVICE_USER=... explicitly."
        fi
        [[ -t 0 ]] || die "Could not infer non-root service user in non-interactive mode. Set SERVICE_USER=..."
        read -r -p "Service user (non-root) to own ${INSTALL_DIR}: " guessed_user
    fi

    id "${guessed_user}" &>/dev/null || die "User '${guessed_user}' does not exist."
    SERVICE_USER="${guessed_user}"

    if [[ -z "${SERVICE_GROUP}" ]]; then
        SERVICE_GROUP="$(id -gn "${SERVICE_USER}" 2>/dev/null || true)"
    fi

    [[ -n "${SERVICE_GROUP}" ]] || die "Could not resolve group for '${SERVICE_USER}'. Set SERVICE_GROUP=..."
    getent group "${SERVICE_GROUP}" &>/dev/null || die "Group '${SERVICE_GROUP}' does not exist."
}

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
check_root() {
    [[ $EUID -eq 0 ]] || die "This script must be run as root. Try: sudo $0"
}

check_linux() {
    [[ "$(uname -s)" == "Linux" ]] || die "This installer supports Linux only."
}

check_required_commands() {
    local cmds=("id" "getent" "mkdir" "rm" "chmod" "chown" "install")
    local c
    for c in "${cmds[@]}"; do
        command -v "${c}" &>/dev/null || die "Required command '${c}' not found."
    done
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
    if [[ -d "${INSTALL_DIR}" ]]; then
        if [[ "${MODE}" == "install" ]]; then
            die "Install directory already exists: ${INSTALL_DIR}. Use --reinstall to replace it."
        fi
        ok "Replacing existing installation directory: ${INSTALL_DIR}"
        rm -rf "${INSTALL_DIR}"
    else
        ok "Creating installation directory: ${INSTALL_DIR}"
    fi
    mkdir -p "${INSTALL_DIR}"
}

create_venv() {
    if [[ -d "${VENV_DIR}" ]]; then
        warn "Virtual environment already exists at ${VENV_DIR} — reusing it."
    else
        ok "Creating virtual environment at ${VENV_DIR} ..."
        "${PYTHON}" -m venv "${VENV_DIR}"
    fi
    # Some distro Python builds create a venv without pip even when ensurepip is
    # available (e.g. when the venv was created by an older script without --upgrade-deps).
    # Bootstrap pip explicitly if it is missing, then upgrade it.
    if [[ ! -x "${VENV_DIR}/bin/pip" ]]; then
        info "pip not found in venv — bootstrapping via ensurepip ..."
        "${VENV_DIR}/bin/python" -m ensurepip --upgrade
    fi
    "${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
}

install_package() {
    ok "Installing ${PACKAGE_SPEC} from PyPI ..."
    "${VENV_DIR}/bin/pip" install --quiet "${PACKAGE_SPEC}"
    local installed_version
}

configure_ownership() {
    id "${SERVICE_USER}" &>/dev/null || die "User '${SERVICE_USER}' does not exist."
    getent group "${SERVICE_GROUP}" &>/dev/null || die "Group '${SERVICE_GROUP}' does not exist."
    chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DIR}"
    ok "Ownership of ${INSTALL_DIR} set to ${SERVICE_USER}:${SERVICE_GROUP}."
}

write_env_file() {
    if [[ -f "${ENV_FILE}" ]]; then
        warn "Environment file ${ENV_FILE} already exists — skipping to preserve your configuration."
        warn "Delete it and re-run to regenerate from the template."
        return
    fi

    ok "Writing environment file: ${ENV_FILE}"
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
    echo
    warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    warn " ACTION REQUIRED: Set OPENBLOCKPERF_API_KEY in ${ENV_FILE}"
    warn " before starting the service."
    warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo
}

write_service_file() {
    local bin="${VENV_DIR}/bin/blockperf"
    ok "Writing systemd unit: ${SERVICE_FILE}"
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
}

write_wrappercommand_file() {
    local bin="${WRAPPER_COMMAND}"
    ok "Writing wrapper command: ${WRAPPER_COMMAND}"
    cat > "${WRAPPER_COMMAND}" <<EOF
#!/usr/bin/env bash
exec ${INSTALL_DIR}/venv/bin/blockperf "\$@"
EOF

    chmod 755 "${WRAPPER_COMMAND}"
}

enable_service() {
    ok "Reloading systemd daemon ..."
    systemctl daemon-reload
    ok "Enabling ${UNIT_NAME} ..."
    systemctl enable "${UNIT_NAME}"
    ok "Service enabled. To start use 'systemctl start ${UNIT_NAME}'."
}

stop_disable_service_if_present() {
    if systemctl list-unit-files "${UNIT_NAME}" --no-pager &>/dev/null; then
        info "Stopping ${UNIT_NAME} (if running) ..."
        systemctl stop "${UNIT_NAME}" 2>/dev/null || true
        info "Disabling ${UNIT_NAME} (if enabled) ..."
        systemctl disable "${UNIT_NAME}" 2>/dev/null || true
    fi
}

remove_installation() {
    confirm_or_die "This will remove service files and ${INSTALL_DIR}. Continue?"
    stop_disable_service_if_present

    if [[ -f "${SERVICE_FILE}" ]]; then
        ok "Removing service file: ${SERVICE_FILE}"
        rm -f "${SERVICE_FILE}"
    fi
    if [[ -f "${WRAPPER_COMMAND}" ]]; then
        ok "Removing wrapper command: ${WRAPPER_COMMAND}"
        rm -f "${WRAPPER_COMMAND}"
    fi
    if [[ -d "${INSTALL_DIR}" ]]; then
        ok "Removing installation directory: ${INSTALL_DIR}"
        rm -rf "${INSTALL_DIR}"
    fi

    if [[ "${PURGE_CONFIG}" == "true" && -f "${ENV_FILE}" ]]; then
        ok "Removing environment file: ${ENV_FILE}"
        rm -f "${ENV_FILE}"
    elif [[ -f "${ENV_FILE}" ]]; then
        warn "Keeping existing environment file: ${ENV_FILE} (use --purge to remove it)."
    fi

    systemctl daemon-reload || true
    ok "Removal complete."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    parse_args "$@"
    check_root
    check_linux
    check_required_commands
    check_systemd

    if [[ "${MODE}" == "remove" ]]; then
        echo
        echo -e "${BOLD}OpenBlockPerf Installer (${MODE})${NC}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        printf "  %-14s %s\n" "Install dir:"  "${INSTALL_DIR}"
        printf "  %-14s %s\n" "Service file:" "${SERVICE_FILE}"
        printf "  %-14s %s\n" "Env file:"     "${ENV_FILE}"
        printf "  %-14s %s\n" "Command:"      "${WRAPPER_COMMAND}"
        printf "  %-14s %s\n" "Purge config:" "${PURGE_CONFIG}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo
        remove_installation
        exit 0
    fi

    check_python
    check_network_value
    resolve_service_identity

    echo
    echo -e "${BOLD}OpenBlockPerf Installer (${MODE})${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf "  %-14s %s\n" "Install dir:"  "${INSTALL_DIR}"
    printf "  %-14s %s\n" "Python:"       "${PYTHON}"
    printf "  %-14s %s\n" "Package:"      "${PACKAGE_SPEC}"
    printf "  %-14s %s\n" "Service user:" "${SERVICE_USER}:${SERVICE_GROUP}"
    printf "  %-14s %s\n" "Network:"      "${NETWORK}"
    printf "  %-14s %s\n" "Service file:" "${SERVICE_FILE}"
    printf "  %-14s %s\n" "Env file:"     "${ENV_FILE}"
    printf "  %-14s %s\n" "Command:"      "${WRAPPER_COMMAND}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo

    if [[ "${MODE}" == "reinstall" ]]; then
        confirm_or_die "Reinstall will replace ${INSTALL_DIR}. Continue?"
        stop_disable_service_if_present
    fi

    create_install_dir
    create_venv
    install_package
    configure_ownership
    write_env_file
    write_service_file
    write_wrappercommand_file
    enable_service

    echo
    echo -e "${GREEN}${BOLD}Installation complete.${NC}"
    echo
    echo "Next steps:"
    echo "  1. Set your API key:  ${ENV_FILE}"
    echo "  2. Start the service: systemctl start ${UNIT_NAME}"
    echo "  3. Check its status:  systemctl status ${UNIT_NAME}"
    echo "  4. Follow the logs:   journalctl -fu ${UNIT_NAME}"
    echo
}

main "$@"
