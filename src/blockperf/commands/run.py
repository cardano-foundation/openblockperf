import asyncio
from datetime import datetime

import rich
import typer
from rich.console import Console

from blockperf.apiclient import BlockperfApiClient
from blockperf.app import Blockperf
from blockperf.async_utils import run_async
from blockperf.config import settings
from blockperf.logging import logger

console = Console()

run_app = typer.Typer(
    name="run",
    help="Run the blockperf client",
    invoke_without_command=True,
)


@run_app.callback()
def run_app_callback():
    """Runs the blockperf client.

    Creates a log reader first and then the event processor. The event
    processor uses the log reader to read log events and process them.
    The event processor is run inside an asyncio
    """
    try:
        app = Blockperf()
        run_async(_run_blockperf_app(app))
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Monitoring stopped.[/]")


async def _run_blockperf_app(app: Blockperf):
    """Asyncronously run the Blockperf app."""
    try:
        await app.start()
    except asyncio.CancelledError:
        rich.print("[bold red]Blockperf app got canceled![/]")
        await app.stop()
