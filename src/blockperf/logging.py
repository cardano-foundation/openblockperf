"""
Logging

* There is only one logger!
* The add function of the logger adds "sings". Sinks manage the log messages.
* A sink can take many forms: A function, a string path, a file object, etc.)
* The add functions returns the id of the sink for later access

"""

import json
import sys

from loguru import logger

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
    format="{time} | {message} | {extra}",
)

# logger.add(
#    sys.stderr,
#    format="{time} {level} {message}",
#    level="TRACE",
# )

logger.debug("Logger loaded")
