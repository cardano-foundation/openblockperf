"""CLI setup and command registration for BlockPerf."""

from typing import Any

import typer
from rich.console import Console

from blockperf.commands import base

console = Console()


def setup_cli(app: typer.Typer) -> None:
    """Set up the CLI with all command groups and commands.

    Args:
        app: The Typer application instance
    """
    # Add base commands directly to the app
    app.command()(base.version)

    # Create the analyze command group
    analyze_app = typer.Typer(
        name="analyze", help="Performance analysis commands"
    )
    app.add_typer(analyze_app)

    # Add analyze commands
    analyze_app.command(name="blocks")(base.analyze_blocks)

    # Create the monitor command group
    monitor_app = typer.Typer(
        name="monitor", help="Real-time monitoring commands"
    )
    app.add_typer(monitor_app)

    # Add monitor commands
    monitor_app.command(name="blocks")(base.monitor_blocks)
