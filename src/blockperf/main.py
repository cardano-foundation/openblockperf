"""Main entry point for the BlockPerf CLI application."""

from typing import Optional

from rich.console import Console

from blockperf.cli import blockperf_app

# Initialize console for rich output
console = Console()

# Set up the CLI commands


def run():
    blockperf_app()


if __name__ == "__main__":
    run()
