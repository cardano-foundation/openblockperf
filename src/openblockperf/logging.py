"""
Logging

* There is only one logger!
* The add function of the logger adds "sings". Sinks manage the log messages.
* A sink can take many forms: A function, a string path, a file object, etc.)
* The add functions returns the id of the sink for later access

"""

__all__ = ["logger", "setup_logging"]

import sys

from loguru import logger


def setup_logging(level: str = "INFO"):
    # Start fresh and remove defaults
    logger.remove()
    logger.add(
        sys.stdout,
        level=level,
        colorize=True,  # TTY-aware: loguru checks if stdout is a TTY
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green>|"
            "<level>{level: <6}</level>|"
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )
    # logger.add(
    #   sys.stderr,
    #   format="{time} {level} {message}",
    #   level="TRACE",
    # )

    logger.info("Logger loaded")
