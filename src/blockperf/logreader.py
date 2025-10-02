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


def create_log_reader(reader_type: str, unit: str | None):
    """Creates a log reader of the given type."""
    unit = unit or "cardano-tracer"
    if reader_type == "journalctl":
        return JournalCtlLogReader(unit=unit)
    else:
        raise ValueError(
            "Unsupported log source type. Use 'file', 'journald', or 'journalctl'."
        )
