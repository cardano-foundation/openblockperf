#!/usr/bin/env python

import pathlib
import random
import sys
import time
from itertools import cycle

rootdir = pathlib.Path(__file__).parent


FILE_PATH = rootdir.as_posix() + "/logeventexamples/logs.json"


def read_lines(filename):
    with open(filename, "r") as file:
        return file.readlines()


def read_file_forever(filename):
    """Reads a file line by line with a random delay between each line, looping indefinitely."""
    lines = read_lines(filename)
    while True:
        try:
            print(random.choice(lines).strip())
            sys.stdout.flush()  # Ensure immediate output
            time.sleep(random.randint(1, 5))  # Random delay between 1-5 sec
        except FileNotFoundError:
            print(f"Error: File '{filename}' not found.")
            time.sleep(5)  # Wait before retrying


if __name__ == "__main__":
    read_file_forever(FILE_PATH)
