#!/usr/bin/env bash
# blockperf-install.sh — Install and configure the OpenBlockPerf client on a Linux system
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
#   sudo ./blockperf-install.sh
#   sudo ./blockperf-install.sh --update
#   sudo ./blockperf-install.sh --reinstall
#   sudo ./blockperf-install.sh --remove
#
# On Debian/Ubuntu and CentOS/RHEL-family systems, missing dependencies (e.g. jq,
# python3, python3-full / python3-pip) may be installed via the package manager
# after confirmation, or non-interactively with --yes.
#   sudo NETWORK=preprod ./install.sh
#   sudo INSTALL_DIR=/srv/openblockperf SERVICE_USER=ada ./install.sh
#   sudo ./blockperf-install.sh --user-context ada
#   sudo ./blockperf-install.sh --node-unit-name cardano-node.service
#   sudo ./blockperf-install.sh --node-config /path/to/config.json
#   sudo ./blockperf-install.sh --network preprod
#   sudo ./blockperf-install.sh --api-key 'YOUR_KEY'   # or: sudo -E ./install.sh   with OPENBLOCKPERF_API_KEY set
#   sudo ./blockperf-install.sh --api-key-file /root/openblockperf-api-key.txt
#   sudo ./blockperf-install.sh --dry-run
#   sudo PACKAGE_VERSION=0.0.5 ./blockperf-install.sh
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
#                     Default: unset → derived from Shelley genesis or mainnet; use --network to set.
#   NODE_NAME         Operator node label (defaults to OS hostname).
#                     Written to OPENBLOCKPERF_NODE_NAME in /etc/default/openblockperf.
#   NODE_UNIT_NAME    systemd unit for cardano-node (e.g. cardano-node.service).
#                     Default: auto-discover; use --node-unit-name to set explicitly.
#   NODE_CONFIG_PATH  Absolute path to cardano-node config.json (TraceOptions).
#                     Default: derived from the node unit ExecStart; use --node-config.
#   OPENBLOCKPERF_API_KEY  If set before install, written to the env file (same as --api-key).

set -euo pipefail

OBP_DOC_REGISTER_URL="https://openblockperf.cardano.org/docs#TODO"
# Internal installer version (reserved for future remote update checks).
INSTALLER_VERSION="0.2.1"
INSTALLER_REMOTE_URL="https://raw.githubusercontent.com/cardano-foundation/openblockperf/main/blockperf-install.sh"

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
NETWORK="${NETWORK:-}"
NODE_NAME="${NODE_NAME:-}"
NODE_UNIT_NAME="${NODE_UNIT_NAME:-}"
NODE_CONFIG_PATH="${NODE_CONFIG_PATH:-}"
MODE="install"        # install | reinstall | update | remove
ASSUME_YES="false"    # true to skip interactive confirmations
PURGE_CONFIG="false"  # true to remove ENV_FILE on --remove
CLI_USER_CONTEXT=""   # set by --user-context <username> (overrides SERVICE_USER from env)
CLI_NODE_UNIT_NAME="" # set by --node-unit-name <unit>
CLI_NODE_CONFIG=""    # set by --node-config <path>
CLI_NETWORK=""        # set by --network mainnet|preprod|preview
CLI_NODE_NAME=""      # set by --node-name <name>
CLI_API_KEY=""        # set by --api-key <value>
CLI_API_KEY_FILE=""   # set by --api-key-file <path>
DRY_RUN="false"       # true to print plan and resolved values only

# Set by resolve_api_key (Step 6); written to ENV_FILE in write_env_file
API_KEY_TO_INSTALL=""

# Set by write_env_file: new | kept | replaced | replaced-after-backup
ENV_FILE_RESULT=""

# Install artifacts touched in this run (used for rollback hints/cleanup)
CREATED_SERVICE_FILE="false"
CREATED_WRAPPER_FILE="false"
CREATED_ENV_FILE="false"
CREATED_INSTALL_DIR="false"
INSTALL_DIR_EXISTED_BEFORE="false"

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

cleanup_on_failure() {
    warn "Attempting limited rollback for artifacts created in this run..."
    if [[ "${CREATED_SERVICE_FILE}" == "true" && -f "${SERVICE_FILE}" ]]; then
        rm -f "${SERVICE_FILE}" || true
        warn "Removed created service file: ${SERVICE_FILE}"
    fi
    if [[ "${CREATED_WRAPPER_FILE}" == "true" && -f "${WRAPPER_COMMAND}" ]]; then
        rm -f "${WRAPPER_COMMAND}" || true
        warn "Removed created wrapper: ${WRAPPER_COMMAND}"
    fi
    if [[ "${CREATED_ENV_FILE}" == "true" && -f "${ENV_FILE}" ]]; then
        rm -f "${ENV_FILE}" || true
        warn "Removed created env file: ${ENV_FILE}"
    fi
    if [[ "${CREATED_INSTALL_DIR}" == "true" && "${INSTALL_DIR_EXISTED_BEFORE}" != "true" && -d "${INSTALL_DIR}" ]]; then
        rm -rf "${INSTALL_DIR}" || true
        warn "Removed created install dir: ${INSTALL_DIR}"
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true
}

on_error() {
    local line="$1"
    local cmd="$2"
    local code="$3"
    echo
    warn "Installer failed at line ${line} (exit ${code})."
    warn "Command: ${cmd}"
    if [[ "${cmd}" == *"/bin/pip"* || "${cmd}" == *" pip "* ]]; then
        warn "pip failed. Check DNS/network/firewall and package availability."
        warn "For detailed diagnostics, re-run manually with:"
        warn "  ${VENV_DIR}/bin/pip install -v ${PACKAGE_SPEC}"
    fi
    if [[ "${MODE}" == "install" && "${DRY_RUN}" != "true" ]]; then
        cleanup_on_failure
    else
        warn "No automatic rollback performed for mode '${MODE}'."
    fi
    warn "You can safely re-run this installer after fixing the issue."
}

print_intro_and_confirm() {
    echo
    echo -e "${BOLD}OpenBlockPerf installer overview${NC}"
    echo "  Version: ${INSTALLER_VERSION}"
    echo "  1) Check/install prerequisites (Debian/Ubuntu and RHEL-family)"
    echo "  2) Resolve service user/group, node name, and cardano-node unit/config"
    echo "  3) Resolve network and API-key strategy"
    echo "  4) Install venv/package, write env+unit+wrapper, enable service"
    echo "  5) Print summary and next steps"
    echo
    if [[ "${DRY_RUN}" == "true" ]]; then
        warn "Dry-run mode: install/write/start steps are skipped."
        warn "Preflight dependency installs may still be required and are real operations."
        info "You are currently in dry-run mode."
    else
        info "Tip: run with --dry-run first to inspect planned settings."
    fi
    confirm_or_die "Continue?"
}

print_update_intro_and_confirm() {
    echo
    echo -e "${BOLD}OpenBlockPerf package update overview${NC}"
    echo "  Version: ${INSTALLER_VERSION}"
    echo "  1) Check existing virtual environment and package versions"
    echo "  2) Show installed/latest openblockperf version"
    echo "  3) Optionally run: pip install --upgrade openblockperf"
    echo
    info "Only the Python package in ${VENV_DIR} is updated."
    info "No systemd unit, env file, install folder layout, or node config is modified."
    if [[ "${DRY_RUN}" == "true" ]]; then
        info "You are currently in dry-run mode."
    fi
    confirm_or_die "Continue with update mode?"
}

