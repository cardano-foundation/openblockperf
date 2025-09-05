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
        with open(self.file_path) as file:
            for line in file:
                yield line.strip()


class JournaldLogReader(NodeLogReader):
    """
    Reads logs from a syslog service identified by its syslog identifier.
    This must be the value you specify in the service unit file with the
    `SyslogIdentifier` field. Assuming this is only ever going to be used
    in the cardano-tracer context the default syslog identigier is `cardano-tracer`.
    """

    def __init__(self, syslog_identifier: str | None):
        """
        Initialize the journald source adapter.

        Args:
            syslog_identifier: The syslog identifier of the service to read logs from.

        """
        self.syslog_identifier = syslog_identifier or "cardano-tracer"
        self.reader = None
        print(f"created JournaldLogReader for {self.syslog_identifier}", self)

    async def connect(self) -> None:
        """Connect to journald."""
        try:
            print("connecting to journald")
            self.reader = journal.Reader()  # Create journal reader
            self.reader.add_match(SYSLOG_IDENTIFIER=self.syslog_identifier)
            print(f"Add match for {self.syslog_identifier=}")

            # Position at end and consume any existing entries to start fresh
            self.reader.seek_tail()
            self.reader.get_previous()  # Position at the actual last entry

            # Consume any remaining entries to ensure we only get new ones
            while self.reader.get_next():
                pass

            print("connected to journald")
        except ImportError as e:
            raise ImportError(
                "systemd-python package is required for journald support"
            ) from e

    async def close(self) -> None:
        """Close the reader connection to journald if there is one."""
        if not self.reader:
            return
        self.reader.close()
        self.reader = None
        print(f"Closed journald connection for unit: {self.syslog_identifier}")

    def get_new_entries(self):
        """Get all new entries that have arrived since last check."""
        entries = []
        while True:
            entry = self.reader.get_next()
            if not entry:
                break
            entries.append(entry)
        print(f"Found {len(entries)} new entries")
        return entries

    async def read_events(self) -> AsyncGenerator[dict[str, Any], None]:
        """Read events from journald as an async generator."""
        assert self.reader, "Not connected to journald. Call connect() first."
        while True:
            try:
                # Wait for new entries to become available
                await self._wait_for_new_entries()

                # Get all new entries that arrived
                entries = self.get_new_entries()

                for entry in entries:
                    print(f"found new entry {list(entry.keys())[:5]}...")  # Show first 5 keys
                    try:
                        # Extract the JSON message from the journal entry
                        message = entry.get("MESSAGE")
                        if not message:
                            print("no message in entry")
                            continue

                        # Parse the JSON message
                        if isinstance(message, bytes):
                            message = message.decode("utf-8")

                        event_data = json.loads(message)

                        # Maybe store for future repickup of where we left off?
                        # self.cursor = entry.get("__CURSOR")

                        yield event_data

                    except json.JSONDecodeError:
                        print(f"Received non-JSON log entry: {message[:100]}...")
                    except Exception as e:
                        print(f"Error processing journal entry: {str(e)}")

            except Exception as e:
                print(f"ERROR in read_events: {e}")
                await asyncio.sleep(0.1)

    async def _wait_for_new_entries(self) -> None:
        """
        Wait for new journal entries to become available.
        This implements the polling mechanism similar to journalctl -f
        Uses systemd's built-in waiting mechanism
        """
        try:
            # Wait for journal changes with timeout in seconds
            result = self.reader.wait(timeout=1.0)
            if not result:
                # No result within timeout, just return
                return
            elif result == journal.APPEND:
                # New entries are available - don't iterate here, just return
                print("New journal entries detected")
                return
            elif result == journal.INVALIDATE:
                # Journal was rotated/invalidated, need to re-seek
                print("Journal invalidated, re-seeking...")
                self.reader.seek_tail()
                self.reader.get_previous()
                # Consume any existing entries
                while self.reader.get_next():
                    pass

        except Exception as e:
            print(f"Error waiting for journal entries: {e}")
            # Fall back to simple sleep
            await asyncio.sleep(0.5)


def create_log_reader(reader_type: str, source: str | None):
    """Creates a log reader of the given type."""
    if reader_type == "file":
        return FileLogReader(source)
    elif reader_type == "journald":
        return JournaldLogReader(syslog_identifier="cardano-tracer")
    else:
        raise ValueError(
            "Unsupported log source type. Use 'file' or 'journald'."
        )
