"""
logreader

"""

import abc
import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import rich
from loguru import logger


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

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class JournalCtlLogReader(NodeLogReader):
    """Concrete implementation of a log reader. Starts a subprocess which
    runs the journalctl tool to receive the messages. The read_messages()
    function is a generator that will yield every single line from the logs.
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


def create_log_reader(reader_type: str, unit: str | None):
    """Creates a log reader of the given type.
    Args:
        reader_type: The type of the reader, currently only journalctl is supported
        unit: The unit to follow the log stream of. Defaults to cardano-tracer

    Returns:
    """
    unit = unit or "cardano-tracer"
    if reader_type == "journalctl":
        return JournalCtlLogReader(unit=unit)
    else:
        raise ValueError(
            "Unsupported log reader type. Only 'journalctl' is allowed currently."
        )