version_gt() {
    # Returns success if $1 > $2
    [[ "$(printf '%s\n' "$1" "$2" | sort -V | tail -n1)" == "$1" && "$1" != "$2" ]]
}

check_installer_update_online() {
    local remote_content remote_version script_path tmp_file
    info "Checking for updates..."
    remote_content="$(curl -fsSL "${INSTALLER_REMOTE_URL}" 2>/dev/null || true)"
    if [[ -z "${remote_content}" ]]; then
        warn "Could not check online installer version from ${INSTALLER_REMOTE_URL}"
        return 0
    fi
    remote_version="$(printf '%s\n' "${remote_content}" | sed -nE 's/^INSTALLER_VERSION="([^"]+)".*/\1/p' | head -n1)"
    [[ -n "${remote_version}" ]] || return 0

    if version_gt "${remote_version}" "${INSTALLER_VERSION}"; then
        info "A newer installer is available: local=${INSTALLER_VERSION}, available=${remote_version}"
        if [[ "${ASSUME_YES}" == "true" || ! -t 0 ]]; then
            info "Non-interactive mode: skipping self-update prompt."
            return 0
        fi
        local ans=""
        read -r -p "Download the newer installer now and restart from it? [y/N]: " ans
        case "${ans}" in
            y|Y|yes|YES)
                script_path="$(realpath "$0" 2>/dev/null || echo "$0")"
                tmp_file="${script_path}.tmp.$$"
                printf '%s' "${remote_content}" > "${tmp_file}"
                chmod +x "${tmp_file}"
                mv "${tmp_file}" "${script_path}"
                if [[ -n "${SUDO_USER:-}" ]] && id "${SUDO_USER}" &>/dev/null; then
                    local sg=""
                    sg="$(id -gn "${SUDO_USER}" 2>/dev/null || true)"
                    if [[ -n "${sg}" ]]; then
                        chown "${SUDO_USER}:${sg}" "${script_path}" 2>/dev/null || true
                    else
                        chown "${SUDO_USER}" "${script_path}" 2>/dev/null || true
                    fi
                fi
                ok "Updated installer at ${script_path}"
                info "Please restart the installer now:"
                info "  sudo ${script_path}"
                exit 0
                ;;
            *)
                info "Continuing with current installer version ${INSTALLER_VERSION}."
                ;;
        esac
    fi
}

