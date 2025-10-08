"""
Logging

* There is only one logger!
* The add function of the logger adds "sings". Sinks manage the log messages.
* A sink can take many forms: A function, a string path, a file object, etc.)
* The add functions returns the id of the sink for later access

"""

from loguru import logger


def setup_logging():
    # Start fresh and remove defaults
    logger.remove()

    # Log everything to a file, keep it for a week.abs
    # logger.add(
    #    "logs.json",
    #    serialize=True,
    #    rotation="50 MB",
    #    compression="zip",
    # )
    logger.add(
        "logs.txt",
        rotation="50 MB",
        compression="zip",
        level="TRACE",
        format="{time:YYYY-MM-DD}T{time:HH:mm:ss}.{time:SSS} | {message} | {extra}",
    )

    # logger.add(
    #    sys.stderr,
    #    format="{time} {level} {message}",
    #    level="TRACE",
    # )

    logger.debug("Logger loaded")
