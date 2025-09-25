"""
logreader

"""

import abc
import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

import rich

logger = logging.getLogger()


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
        print(f"created JournalCtlLogReader for {self.unit}")

    async def connect(self) -> None:
        """Connect by starting the journalctl subprocess."""
        try:
            print("connecting via journalctl subprocess")
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
            rich.print(cmd)
            self.process: asyncio.subprocess.Process = (
                await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
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

        self.process = None
        raise RuntimeError(f"Closed journalctl connection for: '{self.unit}'")

    async def read_messages(self) -> AsyncGenerator[dict[str, Any], None]:
        """Read messages (lines) from journalctl subprocess as an async generator."""
        if not self.process or not self.process.stdout:
            raise RuntimeError("Process or process stdout not available")
        try:
            while True:
                line = await self.process.stdout.readline()
                # rich.print(line)
                if not line:
                    print("EOF reached from journalctl subprocess")
                    break
                try:
                    message = json.loads(line)
                    yield message
                except json.JSONDecodeError as e:
                    print(f"Failed to parse journalctl output as JSON: {e}")
                    print(f"Raw line: {line}")
                except Exception as e:
                    print(f"Error processing journalctl line: {e}")
        except Exception as e:
            print(f"Error reading from journalctl subprocess: {e}")


def create_log_reader(reader_type: str, unit: str | None):
    """Creates a log reader of the given type."""
    unit = unit or "cardano-tracer"
    if reader_type == "journalctl":
        return JournalCtlLogReader(unit=unit)
    else:
        raise ValueError(
            "Unsupported log source type. Use 'file', 'journald', or 'journalctl'."
        )