usage() {
    cat <<EOF
Usage:
  sudo $0 [--install|--reinstall|--update|--remove] [--yes] [--purge] [--dry-run]
          [--user-context <username>] [--node-unit-name <unit>] [--node-config <path>]
          [--network mainnet|preprod|preview] [--node-name <name>]
          [--api-key <value>|--api-key-file <path>] [--version]

Modes:
  --install      Install if target paths are empty (default)
  --reinstall    Reinstall package and replace install directory
  --update       Update only the installed openblockperf package in the existing venv
  --remove       Remove service, wrapper, and installation directory

Options:
  --yes          Non-interactive: assume "yes" for confirmations (also skips
                 confirmation before installing missing OS packages on supported
                 distros: Debian/Ubuntu and CentOS/RHEL-family)
  --user-context <username>
                 Run the service as this user (primary group unless SERVICE_GROUP
                 is set). Skips interactive user prompts. Same as SERVICE_USER=...
  --node-unit-name <unit>
                 systemd unit for cardano-node (e.g. cardano-node.service). Skips
                 auto-discovery. Same as NODE_UNIT_NAME=...
  --node-config <path>
                 Path to cardano-node config.json (TraceOptions). Skips discovery
                 from the unit ExecStart. Same as NODE_CONFIG_PATH=...
  --network mainnet|preprod|preview
                 Cardano network. Skips genesis-based detection. Same as NETWORK=...
  --node-name <name>
                 Operator node label used as OPENBLOCKPERF_NODE_NAME in ${ENV_FILE}.
                 Defaults to OS hostname if omitted.
  --api-key <value>
                 OPENBLOCKPERF_API_KEY to store in ${ENV_FILE}. Skips prompts. Same as
                 exporting OPENBLOCKPERF_API_KEY=... (visible in process list — prefer env file).
  --api-key-file <path>
                 Read OPENBLOCKPERF_API_KEY from a file (recommended over --api-key).
  --dry-run      Resolve configuration and print plan without changing the system.
  --version      Print installer script version and exit.
  --purge        With --remove, also delete ${ENV_FILE}
  -h, --help     Show this help
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --install) MODE="install"; shift ;;
            --reinstall) MODE="reinstall"; shift ;;
            --update) MODE="update"; shift ;;
            --remove) MODE="remove"; shift ;;
            --yes|-y) ASSUME_YES="true"; shift ;;
            --purge) PURGE_CONFIG="true"; shift ;;
            --user-context)
                [[ $# -ge 2 ]] || die "--user-context requires a username"
                CLI_USER_CONTEXT="$2"
                shift 2
                ;;
            --node-unit-name)
                [[ $# -ge 2 ]] || die "--node-unit-name requires a systemd unit name"
                CLI_NODE_UNIT_NAME="$2"
                shift 2
                ;;
            --node-config)
                [[ $# -ge 2 ]] || die "--node-config requires a path to config.json"
                CLI_NODE_CONFIG="$2"
                shift 2
                ;;
            --network)
                [[ $# -ge 2 ]] || die "--network requires mainnet, preprod, or preview"
                CLI_NETWORK="$2"
                shift 2
                ;;
            --node-name)
                [[ $# -ge 2 ]] || die "--node-name requires a value"
                CLI_NODE_NAME="$2"
                shift 2
                ;;
            --api-key)
                [[ $# -ge 2 ]] || die "--api-key requires a value (use '' for empty)"
                CLI_API_KEY="$2"
                shift 2
                ;;
            --api-key-file)
                [[ $# -ge 2 ]] || die "--api-key-file requires a readable file path"
                CLI_API_KEY_FILE="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN="true"
                shift
                ;;
            --version)
                echo "blockperf-install.sh version ${INSTALLER_VERSION}"
                exit 0
                ;;
            -h|--help) usage; exit 0 ;;
            *)
                die "Unknown argument: $1 (use --help)"
                ;;
        esac
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

ensure_valid_working_directory() {
    if ! pwd >/dev/null 2>&1; then
        warn "Current working directory is no longer available. Switching to /"
        cd / || die "Could not switch to a safe working directory (/)."
    fi
}

# Step 2 — Service user and group 
resolve_service_identity() {
    # Explicit SERVICE_USER from environment or --user-context: no interactive prompts.
    if [[ -n "${CLI_USER_CONTEXT}" ]]; then
        SERVICE_USER="${CLI_USER_CONTEXT}"
    fi

    if [[ -n "${SERVICE_USER}" ]]; then
        id "${SERVICE_USER}" &>/dev/null || die "User '${SERVICE_USER}' does not exist."
        if [[ -z "${SERVICE_GROUP}" ]]; then
            SERVICE_GROUP="$(id -gn "${SERVICE_USER}" 2>/dev/null || true)"
        fi
        [[ -n "${SERVICE_GROUP}" ]] || die "Could not resolve group for '${SERVICE_USER}'. Set SERVICE_GROUP=..."
        getent group "${SERVICE_GROUP}" &>/dev/null || die "Group '${SERVICE_GROUP}' does not exist."
        info "Service identity: ${SERVICE_USER}:${SERVICE_GROUP} (explicit)"
        return 0
    fi

    # Interactive / inferred path
    local guessed_user=""

    if [[ -n "${SUDO_USER:-}" ]]; then
        guessed_user="${SUDO_USER}"
    elif command -v logname &>/dev/null; then
        guessed_user="$(logname 2>/dev/null || true)"
    fi

    if [[ -z "${guessed_user}" ]]; then
        guessed_user="$(whoami 2>/dev/null || true)"
    fi

    if [[ -z "${guessed_user}" || "${guessed_user}" == "root" ]]; then
        if [[ "${ASSUME_YES}" == "true" ]]; then
            die "Could not infer non-root service user. Set SERVICE_USER=..., use --user-context, or run interactively."
        fi
        [[ -t 0 ]] || die "Could not infer non-root service user in non-interactive mode. Set SERVICE_USER=... or --user-context"
        read -r -p "Service user (non-root) to own ${INSTALL_DIR}: " guessed_user
    else
        if [[ "${ASSUME_YES}" == "true" ]]; then
            : # accept guess without prompting
        elif [[ -t 0 ]]; then
            local input=""
            read -r -p "Service user [${guessed_user}] (Enter to keep): " input
            if [[ -n "${input}" ]]; then
                guessed_user="${input}"
            fi
        fi
    fi

    [[ -n "${guessed_user}" ]] || die "Service user cannot be empty."
    [[ "${guessed_user}" != "root" ]] || die "Service user must not be root. Set SERVICE_USER=... or --user-context to a non-root account."

    id "${guessed_user}" &>/dev/null || die "User '${guessed_user}' does not exist."
    SERVICE_USER="${guessed_user}"

    if [[ -z "${SERVICE_GROUP}" ]]; then
        SERVICE_GROUP="$(id -gn "${SERVICE_USER}" 2>/dev/null || true)"
    fi

    [[ -n "${SERVICE_GROUP}" ]] || die "Could not resolve group for '${SERVICE_USER}'. Set SERVICE_GROUP=..."
    getent group "${SERVICE_GROUP}" &>/dev/null || die "Group '${SERVICE_GROUP}' does not exist."

    if [[ -t 0 ]] && [[ "${ASSUME_YES}" != "true" ]]; then
        local ginput=""
        read -r -p "Service group [${SERVICE_GROUP}] (Enter to keep): " ginput
        if [[ -n "${ginput}" ]]; then
            SERVICE_GROUP="${ginput}"
            getent group "${SERVICE_GROUP}" &>/dev/null || die "Group '${SERVICE_GROUP}' does not exist."
        fi
    fi

    info "Service identity: ${SERVICE_USER}:${SERVICE_GROUP}"
}

# Step 2b — Operator node name (hostname-based default)
resolve_node_name() {
    if [[ -n "${CLI_NODE_NAME}" ]]; then
        NODE_NAME="${CLI_NODE_NAME}"
    fi

    if [[ -z "${NODE_NAME}" ]]; then
        NODE_NAME="$(hostname 2>/dev/null || true)"
    fi
    if [[ -z "${NODE_NAME}" ]]; then
        NODE_NAME="$(uname -n 2>/dev/null || true)"
    fi
    [[ -n "${NODE_NAME}" ]] || NODE_NAME="node-unknown"

    if [[ "${ASSUME_YES}" != "true" ]] && [[ -t 0 ]] && [[ -z "${CLI_NODE_NAME}" ]]; then
        local in_name=""
        read -r -p "This node name [${NODE_NAME}] (used in aggregated data): " in_name
        if [[ -n "${in_name}" ]]; then
            NODE_NAME="${in_name}"
        fi
    fi

    [[ -n "${NODE_NAME}" ]] || die "NODE_NAME cannot be empty."
    info "Node name: ${NODE_NAME}"
}

# Step 3 — Cardano node systemd unit
normalize_node_unit_name() {
    local u="$1"
    u="${u%.service}"
    u="${u}.service"
    printf '%s' "${u}"
}

node_unit_exists() {
    local u="$1"
    [[ -n "${u}" ]] || return 1
    systemctl cat "${u}" &>/dev/null && return 0
    [[ -f "/etc/systemd/system/${u}" ]] || [[ -f "/lib/systemd/system/${u}" ]] || [[ -f "/usr/lib/systemd/system/${u}" ]]
}

validate_node_unit_or_die() {
    local u="$1"
    node_unit_exists "${u}" || die "systemd unit '${u}' not found. Check the name (systemctl list-unit-files) or pass NODE_UNIT_NAME= / --node-unit-name."
}

collect_cardano_node_unit_candidates() {
    declare -A seen
    local line u f b d

    while IFS= read -r line; do
        [[ -z "${line}" || "${line}" =~ ^# ]] && continue
        u="${line%% *}"
        [[ "${u}" == *.service ]] || continue
        case "${u,,}" in
            *openblockperf*) continue ;;
            cnode-*) continue ;;
            *cardano*|*cnode*) seen["${u}"]=1 ;;
        esac
    done < <(systemctl list-unit-files --type=service --no-legend 2>/dev/null || true)

    for d in /etc/systemd/system /lib/systemd/system /usr/lib/systemd/system; do
        [[ -d "${d}" ]] || continue
        for f in "${d}"/*.service; do
            [[ -f "${f}" ]] || continue
            b=$(basename "${f}")
            case "${b,,}" in
                *openblockperf*) continue ;;
                cnode-*) continue ;;
                *cardano*|*cnode*) seen["${b}"]=1 ;;
            esac
        done
    done

    if [[ ${#seen[@]} -eq 0 ]]; then
        return 0
    fi
    printf '%s\n' "${!seen[@]}" | LC_ALL=C sort -u
}

resolve_cardano_node_unit() {
    if [[ -n "${CLI_NODE_UNIT_NAME}" ]]; then
        NODE_UNIT_NAME="$(normalize_node_unit_name "${CLI_NODE_UNIT_NAME}")"
    fi

    if [[ -n "${NODE_UNIT_NAME}" ]]; then
        NODE_UNIT_NAME="$(normalize_node_unit_name "${NODE_UNIT_NAME}")"
        validate_node_unit_or_die "${NODE_UNIT_NAME}"
        info "Cardano node unit: ${NODE_UNIT_NAME} (explicit)"
        return 0
    fi

    local -a candidates=()
    local line
    while IFS= read -r line; do
        [[ -n "${line}" ]] && candidates+=("${line}")
    done < <(collect_cardano_node_unit_candidates)
    local n=${#candidates[@]}

    if [[ "${n}" -eq 1 ]]; then
        NODE_UNIT_NAME="${candidates[0]}"
        validate_node_unit_or_die "${NODE_UNIT_NAME}"
        info "Cardano node unit: ${NODE_UNIT_NAME} (auto-detected)"
        return 0
    fi

    if [[ "${n}" -gt 1 ]]; then
        if [[ "${ASSUME_YES}" == "true" ]]; then
            die "Multiple Cardano node units found (${n}). Set NODE_UNIT_NAME= or --node-unit-name to choose one: $(printf '%s ' "${candidates[@]}")"
        fi
        [[ -t 0 ]] || die "Multiple Cardano node units found. Set NODE_UNIT_NAME= or --node-unit-name (TTY required to choose interactively)."
        echo
        warn "Multiple systemd units matching cardano/cnode were found:"
        local i sel
        for i in "${!candidates[@]}"; do
            echo "  $((i + 1))) ${candidates[$i]}"
        done
        read -r -p "Select 1-${n}, or type a full unit name (e.g. cardano-node.service): " sel
        if [[ "${sel}" =~ ^[0-9]+$ ]] && (( sel >= 1 && sel <= n )); then
            NODE_UNIT_NAME="${candidates[$((sel - 1))]}"
        else
            [[ -n "${sel}" ]] || die "No unit selected."
            NODE_UNIT_NAME="$(normalize_node_unit_name "${sel}")"
        fi
        validate_node_unit_or_die "${NODE_UNIT_NAME}"
        info "Cardano node unit: ${NODE_UNIT_NAME}"
        return 0
    fi

    # No candidates
    if [[ "${ASSUME_YES}" == "true" ]]; then
        die "No Cardano node systemd unit found (cardano/cnode). Install the node unit or set NODE_UNIT_NAME= / --node-unit-name."
    fi
    [[ -t 0 ]] || die "No Cardano node unit found. Set NODE_UNIT_NAME= or --node-unit-name (or run interactively)."
    local manual=""
    read -r -p "systemd unit name for cardano-node (e.g. cardano-node.service): " manual
    [[ -n "${manual}" ]] || die "No unit name given."
    NODE_UNIT_NAME="$(normalize_node_unit_name "${manual}")"
    validate_node_unit_or_die "${NODE_UNIT_NAME}"
    info "Cardano node unit: ${NODE_UNIT_NAME}"
}

# Step 4 — Node config.json path (TraceOptions backend validation is skipped for now)

extract_config_from_execstart_string() {
    local s="$1"
    [[ -n "${s}" ]] || return 1
    if [[ "${s}" =~ --config-yaml[[:space:]]+([^[:space:];}]+) ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
        return 0
    fi
    if [[ "${s}" =~ --config[[:space:]]+([^[:space:];}]+) ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
        return 0
    fi
    if [[ "${s}" =~ -config[[:space:]]+([^[:space:];}]+) ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
        return 0
    fi
    return 1
}

# CNTOOLS-style units use ExecStart=/bin/bash -l -c "exec .../scripts/cnode.sh"
# with config at the sibling path .../files/config.json .
extract_cntools_config_path_from_execstart_string() {
    local s="$1"
    [[ -n "${s}" ]] || return 1
    if [[ "${s}" =~ (/[^[:space:];\"]+/scripts/cnode\.sh) ]]; then
        local script_path="${BASH_REMATCH[1]}"
        local out="${script_path/scripts\/cnode.sh/files\/config.json}"
        printf '%s' "${out}"
        return 0
    fi
    return 1
}

extract_config_from_env_string() {
    local e="$1"
    [[ -n "${e}" ]] || return 1
    if [[ "${e}" =~ (^|[[:space:]])CONFIG=([^[:space:]]+) ]]; then
        printf '%s' "${BASH_REMATCH[2]}"
        return 0
    fi
    if [[ "${e}" =~ (^|[[:space:]])NODE_CONFIG=([^[:space:]]+) ]]; then
        printf '%s' "${BASH_REMATCH[2]}"
        return 0
    fi
    if [[ "${e}" =~ (^|[[:space:]])CONFIG_FILE=([^[:space:]]+) ]]; then
        printf '%s' "${BASH_REMATCH[2]}"
        return 0
    fi
    return 1
}

make_absolute_path() {
    local p="$1"
    local wd="$2"
    [[ -n "${p}" ]] || return 1
    if [[ "${p}" == /* ]]; then
        printf '%s' "${p}"
        return 0
    fi
    [[ -n "${wd}" ]] || return 1
    printf '%s' "${wd%/}/${p}"
}

extract_config_path_from_systemd_unit() {
    local unit="$1"
    local ex envs wd path cat_line
    ex="$(systemctl show "${unit}" -p ExecStart --value 2>/dev/null || true)"
    envs="$(systemctl show "${unit}" -p Environment --value 2>/dev/null || true)"
    wd="$(systemctl show "${unit}" -p WorkingDirectory --value 2>/dev/null || true)"
    path=""
    path="$(extract_config_from_execstart_string "${ex}")" || path=""
    if [[ -z "${path}" ]]; then
        path="$(extract_cntools_config_path_from_execstart_string "${ex}")" || path=""
    fi
    if [[ -z "${path}" && -n "${envs}" ]]; then
        path="$(extract_config_from_env_string "${envs}")" || path=""
    fi
    if [[ -z "${path}" ]]; then
        cat_line="$(systemctl cat "${unit}" 2>/dev/null | grep -m1 '^ExecStart=' | sed 's/^ExecStart=//' || true)"
        path="$(extract_config_from_execstart_string "${cat_line}")" || path=""
    fi
    if [[ -z "${path}" ]]; then
        path="$(extract_cntools_config_path_from_execstart_string "${cat_line}")" || path=""
    fi
    [[ -n "${path}" ]] || return 1
    if [[ "${path}" != /* ]]; then
        path="$(make_absolute_path "${path}" "${wd}")" || return 1
    fi
    printf '%s' "${path}"
}

resolve_node_config_path() {
    if [[ -n "${CLI_NODE_CONFIG}" ]]; then
        NODE_CONFIG_PATH="${CLI_NODE_CONFIG}"
    fi

    local origin="explicit"
    if [[ -z "${NODE_CONFIG_PATH}" ]]; then
        local discovered=""
        discovered="$(extract_config_path_from_systemd_unit "${NODE_UNIT_NAME}" 2>/dev/null || true)"
        if [[ -n "${discovered}" ]]; then
            NODE_CONFIG_PATH="${discovered}"
            origin="systemd"
        fi
    fi

    if [[ -z "${NODE_CONFIG_PATH}" ]]; then
        if [[ "${ASSUME_YES}" == "true" ]]; then
            die "Could not determine cardano-node config.json. Set NODE_CONFIG_PATH= or --node-config."
        fi
        [[ -t 0 ]] || die "Could not determine cardano-node config.json. Set NODE_CONFIG_PATH= or --node-config (or run interactively)."
        read -r -p "Absolute path to cardano-node config.json: " NODE_CONFIG_PATH
        origin="prompt"
        [[ -n "${NODE_CONFIG_PATH}" ]] || die "No path given."
    fi

    [[ -f "${NODE_CONFIG_PATH}" ]] || die "Node config file not found: ${NODE_CONFIG_PATH}"

    jq -e '.' "${NODE_CONFIG_PATH}" &>/dev/null || die "Node config is not valid JSON: ${NODE_CONFIG_PATH}"

    case "${origin}" in
        explicit) info "Node config: ${NODE_CONFIG_PATH} (explicit)" ;;
        systemd)  info "Node config: ${NODE_CONFIG_PATH} (from ${NODE_UNIT_NAME} ExecStart/Environment)" ;;
        prompt)   info "Node config: ${NODE_CONFIG_PATH}" ;;
    esac

    ok "Node config JSON OK (${NODE_CONFIG_PATH})."
}

# Step 5 — Cardano network
derive_network_from_shelley_genesis() {
    local cfg="$1"
    local rel dir abs magic
    [[ -f "${cfg}" ]] || return 1
    rel="$(jq -r '.ShelleyGenesisFile // empty' "${cfg}")"
    [[ -n "${rel}" && "${rel}" != "null" ]] || return 1
    dir="$(dirname "${cfg}")"
    if [[ "${rel}" == /* ]]; then
        abs="${rel}"
    else
        abs="${dir}/${rel}"
    fi
    [[ -f "${abs}" ]] || return 1
    magic="$(jq -r '.networkMagic // empty' "${abs}")"
    [[ -n "${magic}" && "${magic}" != "null" ]] || return 1
    case "${magic}" in
        764824073) printf '%s' "mainnet" ;;
        1)         printf '%s' "preprod" ;;
        2)         printf '%s' "preview" ;;
        *)         return 1 ;;
    esac
    return 0
}

resolve_network() {
    if [[ -n "${CLI_NETWORK}" ]]; then
        NETWORK="${CLI_NETWORK}"
        info "Network: ${NETWORK} (--network)"
        check_network_value
        return 0
    fi

    if [[ -n "${NETWORK}" ]]; then
        info "Network: ${NETWORK} (NETWORK environment)"
        check_network_value
        return 0
    fi

    local derived=""
    derived="$(derive_network_from_shelley_genesis "${NODE_CONFIG_PATH}" 2>/dev/null || true)"
    if [[ -n "${derived}" ]]; then
        NETWORK="${derived}"
        info "Network: ${NETWORK} (from Shelley genesis networkMagic)"
        check_network_value
        return 0
    fi

    if [[ "${ASSUME_YES}" == "true" ]]; then
        NETWORK="mainnet"
        warn "Network: mainnet (default; set NETWORK= or --network to override)"
        check_network_value
        return 0
    fi

    if [[ -t 0 ]]; then
        local ans=""
        read -r -p "Cardano network [mainnet|preprod|preview] [mainnet]: " ans
        NETWORK="${ans:-mainnet}"
    else
        NETWORK="mainnet"
        warn "Network: mainnet (default; no TTY — set NETWORK= or --network to choose)"
    fi

    check_network_value
}

# Step 6 — openBlockperf API key 
resolve_api_key() {
    API_KEY_TO_INSTALL=""
    if [[ -n "${CLI_API_KEY}" && -n "${CLI_API_KEY_FILE}" ]]; then
        die "Use only one of --api-key or --api-key-file."
    fi
    if [[ -n "${CLI_API_KEY_FILE}" ]]; then
        [[ -r "${CLI_API_KEY_FILE}" ]] || die "API key file is not readable: ${CLI_API_KEY_FILE}"
        API_KEY_TO_INSTALL="$(<"${CLI_API_KEY_FILE}")"
        API_KEY_TO_INSTALL="${API_KEY_TO_INSTALL%$'\n'}"
        info "API key: loaded from file (${CLI_API_KEY_FILE})"
        return 0
    fi
    if [[ -n "${CLI_API_KEY}" ]]; then
        API_KEY_TO_INSTALL="${CLI_API_KEY}"
        info "API key: provided (--api-key)"
        return 0
    fi
    if [[ -n "${OPENBLOCKPERF_API_KEY:-}" ]]; then
        API_KEY_TO_INSTALL="${OPENBLOCKPERF_API_KEY}"
        info "API key: from OPENBLOCKPERF_API_KEY environment"
        return 0
    fi

    if [[ "${ASSUME_YES}" == "true" ]]; then
        warn "No API key (--api-key or OPENBLOCKPERF_API_KEY). Add OPENBLOCKPERF_API_KEY to ${ENV_FILE} before starting the service."
        return 0
    fi

    if [[ ! -t 0 ]]; then
        warn "No API key (non-interactive, no TTY). Set OPENBLOCKPERF_API_KEY or use --api-key."
        return 0
    fi

    local ans=""
    read -r -p "Do you already have a Blockperf API key? [y/N]: " ans
    case "${ans}" in
        y|Y|yes|YES)
            read -r -s -p "Enter OPENBLOCKPERF_API_KEY value (input hidden): " API_KEY_TO_INSTALL
            echo
            ;;
        *)
            echo
            info "After this install finishes, register your pool and obtain an API key with:"
            echo "    blockperf register"
            info "Registration requires a Calidus key; see:  ${OBP_DOC_REGISTER_URL}"
            info "Then set OPENBLOCKPERF_API_KEY in ${ENV_FILE} and start the service."
            ;;
    esac
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

# ---------------------------------------------------------------------------
# Step 1 — Preflight: required commands and optional OS package install
# (Debian/Ubuntu and CentOS/RHEL-family only)
# ---------------------------------------------------------------------------
DISTRO_FAMILY="" # debian | rhel | unknown

detect_distro_family() {
    DISTRO_FAMILY="unknown"
    [[ -f /etc/os-release ]] || return 0
    # shellcheck source=/dev/null
    . /etc/os-release
    case "${ID,,}" in
        debian|ubuntu|linuxmint|raspbian) DISTRO_FAMILY="debian" ;;
        rhel|centos|fedora|rocky|almalinux|ol|virtuozzo) DISTRO_FAMILY="rhel" ;;
        *) DISTRO_FAMILY="unknown" ;;
    esac
}

run_apt_install() {
    command -v apt-get &>/dev/null || die "apt-get not found; cannot install packages on this system."
    info "Running: apt-get update && apt-get install -y $*"
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}

run_rhel_install() {
    if command -v dnf &>/dev/null; then
        info "Running: dnf install -y $*"
        dnf install -y "$@"
    elif command -v yum &>/dev/null; then
        info "Running: yum install -y $*"
        yum install -y "$@"
    else
        die "Neither dnf nor yum found; cannot install packages on this system."
    fi
}

ensure_ensurepip_available() {
    "${PYTHON}" -m ensurepip --version &>/dev/null && return 0
    local pkg_deb="" pkg_rpm=""
    case "${DISTRO_FAMILY}" in
        debian) pkg_deb="python3-full" ;;
        rhel)   pkg_rpm="python3-pip" ;;
        *)
            die "'${PYTHON}' has no ensurepip module. On Debian/Ubuntu install python3-full; on RHEL install python3-pip. Then re-run."
            ;;
    esac
    echo
    warn "'${PYTHON}' cannot run ensurepip (needed for pip in the venv)."
    if [[ "${DRY_RUN}" == "true" ]]; then
        warn "Dry-run note: package installation in preflight is a real operation."
    fi
    if [[ -n "${pkg_deb}" ]]; then
        warn "Will install package: ${pkg_deb}"
        confirm_or_die "Proceed with installation?"
        run_apt_install "${pkg_deb}"
    else
        warn "Will install package: ${pkg_rpm}"
        confirm_or_die "Proceed with installation?"
        run_rhel_install "${pkg_rpm}"
    fi
    "${PYTHON}" -m ensurepip --version &>/dev/null \
        || die "'${PYTHON}' still has no ensurepip after installing packages."
}

ensure_dependencies_step1() {
    detect_distro_family
    local -A deb_pkgs_
    local -A rpm_pkgs_
    local c
    local need_core=false

    if ! command -v "${PYTHON}" &>/dev/null; then
        case "${DISTRO_FAMILY}" in
            debian) deb_pkgs_[python3]=1 ;;
            rhel)   rpm_pkgs_[python3]=1 ;;
            *)
                die "Python interpreter '${PYTHON}' not found. Install Python 3.12+ (this script only auto-installs packages on Debian/Ubuntu and CentOS/RHEL-family)."
                ;;
        esac
    fi

    if ! command -v jq &>/dev/null; then
        case "${DISTRO_FAMILY}" in
            debian) deb_pkgs_[jq]=1 ;;
            rhel)   rpm_pkgs_[jq]=1 ;;
            *)
                die "Command 'jq' not found. Install the 'jq' package, then re-run (auto-install is only supported on Debian/Ubuntu and CentOS/RHEL-family)."
                ;;
        esac
    fi

    if ! command -v curl &>/dev/null; then
        case "${DISTRO_FAMILY}" in
            debian) deb_pkgs_[curl]=1 ;;
            rhel)   rpm_pkgs_[curl]=1 ;;
            *)
                die "Command 'curl' not found. Install curl, then re-run (auto-install is only supported on Debian/Ubuntu and CentOS/RHEL-family)."
                ;;
        esac
    fi

    if ! command -v systemctl &>/dev/null; then
        case "${DISTRO_FAMILY}" in
            debian) deb_pkgs_[systemd]=1 ;;
            rhel)   rpm_pkgs_[systemd]=1 ;;
            *)
                die "Command 'systemctl' not found. Install systemd (this script only auto-installs packages on Debian/Ubuntu and CentOS/RHEL-family)."
                ;;
        esac
    fi

    local core_cmds=(id getent mkdir rm chmod chown install)
    for c in "${core_cmds[@]}"; do
        if ! command -v "${c}" &>/dev/null; then
            need_core=true
            break
        fi
    done
    if [[ "${need_core}" == true ]]; then
        case "${DISTRO_FAMILY}" in
            debian) deb_pkgs_[coreutils]=1 ;;
            rhel)   rpm_pkgs_[coreutils]=1 ;;
            *)
                die "Required core utility command missing from PATH. Install coreutils, then re-run."
                ;;
        esac
    fi

    local pkgs_deb=("${!deb_pkgs_[@]}")
    local pkgs_rpm=("${!rpm_pkgs_[@]}")

    if [[ ${#pkgs_deb[@]} -gt 0 || ${#pkgs_rpm[@]} -gt 0 ]]; then
        echo
        warn "The following OS packages will be installed to satisfy missing commands:"
        if [[ "${DRY_RUN}" == "true" ]]; then
            warn "Dry-run note: this preflight installation is real."
        fi
        if [[ ${#pkgs_deb[@]} -gt 0 ]]; then
            warn "  (Debian/Ubuntu) ${pkgs_deb[*]}"
        fi
        if [[ ${#pkgs_rpm[@]} -gt 0 ]]; then
            warn "  (RHEL/CentOS-family) ${pkgs_rpm[*]}"
        fi
        confirm_or_die "Proceed with installation?"
        if [[ ${#pkgs_deb[@]} -gt 0 ]]; then
            run_apt_install "${pkgs_deb[@]}"
        fi
        if [[ ${#pkgs_rpm[@]} -gt 0 ]]; then
            run_rhel_install "${pkgs_rpm[@]}"
        fi
    fi

    command -v "${PYTHON}" &>/dev/null || die "After package install, '${PYTHON}' is still not in PATH. Set PYTHON= to the installed interpreter."
    command -v jq &>/dev/null || die "Command 'jq' not found after package install."
    command -v curl &>/dev/null || die "Command 'curl' not found after package install."
    command -v systemctl &>/dev/null || die "Command 'systemctl' not found after package install."

    ensure_ensurepip_available
}

check_remove_prerequisites() {
    command -v systemctl &>/dev/null || die "systemctl not found. This installer requires systemd."
    command -v rm &>/dev/null || die "Command 'rm' not found."
}

check_required_commands() {
    local cmds=("id" "getent" "mkdir" "rm" "chmod" "chown" "install" "jq" "curl")
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
    [[ -d "${INSTALL_DIR}" ]] && INSTALL_DIR_EXISTED_BEFORE="true"
    if [[ -d "${INSTALL_DIR}" ]]; then
        if [[ "${MODE}" == "install" ]]; then
            die "Install directory already exists: ${INSTALL_DIR}. Use --reinstall to replace it."
        fi
        # In reinstall mode we keep INSTALL_DIR and replace only VENV_DIR.
        # If cwd is inside VENV_DIR, removing it will break later os.getcwd()
        # calls (e.g. python -m venv -> pip bootstrap). Move to a safe cwd first.
        local current_pwd="" venv_real=""
        current_pwd="$(pwd -P 2>/dev/null || true)"
        if command -v realpath &>/dev/null; then
            venv_real="$(realpath -m "${VENV_DIR}" 2>/dev/null || echo "${VENV_DIR}")"
        else
            venv_real="${VENV_DIR}"
        fi
        if [[ -n "${current_pwd}" && -n "${venv_real}" && "${current_pwd}" == "${venv_real}"* ]]; then
            warn "Current working directory is inside ${VENV_DIR}; switching to / before reinstall cleanup."
            cd /
        fi
        if [[ -d "${VENV_DIR}" ]]; then
            ok "Reinstall mode: replacing virtual environment directory: ${VENV_DIR}"
            rm -rf "${VENV_DIR}"
        else
            info "Reinstall mode: no existing virtual environment found at ${VENV_DIR}; creating fresh."
        fi
    else
        ok "Creating installation directory: ${INSTALL_DIR}"
        CREATED_INSTALL_DIR="true"
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
    if ! "${VENV_DIR}/bin/pip" install --quiet "${PACKAGE_SPEC}"; then
        warn "Package install failed for ${PACKAGE_SPEC}."
        warn "Try manually with verbose output:"
        warn "  ${VENV_DIR}/bin/pip install -v ${PACKAGE_SPEC}"
        die "pip install failed."
    fi
    local installed_version
}

get_current_installed_package_version() {
    [[ -x "${VENV_DIR}/bin/pip" ]] || return 1
    "${VENV_DIR}/bin/pip" show "${PACKAGE_NAME}" 2>/dev/null | sed -nE 's/^Version: (.+)$/\1/p' | head -n1
}

get_latest_pypi_package_version() {
    [[ -x "${VENV_DIR}/bin/pip" ]] || return 1
    "${VENV_DIR}/bin/pip" index versions "${PACKAGE_NAME}" 2>/dev/null | sed -nE "s/^${PACKAGE_NAME} \\(([^)]+)\\).*/\1/p" | head -n1
}

get_pypi_summary_text() {
    curl -fsSL "https://pypi.org/pypi/${PACKAGE_NAME}/json" 2>/dev/null | jq -r '.info.summary // empty' 2>/dev/null || true
}

update_package_only_mode() {
    [[ -x "${VENV_DIR}/bin/pip" ]] || die "No venv found at ${VENV_DIR}. Install first before using --update."

    local current_version latest_version summary
    current_version="$(get_current_installed_package_version || true)"
    latest_version="$(get_latest_pypi_package_version || true)"
    summary="$(get_pypi_summary_text || true)"

    echo
    echo -e "${BOLD}OpenBlockPerf Package Update${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf "  %-20s %s\n" "Installer version:" "${INSTALLER_VERSION}"
    printf "  %-20s %s\n" "Currently installed:" "${current_version:-unknown}"
    printf "  %-20s %s\n" "Latest on PyPI:" "${latest_version:-unknown}"
    if [[ -n "${summary}" ]]; then
        printf "  %-20s %s\n" "Release info:" "${summary}"
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo

    if [[ "${DRY_RUN}" == "true" ]]; then
        ok "Dry-run complete for --update. No package changes applied."
        return 0
    fi

    if [[ -n "${current_version}" && -n "${latest_version}" && "${current_version}" == "${latest_version}" ]]; then
        ok "openblockperf is already up to date (${current_version})."
        return 0
    fi

    confirm_or_die "Proceed with package update now?"
    if ! "${VENV_DIR}/bin/pip" install --quiet --upgrade "${PACKAGE_NAME}"; then
        warn "Package update failed."
        warn "Try manually with verbose output:"
        warn "  ${VENV_DIR}/bin/pip install -v --upgrade ${PACKAGE_NAME}"
        die "pip update failed."
    fi
    local updated_version
    updated_version="$(get_current_installed_package_version || true)"
    ok "Updated ${PACKAGE_NAME} to ${updated_version:-unknown}."
}

configure_ownership() {
    id "${SERVICE_USER}" &>/dev/null || die "User '${SERVICE_USER}' does not exist."
    getent group "${SERVICE_GROUP}" &>/dev/null || die "Group '${SERVICE_GROUP}' does not exist."
    chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DIR}"
    ok "Ownership of ${INSTALL_DIR} set to ${SERVICE_USER}:${SERVICE_GROUP}."
}

write_env_file() {
    ENV_FILE_RESULT="new"

    if [[ -f "${ENV_FILE}" ]]; then
        if [[ -t 0 ]] && [[ "${ASSUME_YES}" != "true" ]]; then
            local choice=""
            read -r -p "Environment file ${ENV_FILE} already exists. Replace with a new file from this run, or keep the existing file? [R/k] (default R): " choice
            case "${choice:-R}" in
                k|K|keep|KEEP)
                    warn "Keeping existing environment file: ${ENV_FILE}"
                    ENV_FILE_RESULT="kept"
                    return 0
                    ;;
                r|R|replace|REPLACE|"")
                    ok "Replacing existing environment file: ${ENV_FILE}"
                    ENV_FILE_RESULT="replaced"
                    ;;
                *)
                    die "Invalid choice '${choice}'. Use R (replace) or k (keep)."
                    ;;
            esac
        else
            local backup=""
            backup="$(dirname "${ENV_FILE}")/$(basename "${ENV_FILE}")-$(date +%Y-%m-%d_%H-%M).backup"
            if [[ -e "${backup}" ]]; then
                backup="$(dirname "${ENV_FILE}")/$(basename "${ENV_FILE}")-$(date +%Y-%m-%d_%H-%M-%S).backup"
            fi
            mv "${ENV_FILE}" "${backup}"
            ok "Non-interactive: renamed existing env file to ${backup}"
            ENV_FILE_RESULT="replaced-after-backup"
        fi
    fi

    local api_line
    if [[ -n "${API_KEY_TO_INSTALL}" ]]; then
        api_line="OPENBLOCKPERF_API_KEY=$(printf '%q' "${API_KEY_TO_INSTALL}")"
    else
        api_line="OPENBLOCKPERF_API_KEY="
    fi

    ok "Writing environment file: ${ENV_FILE}"
    mkdir -p "$(dirname "${ENV_FILE}")"
    cat > "${ENV_FILE}" <<EOF
# OpenBlockPerf client configuration
# Documentation: https://openblockperf.readthedocs.io
#
# All variables use the OPENBLOCKPERF_ prefix (pydantic-settings convention).
# After editing this file, restart the service:
#   systemctl restart ${UNIT_NAME}

# -----------------------------------------------------------------------
# API key (from blockperf register); Calidus key required — ${OBP_DOC_REGISTER_URL}
# -----------------------------------------------------------------------
${api_line}

# -----------------------------------------------------------------------
# Cardano network: mainnet | preprod | preview
# -----------------------------------------------------------------------
OPENBLOCKPERF_NETWORK=${NETWORK}

# -----------------------------------------------------------------------
# Client log level: DEBUG | INFO | WARNING | ERROR | EXCEPTION
# -----------------------------------------------------------------------
OPENBLOCKPERF_LOG_LEVEL=WARNING

# -----------------------------------------------------------------------
# Operator-defined node label (used to identify this node in aggregated data)
# -----------------------------------------------------------------------
OPENBLOCKPERF_NODE_NAME=${NODE_NAME}

# -----------------------------------------------------------------------
# cardano-node config.json path (resolved by install.sh)
# -----------------------------------------------------------------------
OPENBLOCKPERF_NODE_CONFIG=${NODE_CONFIG_PATH}

# -----------------------------------------------------------------------
# cardano-node systemd unit name (used for journald node log lookup)
# -----------------------------------------------------------------------
OPENBLOCKPERF_NODE_UNIT_NAME=${NODE_UNIT_NAME}

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
    if [[ "${ENV_FILE_RESULT}" == "new" || "${ENV_FILE_RESULT}" == "replaced" || "${ENV_FILE_RESULT}" == "replaced-after-backup" ]]; then
        CREATED_ENV_FILE="true"
    fi
    echo
    if [[ -z "${API_KEY_TO_INSTALL}" ]]; then
        warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        warn " ACTION REQUIRED: Set OPENBLOCKPERF_API_KEY in ${ENV_FILE}"
        warn " before starting the service."
        warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo
    fi
}

