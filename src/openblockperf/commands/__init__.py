"""Base commands implementation for BlockPerf CLI."""

import platform
import sys

import httpx
from rich.console import Console

from openblockperf import __version__
from openblockperf.utils import async_command

from .register import register_cmd
from .run import run_cmd

__all__ = ["run_cmd", "version_cmd", "register_cmd"]

console = Console()


@async_command
async def version_cmd() -> None:
    """Display the version of BlockPerf.

    Args:
        verbose: Display more detailed version information
    """
    response = httpx.get("https://pypi.org/pypi/openblockperf/json", timeout=3)
    latest = response.json()["info"]["version"]
    console.print(f"Latest: {latest}")
    console.print(f"BlockPerf version: [bold green]{__version__}[/]")
    if __version__ != latest:
        console.print(f"New Version available: [bold red]{latest}[/]")
    console.print(f"Python version: [cyan]{sys.version}[/]")
    console.print(f"Platform: [cyan]{platform.platform()}[/]")
