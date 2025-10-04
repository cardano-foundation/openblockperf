"""Client identifier management for Blockperf.

Handles unique client UUID generation and persistent storage.
"""

import os
import uuid
from pathlib import Path

from loguru import logger

from blockperf.errors import ConfigurationError


class ClientIdentifier:
    """Manages unique client identification using persistent UUIDs."""

    clientid_file = "clientid.uuid"

    def __init__(self, state_dir: Path | None = None):
        """Initialize client identifier manager.

        Args:
            state_dir: Directory to store client ID. If None, uses smart defaults
        """
        self.state_dir = state_dir or self._get_default_state_dir()
        self.clientid_path = self.state_dir / self.clientid_file
        self._clientid: str | None = None

    def _get_default_state_dir(self) -> Path:
        """Get the default state directory using XDG standards with fallbacks."""
        # Priority order for state directory:

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
            logger.debug(
                f"Running as root, using system directory: {system_dir}"
            )
            return system_dir

        # 4. Fallback to /tmp with username
        username = os.environ.get("USER", "unknown")
        fallback_dir = Path(f"/tmp/blockperf-{username}")
        logger.warning(f"Using temporary fallback directory: {fallback_dir}")
        return fallback_dir

    def get_or_create_clientid(self) -> str:
        """Get existing client ID or create a new one if none exists.

        Returns:
            UUID string identifying this client instance

        Raises:
            ConfigurationError: If unable to create state directory or write ID file
        """
        if self._clientid is not None:
            return self._clientid

        try:
            # Try to load existing ID
            if self.clientid_path.exists():
                self._clientid = self._load_existing_id()
                if self._clientid:
                    logger.info(f"Loaded existing client ID: {self._clientid}")
                    return self._clientid

            # Create new ID
            self._clientid = self._create_new_id()
            logger.info(f"Created new client ID: {self._clientid}")
            return self._clientid

        except Exception as e:
            raise ConfigurationError(
                f"Failed to get or create client ID: {e}"
            ) from e

    def _load_existing_id(self) -> str | None:
        """Load client ID from existing file.

        Returns:
            Client ID string or None if file is invalid
        """
        try:
            content = self.clientid_path.read_text().strip()

            # Validate it's a proper UUID
            uuid.UUID(content)

            return content

        except (ValueError, OSError) as e:
            logger.warning(f"Invalid or unreadable client ID file: {e}")
            return None

    def _create_new_id(self) -> str:
        """Create a new client ID and store it.

        Returns:
            New UUID string

        Raises:
            ConfigurationError: If unable to create directory or write file
        """
        # Generate new UUID
        new_id = str(uuid.uuid4())

        try:
            # Ensure state directory exists with proper permissions
            self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o755)

            # Write the ID file
            self.clientid_path.write_text(new_id)

            # Set readable permissions for the ID file
            self.clientid_path.chmod(0o644)

            return new_id

        except OSError as e:
            # Provide helpful error messages for common issues
            if e.errno == 13:  # Permission denied
                raise ConfigurationError(
                    f"Permission denied creating client ID at {self.clientid_path}. "
                    f"Try running as root or using a different state directory."
                ) from e
            else:
                raise ConfigurationError(
                    f"Failed to create client ID file at {self.clientid_path}: {e}"
                ) from e

    @property
    def clientid(self) -> str:
        """Get the current client ID, creating one if needed."""
        return self.get_or_create_clientid()


# Global instance for easy access
_clientidentifier: ClientIdentifier | None = None


def get_clientid(state_dir: Path | None = None) -> str:
    """Get the client ID for this instance.

    Args:
        state_dir: Custom state directory (optional)

    Returns:
        UUID string identifying this client instance
    """
    global _clientidentifier

    if _clientidentifier is None:
        _clientidentifier = ClientIdentifier(state_dir)

    return _clientidentifier.clientid


def reset_clientidentifier() -> None:
    """Reset the global client identifier (mainly for testing)."""
    global _clientidentifier
    _clientidentifier = None
