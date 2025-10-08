import asyncio
import contextlib
import signal
import sys
from datetime import datetime

import typer
from loguru import logger
from rich.console import Console

from blockperf.apiclient import BlockperfApiClient
from blockperf.app import Blockperf
from blockperf.config import settings
from blockperf.errors import BlockperfError, ConfigurationError

run_app = typer.Typer(
    name="run",
    help="Run the blockperf client",
    invoke_without_command=True,
)
console = Console(file=sys.stdout, force_terminal=True)


@run_app.callback()
def run_app_callback():
    """Runs the blockperf client."""
    try:
        app = Blockperf(console)
        asyncio.run(_run_blockperf_app(app))
    except KeyboardInterrupt:
        console.print("\n[bold green]Shutdown initiated by user[/]")
        sys.exit(0)
    except ConfigurationError as e:
        console.print(f"[bold red]Configuration error:[/] {e}")
        sys.exit(1)
    except BlockperfError as e:
        console.print(f"[bold red]Application error:[/] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/] {e}")
        logger.exception("Unexpected error in run_app_callback")
        sys.exit(1)


async def _run_blockperf_app(app: Blockperf):
    """Asyncronously run the Blockperf app."""

    # Set up signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler():
        console.print("Received shutdown signal")
        shutdown_event.set()

    # Register signal handlers
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in [signal.SIGINT, signal.SIGTERM]:
            loop.add_signal_handler(sig, signal_handler)

    try:
        # Start the app with shutdown coordination
        app_task = asyncio.create_task(app.start())
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        # Wait for either app completion or shutdown signal
        done, pending = await asyncio.wait(
            [app_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel any remaining tasks
        for task in pending:
            task.cancel()
            # instead of try/catch pass
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Check if app_task completed with an exception
        if app_task in done and not app_task.cancelled():
            await app_task  # This will re-raise any exception if there was one

    except asyncio.CancelledError:
        console.print("Application was cancelled")
    except Exception:
        logger.exception("Error in _run_blockperf_app")
        raise
    finally:
        # Ensure clean shutdown
        await app.stop()
