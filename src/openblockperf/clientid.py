"""Client identifier management for Blockperf.

Handles unique client UUID generation and persistent storage.
"""

import os
from pathlib import Path

from openblockperf.errors import ConfigurationError
from openblockperf.logging import logger

# Filename where to client id is stored in
CLIENTID_FILE = "client_id.uuid"


def _get_state_dir() -> Path:
    """Get the state directory using XDG standards with fallbacks."""

    # 1. XDG_STATE_HOME (if set)
    if xdg_state_home := os.environ.get("XDG_STATE_HOME"):
        state_dir = Path(xdg_state_home) / "blockperf"
        logger.debug(f"Using XDG_STATE_HOME: {state_dir}")
        return state_dir

    # 2. ~/.local/state/blockperf (XDG default)
    if home := os.environ.get("HOME"):
        state_dir = Path(home) / ".local" / "state" / "blockperf"
        logger.debug(f"Using user state directory: {state_dir}")
        return state_dir

    # 3. /var/lib/blockperf (if it exists or we're root)
    system_dir = Path("/var/lib/blockperf")
    if system_dir.exists():
        logger.debug(f"Using existing system directory: {system_dir}")
        return system_dir
    elif os.getuid() == 0:  # Running as root
        logger.debug(f"Running as root, using system directory: {system_dir}")
        return system_dir

    # 4. Fallback to /tmp with username
    username = os.environ.get("USER", "unknown")
    fallback_dir = Path(f"/tmp/blockperf-{username}")
    logger.warning(f"Using temporary fallback directory: {fallback_dir}")
    return fallback_dir


def store_client_id(client_id: str):
    """Stores the client id on the system."""
    try:
        state_dir = _get_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
        client_id_path = state_dir / CLIENTID_FILE
        client_id_path.write_text(client_id)
        client_id_path.chmod(0o644)
        return

    except OSError as e:
        # Provide helpful error messages for common issues
        if e.errno == 13:  # noqa: PLR2004
            # Permission denied
            raise ConfigurationError(
                f"Permission denied creating client ID at {client_id_path}. "
                f"Try running as root or using a different state directory."
            ) from e
        else:
            raise ConfigurationError(f"Failed to create client ID file at {client_id_path}: {e}") from e


def get_client_id() -> str:
    """Get the client ID for this instance.

    Returns:
        UUID string identifying this client instance
    """
    state_dir = _get_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
    client_id_path = state_dir / CLIENTID_FILE
    if not client_id_path.exists():
        return "None"
    return client_id_path.read_text()
