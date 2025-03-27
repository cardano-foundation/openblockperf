#!/usr/bin/env python
"""
A dummy script that prints log messags from a log file to stdout such that
i can use it to print to journald and at the same time have my client
connect to that journald stream and ingest its logs.

start the log streaming with

python -u servelogs.py | systemd-cat -t 'cardano-logs'

The -u tells python to not buffer stdout such that all messages printed
to stdout will be immediatly sent to stdout and thus show up in journald much
quicker. The receiving end is then tto use journalctl to read from
that service like so:

journalctl -f -t cardano-logs -o json | jq -r .MESSAGE

The -o flag tells journalctl to print out as json. But that will add
some xtra boilerplate to the json. Thats why that is filtered using
the pipe to jq.

"""

import json
import logging
import pathlib
import random
import sys
import time
from itertools import cycle

from systemd import journal

rootdir = pathlib.Path(__file__).parent


FILE_PATH = rootdir.as_posix() + "/logeventexamples/logs.json"

logger = logging.getLogger("custom_logger_name")
logger.setLevel(logging.DEBUG)
logger.addHandler(journal.JournalHandler(SYSLOG_IDENTIFIER="custom_unit_name"))


def read_lines(filename):
    with open(filename, "r") as file:
        return file.readlines()


def read_file_forever(filename):
    """Reads a file line by line with a random delay between each line, looping indefinitely."""
    lines = read_lines(filename)
    while True:
        try:
            print("hop")
            l = json.loads(random.choice(lines).strip())
            logger.info("", extra={"MESSAGE_JSON": json.dumps(l)})
            # sys.stdout.flush()  # Ensure immediate output
            time.sleep(random.uniform(0.1, 3))  # Random delay between 1-5 sec
        except FileNotFoundError:
            print(f"Error: File '{filename}' not found.")
            time.sleep(5)  # Wait before retrying


if __name__ == "__main__":
    read_file_forever(FILE_PATH)
