import asyncio

import typer
from rich.console import Console

from blockperf.core.async_utils import run_async
from blockperf.core.logreader import create_log_reader
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

    Creates a log reader first and then the event processor. The event
    processor uses the log reader to read log events and process them.
    The event processor is run inside an asyncio
    """
    try:
        log_reader = create_log_reader("journalctl", "cardano-tracer")
        event_processor = EventProcessor(log_reader=log_reader)
        run_async(_run_event_processor(event_processor))
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Monitoring stopped.[/]")


async def _run_event_processor(event_processor: EventProcessor):
    """Asyncronously run the given event processor."""
    try:
        event_processor_task = asyncio.create_task(event_processor.start())
        await event_processor_task
    except asyncio.CancelledError:
        await event_processor.stop()
