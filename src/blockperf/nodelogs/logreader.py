"""
logreader


Read cardano-node log events from multiple sources.

The cardano-node can be configured to write its log events to either a logfile
or to the journald system over stdout. This logreader module implements the
ability to read log events from both. It provides a generic NodeLogReader
abstraction that will have the two concrete implementtations for the file
and the journald based source.


"""

import abc
import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator
from pprint import pprint
from typing import Any

# Move to actuall Reader for less hard depenency
from systemd import journal

logger = logging.getLogger()


class NodeLogReader(abc.ABC):
    """
    Abstract Base Class for log readers.
    """

    @abc.abstractmethod
    async def connect(self) -> None:
        """Connect to the log source."""
        pass

    @abc.abstractmethod
    async def read_events(self) -> AsyncGenerator[dict[str, Any], None]:
        """Read events from the log source as an async generator."""
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        """Close the connection to the log source."""
        pass

    async def __aenter__(self):
        print("__aenter__")
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("__aexit__")
        await self.close()


class FileLogReader(NodeLogReader):
    """
    Reads logs from a specified file.
    """

    def __init__(self, file_path):
        self.file_path = file_path

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Log file {file_path} does not exist.")

    def read_logs(self):
        with open(self.file_path, "r") as file:
            for line in file:
                yield line.strip()


class JournaldLogReader(NodeLogReader):
    """
    Reads logs from the systemd journal.
    """

    def __init__(self, syslog_identifier: str, cursor: str | None = None):
        """
        Initialize the journald source adapter.

        Args:
            unit_name: The systemd unit name to read logs from
            cursor: Optional cursor to start reading from a specific position
        """
        self.syslog_identifier = syslog_identifier
        self.cursor = cursor
        self._reader = None
        print("created JournaldLogReader %s", self)

    async def connect(self) -> None:
        """Connect to journald."""
        try:
            print("connecting to JournaldLogReader")
            # import pudb

            # pu.db
            # Create journal reader
            self._reader = journal.Reader()
            if self.syslog_identifier:
                self._reader.add_match(SYSLOG_IDENTIFIER=self.syslog_identifier)
                print(f"Add match for {self.syslog_identifier=}")
            # If cursor provided, seek to that position
            if self.cursor:
                self._reader.seek_cursor(self.cursor)
            else:
                # Otherwise start from the end
                self._reader.seek_tail()
                # Back up a bit to get a couple of entries for context
                # self._reader.get_previous(15)

            logger.info("connected to journald")

        except ImportError as e:
            raise ImportError(
                "systemd-python package is required for journald support"
            ) from e

    async def read_events(self) -> AsyncGenerator[dict[str, Any], None]:
        """Read events from journald as an async generator."""
        print("Reading events")
        if not self._reader:
            raise RuntimeError(
                "Not connected to journald. Call connect() first."
            )
        import pudb

        while True:
            # pu.db
            # Process available entries
            entry = self._reader.get_next()

            if entry:
                # print(entry)
                try:
                    # Extract the JSON message from the journal entry
                    # Assuming the log entry is a JSON string in the MESSAGE field
                    message = entry.get("MESSAGE_JSON")
                    # print(message)
                    if not message:
                        continue

                    # Parse the JSON message
                    if isinstance(message, bytes):
                        message = message.decode("utf-8")

                    # pu.db
                    event_data = json.loads(message)

                    # pprint(event_data)

                    # Save cursor for future resumption
                    self.cursor = entry.get("__CURSOR")

                    yield event_data

                except json.JSONDecodeError:
                    logger.warning(f"Received non-JSON log entry: {message}")

                except Exception as e:
                    logger.error(f"Error processing journal entry: {str(e)}")

            else:
                # No new entries, wait a bit before checking again
                await asyncio.sleep(0.1)

    async def close(self) -> None:
        """Close the connection to journald."""
        if self._reader:
            self._reader.close()
            self._reader = None
            logger.info(
                f"Closed journald connection for unit: {self.unit_name}"
            )


def create_log_reader(source_type, source):
    if source_type == "file":
        return FileLogReader(source)
    elif source_type == "journald":
        return JournaldLogReader(syslog_identifier="custom_unit_name")
    else:
        raise ValueError(
            "Unsupported log source type. Use 'file' or 'journald'."
        )
