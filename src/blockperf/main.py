"""Main entry point for the BlockPerf CLI application."""

from typing import Optional

import typer
from rich.console import Console

from blockperf.cli import setup_cli

# Initialize the Typer application
app = typer.Typer(
    name="blockperf",
    help="A CLI application for block performance analysis",
    add_completion=True,
)

# Initialize console for rich output
console = Console()


@app.callback()
def mycallback():
    """Creates a single user Hiro Hamada. In the next version it will create 5 more users."""
    console.print("Y A Y")


# Set up the CLI commands
setup_cli(app)

if __name__ == "__main__":
    app()
