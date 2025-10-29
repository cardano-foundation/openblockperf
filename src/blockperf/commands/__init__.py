"""Base commands implementation for BlockPerf CLI."""

import asyncio
import platform
import sys

from rich.console import Console

from blockperf import __version__

from .run import run_cmd

__all__ = ["run_cmd", "version_cmd"]

console = Console()


def version_cmd(verbose: bool = False) -> None:
    """Display the version of BlockPerf.

    Args:
        verbose: Display more detailed version information
    """
    console.print(f"BlockPerf version: [bold green]{__version__}[/]")

    if verbose:
        console.print("\n[bold]Environment:[/]")

        console.print(f"Python version: [cyan]{sys.version}[/]")
        console.print(f"Platform: [cyan]{platform.platform()}[/]")
