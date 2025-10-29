import asyncio
import contextlib
import signal
import sys
from datetime import datetime

import rich
import typer
from loguru import logger
from rich.console import Console

from blockperf.apiclient import BlockperfApiClient
from blockperf.app import Blockperf
from blockperf.config import settings
from blockperf.errors import (
    ApiConnectionError,
    BlockperfError,
    ConfigurationError,
)
from blockperf.logging import logger
from blockperf.utils import async_command

run_app = typer.Typer(
    name="run",
    help="Run the blockperf client",
    invoke_without_command=True,
)
console = Console(file=sys.stdout, force_terminal=True)


@async_command
async def run_cmd() -> None:
    """Implements the run command."""
    try:
        app = Blockperf(console)

        # Setup the signal handler for Ctrl-SIGINT or SIGTERM os signals
        shutdown_event = asyncio.Event()

        def signal_handler():
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        for sig in [signal.SIGINT, signal.SIGTERM]:
            loop.add_signal_handler(sig, signal_handler)

        # Start the app and the shutdown event handler as asyncio tasks
        app_task = asyncio.create_task(app.start())
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        # Wait until app_task or shutdown_task finishes. Either because
        # of a crash in the app (or it finished) or because of a Signal the
        # shutdown event received e.g.: Ctrl-c, SIGIINT, SIGTERM
        done, pending = await asyncio.wait(
            [app_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
        )

        # Before closing the app, make sure to cleanup work by waiting for
        # remaining tasks from the app.
        # Cancel any remaining tasks
        for task in pending:
            task.cancel()
            # instead of try/catch pass
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # Check if app_task completed with an exception
        if app_task in done and not app_task.cancelled():
            await app_task  # This will re-raise any exception if there was one

    except KeyboardInterrupt:
        console.print("\n[bold green]Shutdown initiated by user[/]")
        sys.exit(0)
    except asyncio.CancelledError:
        console.print("Application was cancelled")
        sys.exit(0)
    except ConfigurationError as e:
        console.print(f"[bold red]Configuration error:[/] {e}")
        sys.exit(1)
    except Exception as e:
        if hasattr(e, "exceptions"):
            console.print(f"[bold red]App failed with {len(e.exceptions)} error(s):[/]")  # fmt: off
            for exc in e.exceptions:
                console.print(f"[bold red]- {type(exc).__name__}: {exc}[/]")
        else:
            console.print(f"[bold red]Application failed: {e}[/]")
        sys.exit(1)
    finally:
        await app.stop()
