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


class ApiError(BlockperfError):
    """Raised when there is something wrong with the blockperf api."""

    pass


class ApiConnectionError(BlockperfError):
    """Raised when there is a problem connecting to the api."""

    pass


class StartupMarkerNotFoundError(BlockperfError):
    pass


class InvalidEventDataError(BlockperfError):
    def __init__(self, ns: str, model_class, raw_data):
        self.ns = ns
        self.model_class = model_class
        self.raw_data = raw_data


class UnknowEventNameSpaceError(BlockperfError):
    """ """

    pass