# Step 7 — Install core (venv, package, env, systemd, wrapper, enable)
install_core() {
    create_install_dir
    create_venv
    install_package
    configure_ownership
    write_env_file
    write_service_file
    write_wrappercommand_file
    enable_service
}

maybe_start_service_after_install() {
    [[ -n "${API_KEY_TO_INSTALL}" ]] || return 0
    if [[ "${ASSUME_YES}" == "true" ]]; then
        info "Starting ${UNIT_NAME} (--yes and API key present) ..."
        local start_out=""
        if start_out="$(systemctl start "${UNIT_NAME}" 2>&1)"; then
            ok "Started ${UNIT_NAME}."
        else
            warn "Could not start ${UNIT_NAME}."
            warn "${start_out}"
            warn "Fix issues and run: systemctl start ${UNIT_NAME}"
        fi
        return 0
    fi
    [[ -t 0 ]] || return 0
    local st=""
    read -r -p "Start ${UNIT_NAME} now (API key is configured)? [y/N]: " st
    case "${st}" in
        y|Y|yes|YES)
            local start_out=""
            if start_out="$(systemctl start "${UNIT_NAME}" 2>&1)"; then
                ok "Started ${UNIT_NAME}."
            else
                warn "Could not start ${UNIT_NAME}."
                warn "${start_out}"
                warn "Run: systemctl start ${UNIT_NAME}"
            fi
            ;;
        *) ;;
    esac
}

