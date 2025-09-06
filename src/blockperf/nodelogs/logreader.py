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
import subprocess
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

            # Position at the very end of the journal for this service
            self.reader.seek_tail()
            # Skip any existing entries by moving to the actual end
            while self.reader.get_previous():
                pass  # This moves us to the very beginning

            # Now go to the actual end by consuming all entries
            while self.reader.get_next():
                pass  # Now we're truly at the end

            print("connected to journald, positioned at end of stream")
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
        if entries:
            print(f"Found {len(entries)} new entries")
        return entries

    async def read_events(self) -> AsyncGenerator[dict[str, Any], None]:
        """Read events from journald as an async generator."""
        assert self.reader, "Not connected to journald. Call connect() first."
        while True:
            try:
                # Check for new entries first (without waiting)
                entries = self.get_new_entries()

                if entries:
                    for entry in entries:
                        print(f"found new entry {list(entry.keys())[:5]}...")
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
                            print(
                                f"Received non-JSON log entry: {message[:100]}..."
                            )
                        except Exception as e:
                            print(f"Error processing journal entry: {str(e)}")
                else:
                    # No entries available, wait for new ones
                    await self._wait_for_new_entries()

            except Exception as e:
                print(f"ERROR in read_events: {e}")
                await asyncio.sleep(0.1)

    async def _wait_for_new_entries(self) -> None:
        """Wait for new journal entries to become available."""
        try:
            result = self.reader.wait(timeout=1.0)
            if result == journal.APPEND:
                # New entries are available - don't iterate here, just return
                print("New journal entries detected")
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


class JournalCtlLogReader(NodeLogReader):
    """
    Reads logs from journald using the journalctl CLI tool.
    This implementation uses subprocess to call 'journalctl -fu <service>'.
    """

    def __init__(self, syslog_identifier: str | None):
        """
        Initialize the journalctl-based log reader.

        Args:
            syslog_identifier: The syslog identifier of the service to read logs from.
        """
        self.syslog_identifier = syslog_identifier or "cardano-tracer"
        self.process = None
        print(f"created JournalCtlLogReader for {self.syslog_identifier}")

    async def connect(self) -> None:
        """Connect by starting the journalctl subprocess."""
        try:
            print("connecting via journalctl subprocess")
            # Build the journalctl command: journalctl -f -u <service> -o json
            # and create a Process instance
            cmd = [
                "journalctl",
                "-f",  # Follow (like tail -f)
                "--identifier",
                self.syslog_identifier,  # Filter by syslog identifier
                "-o",
                "json",  # Output in JSON format
                "--no-pager",  # Don't use pager
                "--since",
                "now",  # Only show entries from now on
            ]
            self.process: asyncio.subprocess.Process = (
                await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            )

            print("connected via journalctl subprocess")

        except Exception as e:
            raise RuntimeError(
                f"Failed to start journalctl subprocess: {e}"
            ) from e

    async def close(self) -> None:
        """Close the journalctl subprocess."""
        if not self.process:
            return

        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=5.0)
        except TimeoutError:
            print("journalctl process didn't terminate, now killing it!")
            self.process.kill()
            await self.process.wait()

        self.process = None
        print(
            f"Closed journalctl connection for identifier: {self.syslog_identifier}"
        )

    async def read_events(self) -> AsyncGenerator[dict[str, Any], None]:
        """Read events from journalctl subprocess as an async generator."""
        assert self.process, "Not connected. Call connect() first."
        assert self.process.stdout, "Process stdout not available"

        print("Starting to read events from journalctl")

        try:
            while True:
                # Read a line from the subprocess stdout
                line = await self.process.stdout.readline()
                print(line)

                if not line:
                    # EOF reached, subprocess probably ended
                    print("EOF reached from journalctl subprocess")
                    break

                try:
                    # Decode the line and strip whitespace
                    line_str = line.decode("utf-8").strip()

                    if not line_str:
                        continue

                    # Parse as JSON
                    event_data = json.loads(line_str)

                    print(
                        f"Received event from journalctl: {event_data.get('MESSAGE', 'No MESSAGE')[:50]}..."
                    )

                    # Extract the actual log message and parse it as JSON if it's structured
                    message = event_data.get("MESSAGE")
                    if message:
                        try:
                            # Try to parse the message as JSON (for structured logs)
                            if isinstance(message, str) and (
                                message.startswith("{")
                                or message.startswith("[")
                            ):
                                structured_data = json.loads(message)
                                yield structured_data
                            else:
                                # If not JSON, yield the whole journalctl entry
                                yield event_data
                        except json.JSONDecodeError:
                            # Message is not JSON, yield the whole journalctl entry
                            yield event_data

                except json.JSONDecodeError as e:
                    print(f"Failed to parse journalctl output as JSON: {e}")
                    print(f"Raw line: {line_str}")
                except Exception as e:
                    print(f"Error processing journalctl line: {e}")

        except Exception as e:
            print(f"Error reading from journalctl subprocess: {e}")
        finally:
            # Check if process is still running
            if self.process and self.process.returncode is None:
                print(
                    "journalctl subprocess still running after read loop ended"
                )
            elif self.process:
                print(
                    f"journalctl subprocess ended with return code: {self.process.returncode}"
                )


def create_log_reader(reader_type: str, source: str | None):
    """Creates a log reader of the given type."""
    if reader_type == "file":
        return FileLogReader(source)
    elif reader_type == "journald":
        return JournaldLogReader(syslog_identifier=source or "cardano-tracer")
    elif reader_type == "journalctl":
        return JournalCtlLogReader(syslog_identifier=source or "cardano-tracer")
    else:
        raise ValueError(
            "Unsupported log source type. Use 'file', 'journald', or 'journalctl'."
        )
