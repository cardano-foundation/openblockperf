"""
logreader

"""

import abc
import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger

from blockperf.errors import StartupMarkerNotFoundError


class NodeLogReader(abc.ABC):
    """
    Abstract Base Class for log readers.  Provides the general interface
    that all LogReaders must implement.
    """

    @abc.abstractmethod
    async def connect(self) -> None:
        """Connect to the log source."""
        pass

    @abc.abstractmethod
    async def read_messages(self) -> AsyncGenerator[dict[str, Any], None]:
        """Read messages from the log source as an async generator."""
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        """Close the connection to the log source."""
        pass

    @abc.abstractmethod
    async def search_messages(
        self, search_string: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Search historical messages for a given string.

        Args:
            search_string: The string to search for in log messages

        Yields:
            Matching log messages as dictionaries
        """
        pass

    @abc.abstractmethod
    async def replay_from_startup(
        self, startup_marker: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Replay all log messages from the last service startup to present.

        This method should:
        1. Find the most recent occurrence of startup_marker
        2. Yield all log messages from that point until "now"
        3. Return when caught up to present time

        Args:
            startup_marker: String that marks service startup (e.g., "Started cardano-tracer")

        Yields:
            Historical log messages in chronological order (oldest first)
        """
        pass

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class JournalCtlLogReader(NodeLogReader):
    """Implementation of a log reader based on the journalctl cli tool.

    Starts a subprocess which runs the journalctl tool to receive the logs
    from journald. Upon creation the systemd unit to log must be provided.

    The read_messages() function is an async generator that will yield every
    single line from the logs forever.

    The replay_from_startup() function is also an async generator but
    it will only ever read messages from the past. It tries to find the
    last starting point of the node and then yield all messages until now.
    """

    def __init__(self, unit: str):
        """
        Initialize the journalctl based log reader.

        Args:
            unit: The syslog unit of the service to read logs from.
        """
        self.unit = unit
        self.process = None
        logger.debug(f"Created JournalCtlLogReader for {self.unit}")

    async def connect(self) -> None:
        """Connect by starting the journalctl subprocess."""
        try:
            # Build the journalctl command: journalctl -f -u <service> -o json
            # and create a Process instance
            cmd = [
                "journalctl",
                "-f",
                "--unit",
                self.unit,  # Filter by syslog unit
                "-o",
                "cat",  # Only show the message without any metadata
                "--no-pager",  # Don't use pager
                "--since",
                "now",  # Only show entries from now on
            ]
            logger.debug("Connecting via journalctl subprocess", cmd=cmd)

            self.process: asyncio.subprocess.Process = (
                await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    limit=10000000,  # 10MB Buffer size
                )
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to start journalctl subprocess: {e}"
            ) from e

    async def close(self) -> None:
        """Close the journalctl subprocess."""
        if not self.process:
            return

        try:
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), timeout=1.0)
        except TimeoutError:
            print("journalctl didn't terminate, now killing it!")
            self.process.kill()  # sends SIGKILL
            await self.process.wait()  # ensure OS has time to kill

        # unset process
        self.process = None

    async def read_messages(self) -> AsyncGenerator[dict[str, Any], None]:
        """Read messages (lines) from journalctl subprocess as an async generator."""
        if not self.process or not self.process.stdout:
            raise RuntimeError("Process or process stdout not available")

        while True:
            line = await self.process.stdout.readline()

            if not line:
                print("EOF reached from journalctl subprocess")
                break
            try:
                # Using -o cat above, i assume there will be a clean json
                # coming out of the node logs
                message = json.loads(line)
                yield message
            except json.JSONDecodeError as e:
                print(f"Failed to parse journalctl output as JSON: {e}")
                print(f"Raw line: {line}")
            except Exception as e:
                print(f"Error processing journalctl line: {e}")

    async def search_messages(
        self, search_string: str, since_hours: int
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Search historical messages using journalctl for a given string.

        Args:
            search_string: The string to search for in log messages
            since: The journalctl since argument, defaults to "60 minutes ago"

        Yields:
            Matching log messages as dictionaries as they are found
        """
        process = None

        try:
            # Build journalctl search command
            cmd = [
                "journalctl",
                "--unit",
                self.unit,  # Filter by service unit
                "-o",
                "cat",  # Output format: only message content
                "--no-pager",  # Don't use pager
                "--reverse",  # Show newest first
                "--since" if since_hours else "",
                f"{since_hours} hours ago" if since_hours else "",
                "--grep",
                search_string,  # Search for the string
            ]

            logger.debug(
                f"Searching peer {search_string} since {since_hours} hours ago"
            )

            # Execute the search command as a streaming process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10000000,  # 10MB Buffer size
            )

            # Stream results as they come in
            while True:
                line = await process.stdout.readline()

                if not line:
                    # Check if process has finished
                    if (
                        process.returncode is not None
                        or process.stdout.at_eof()
                    ):
                        break
                    continue

                line_str = line.decode("utf-8").strip()
                if not line_str:  # Skip empty lines
                    continue

                try:
                    # Try to parse as JSON (assuming cardano-tracer outputs JSON)
                    message = json.loads(line_str)
                    yield message
                except json.JSONDecodeError:
                    # If not JSON, treat as plain text message
                    yield {"message": line_str, "raw": True}
                except Exception as e:
                    logger.warning(f"Error parsing search result line: {e}")
                    continue

            # Wait for process to finish and check return code
            await process.wait()
            if process.returncode != 0:
                stderr_data = await process.stderr.read()
                error_msg = (
                    stderr_data.decode("utf-8")
                    if stderr_data
                    else "Unknown error"
                )
                logger.warning(
                    f"journalctl search finished with return code {process.returncode}: {error_msg}"
                )

        except Exception as e:
            logger.error(f"Error during log search: {e}")
        finally:
            # Clean up the process if it's still running
            if process and process.returncode is None:
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=1.0)
                except TimeoutError:
                    logger.warning(
                        "journalctl search process didn't terminate, killing it"
                    )
                    process.kill()
                    await process.wait()

    async def replay_from_startup(self) -> AsyncGenerator[dict[str, Any], None]:
        """Replay all log messages since the last start of the node.

        Does so in steps:

        * Searches for the "server startet" namespace event (see below) in journald
        * Extracts the timestamp from that log message
        * Uses that timestamp to now where to start replaying events until now
        *

        Yields:
            Historical log messages in chronological order (oldest first)
        """

        # There was another namespace with that same string "Reflection.TracerConfigInfo"
        # such that i needed to add the ns field part here as well
        startup_marker = '"ns":"Net.Server.Local.Started"'
        startup_timestamp = None
        process = None

        try:
            #######################################
            # Step 1: Find startup message of node
            search_cmd = [
                "journalctl",
                "--unit",
                self.unit,
                "-o",
                "json",  # Use JSON format to get the log messages timestamp
                "--no-pager",
                "--reverse",  # Newest first
                "-n",
                "1",  # Only get the most recent match
                "--grep",
                startup_marker,
            ]
            search_process = await asyncio.create_subprocess_exec(
                *search_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await search_process.communicate()
            if search_process.returncode != 0 or not stdout:
                logger.warning(
                    f"No startup marker '{startup_marker}' found in logs"
                )
                raise StartupMarkerNotFoundError()

            #######################################
            # Step 2: Extrat timestamp from startup message
            try:
                startup_line = stdout.decode("utf-8").strip()
                startup_entry = json.loads(startup_line)
                startup_timestamp = startup_entry.get("__REALTIME_TIMESTAMP")

                if not startup_timestamp:
                    logger.warning(
                        "Could not extract timestamp from startup entry"
                    )
                    return
                logger.info(f"Found startup at timestamp: {startup_timestamp}")
            except json.JSONDecodeError as e:
                logger.warning(f"Could not parse startup entry: {e}")
                return

            #######################################
            # Step 3: Replay all messages from startup timestamp to now
            # Convert microsecond timestamp to journalctl format
            startup_time_sec = int(startup_timestamp) // 1000000
            replay_cmd = [
                "journalctl",
                "--unit",
                self.unit,
                "-o",
                "cat",  # Message content only (like read_messages)
                "--no-pager",
                "--since",
                f"@{startup_time_sec}",  # Unix timestamp format
                "--until",
                "now",
            ]
            logger.info(f"Replaying logs from startup timestamp {startup_time_sec}")  # fmt: off
            # Execute replay command as streaming process
            process = await asyncio.create_subprocess_exec(
                *replay_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10000000,  # 10MB Buffer
            )

            message_count = 0
            while True:
                line = await process.stdout.readline()
                if not line:
                    # If process is finished, break the loop and return function
                    if (
                        process.returncode is not None
                        or process.stdout.at_eof()
                    ):
                        break
                    # Keep waiting by continuing the loop
                    continue

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue
                try:
                    # Parse message like read_messages does
                    message = json.loads(line_str)
                    message_count += 1
                    yield message
                except json.JSONDecodeError:
                    logger.debug(f"Malformed JSON in replay: {line_str[:100]}...")  # fmt: off
                    continue

            # Finally wait for the process to finish and close it or display
            # error if non zero exitr code appeared
            await process.wait()
            if process.returncode != 0:
                stderr_data = await process.stderr.read()
                error_msg = (
                    stderr_data.decode("utf-8")
                    if stderr_data
                    else "Unknown error"
                )
                logger.warning(f"Replay finished with return code {process.returncode}: {error_msg}")  # fmt: off
            else:
                logger.info(f"Replay completed successfully: {message_count} messages processed")  # fmt: off
        except Exception as e:
            logger.error(f"Error during log replay: {e.__class__.__name__}")
            raise
        finally:
            # Clean up process if still running
            if process and process.returncode is None:
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=1.0)
                except TimeoutError:
                    logger.warning("Replay process didn't terminate, killing it")  # fmt: off
                    process.kill()
                    await process.wait()


def create_log_reader(reader_type: str, unit: str | None) -> NodeLogReader:
    """Creates a log reader of the given type.

    Args:
        reader_type: The type of the reader, currently only journalctl is supported
        unit: The unit to follow the log stream of. Defaults to cardano-tracer

    Returns:
        An instance of a subclass of NodeLogReader.
    """
    unit = unit or "cardano-tracer"
    if reader_type == "journalctl":
        return JournalCtlLogReader(unit=unit)
    else:
        raise ValueError(
            "Unsupported log reader type. Only 'journalctl' is allowed currently."
        )