print_post_install_summary() {
    echo
    echo -e "${GREEN}${BOLD}Installation complete.${NC}"
    echo "Installer version: ${INSTALLER_VERSION}"
    echo
    echo "Summary:"
    echo "  • Virtual env:     ${VENV_DIR}"
    echo "  • CLI wrapper:     ${WRAPPER_COMMAND}"
    echo "  • Environment:     ${ENV_FILE}"
    case "${ENV_FILE_RESULT}" in
        new)                    echo "  • Env file action: created new" ;;
        kept)                   echo "  • Env file action: kept existing (not overwritten)" ;;
        replaced)               echo "  • Env file action: replaced in place" ;;
        replaced-after-backup)  echo "  • Env file action: previous file renamed to *.backup, new file written" ;;
        *)                      echo "  • Env file action: ${ENV_FILE_RESULT:-unknown}" ;;
    esac
    echo "  • systemd unit:    ${SERVICE_FILE} (enabled)"
    echo
    if [[ -n "${API_KEY_TO_INSTALL}" ]]; then
        echo "Next steps:"
        echo "  1. Start the service (if not already):  systemctl start ${UNIT_NAME}"
        echo "  2. Status:   systemctl status ${UNIT_NAME}"
        echo "  3. Logs:     journalctl -fu ${UNIT_NAME}"
    else
        echo "Next steps (API key not set in this run):"
        echo "  1. Register and obtain an API key:"
        echo "       ${INSTALL_DIR}/venv/bin/blockperf register"
        echo "     A Calidus key is required; documentation:  ${OBP_DOC_REGISTER_URL}"
        echo "  2. Set OPENBLOCKPERF_API_KEY in ${ENV_FILE}"
        echo "  3. Start the service:  systemctl start ${UNIT_NAME}"
        echo "  4. Status:  systemctl status ${UNIT_NAME}"
        echo "  5. Logs:    journalctl -fu ${UNIT_NAME}"
    fi
    if [[ "${ENV_FILE_RESULT}" == "kept" ]]; then
        echo
        warn "The existing env file was kept. Resolved values from this run were NOT written."
        warn "Check and update these entries manually in ${ENV_FILE}:"
        warn "  OPENBLOCKPERF_NETWORK=${NETWORK}"
        warn "  OPENBLOCKPERF_NODE_NAME=${NODE_NAME}"
        warn "  OPENBLOCKPERF_NODE_CONFIG=${NODE_CONFIG_PATH}"
        warn "  OPENBLOCKPERF_NODE_UNIT_NAME=${NODE_UNIT_NAME}"
    fi
    echo
}

