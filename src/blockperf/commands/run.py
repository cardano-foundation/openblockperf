import asyncio

import typer
from rich.console import Console

from blockperf.nodelogs.logreader import create_log_reader
from blockperf.services.eventprocessor import EventProcessor

console = Console()

run_app = typer.Typer(
    name="run",
    help="Run the blockperf client",
    invoke_without_command=True,
)


@run_app.callback()
def run_app_callback():
    """Runs the blockperf client.

    * Creates the logprocessor seriver
    * starts it
    """
    try:
        from blockperf.core.async_utils import run_async

        #
        run_async(_run_app_callback())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Monitoring stopped.[/]")


async def _run_app_callback():
    """Maybe pass in a LogReader created in the callback above?"""
    log_reader = create_log_reader("journald", "cardano-logs")
    event_processor = EventProcessor(log_reader=log_reader)
    event_processor_task = asyncio.create_task(event_processor.start())
    try:
        await event_processor_task
    except asyncio.CancelledError:
        await event_processor.stop()
