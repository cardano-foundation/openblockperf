class BlockperfError(Exception):
    """Base exception for all Blockperf errors."""
    pass


class EventError(BlockperfError):
    """Raised when event processing fails."""
    pass


class ConfigurationError(BlockperfError):
    """Raised when configuration is invalid."""
    pass


class NetworkError(BlockperfError):
    """Raised when network operations fail."""
    pass


class LogReaderError(BlockperfError):
    """Raised when log reading fails."""
    pass


class TaskError(BlockperfError):
    """Raised when a background task fails critically."""
    pass