write_service_file() {
    local bin="${VENV_DIR}/bin/blockperf"
    ok "Writing systemd unit: ${SERVICE_FILE}"
    mkdir -p "$(dirname "${SERVICE_FILE}")"
    cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=OpenBlockPerf Client
Documentation=https://openblockperf.readthedocs.io
After=network-online.target
Wants=network-online.target
${NODE_UNIT_NAME:+After=${NODE_UNIT_NAME}}

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${INSTALL_DIR}
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
    CREATED_SERVICE_FILE="true"
}

write_wrappercommand_file() {
    local bin="${WRAPPER_COMMAND}"
    ok "Writing wrapper command: ${WRAPPER_COMMAND}"
    mkdir -p "$(dirname "${WRAPPER_COMMAND}")"
    cat > "${WRAPPER_COMMAND}" <<EOF
#!/usr/bin/env bash
exec ${INSTALL_DIR}/venv/bin/blockperf "\$@"
EOF

    chmod 755 "${WRAPPER_COMMAND}"
    CREATED_WRAPPER_FILE="true"
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
    trap 'on_error "${LINENO}" "${BASH_COMMAND}" "$?"' ERR
    ensure_valid_working_directory
    parse_args "$@"
    if [[ "${MODE}" == "remove" && "${DRY_RUN}" == "true" ]]; then
        die "--dry-run is only available for install/reinstall."
    fi
    check_root
    check_linux

    # Always check for newer installer before any intro/wizard output.
    if [[ "${MODE}" != "remove" ]]; then
        check_installer_update_online
    fi

    # Show interactive overview before any package-install prompts.
    if [[ "${MODE}" != "remove" ]] && [[ "${ASSUME_YES}" != "true" ]]; then
        if [[ "${MODE}" == "update" ]]; then
            print_update_intro_and_confirm
        else
            print_intro_and_confirm
        fi
    fi

    if [[ "${MODE}" == "remove" ]]; then
        check_remove_prerequisites
    else
        ensure_dependencies_step1
        check_required_commands
        check_systemd
    fi

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

    if [[ "${MODE}" == "update" ]]; then
        check_python
        update_package_only_mode
        return 0
    fi

    check_python
    resolve_service_identity
    resolve_node_name
    resolve_cardano_node_unit
    resolve_node_config_path
    resolve_network
    resolve_api_key

    echo
    echo -e "${BOLD}OpenBlockPerf Installer (${MODE})${NC}"
    printf "  %-14s %s\n" "Version:"      "${INSTALLER_VERSION}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf "  %-14s %s\n" "Install dir:"  "${INSTALL_DIR}"
    printf "  %-14s %s\n" "Python:"       "${PYTHON}"
    printf "  %-14s %s\n" "Package:"      "${PACKAGE_SPEC}"
    printf "  %-14s %s\n" "Service user:" "${SERVICE_USER}:${SERVICE_GROUP}"
    printf "  %-14s %s\n" "Node name:"    "${NODE_NAME}"
    printf "  %-14s %s\n" "Node unit:"    "${NODE_UNIT_NAME}"
    printf "  %-14s %s\n" "Node config:"  "${NODE_CONFIG_PATH}"
    printf "  %-14s %s\n" "Network:"      "${NETWORK}"
    if [[ -n "${API_KEY_TO_INSTALL}" ]]; then
        printf "  %-14s %s\n" "API key:"    "set"
    else
        printf "  %-14s %s\n" "API key:"    "not set"
    fi
    printf "  %-14s %s\n" "Service file:" "${SERVICE_FILE}"
    printf "  %-14s %s\n" "Env file:"     "${ENV_FILE}"
    printf "  %-14s %s\n" "Command:"      "${WRAPPER_COMMAND}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo

    if [[ "${DRY_RUN}" == "true" ]]; then
        ok "Dry-run complete. No files changed."
        echo "Re-run without --dry-run to apply."
        return 0
    fi

    if [[ "${MODE}" == "reinstall" ]]; then
        confirm_or_die "Reinstall will replace ${INSTALL_DIR}. Continue?"
        stop_disable_service_if_present
    fi

    install_core
    maybe_start_service_after_install
    print_post_install_summary
}

main "$@"
