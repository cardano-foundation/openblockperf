import asyncio
import contextlib
import signal
import sys

import typer
from pydantic import ValidationError
from rich.console import Console

from openblockperf.app import Blockperf
from openblockperf.config import AppSettings, Network
from openblockperf.errors import ConfigurationError
from openblockperf.logging import logger
from openblockperf.utils import async_command

run_app = typer.Typer(
    name="run",
    help="Run the blockperf client",
    invoke_without_command=True,
)
console = Console(file=sys.stdout, force_terminal=True)


@async_command
async def run_cmd(
    network: str = typer.Option(
        None,
        "--network",
        "-n",
        help="Cardano network to connect to (mainnet, preprod, preview). Defaults to OPENBLOCKPERF_NETWORK env var or 'mainnet'.",
    ),
    api_url: str = typer.Option(
        None,
        "--api-url",
        help="""Override API URL (for development/testing). Takes precedence over network-specific URLs.

        You will need to provide the full url, including port and path of the api.
        E.g.: http://localhost:8000/api/v0
        """,
    ),
) -> None:
    """Implements the run command."""
    try:
        overrides = {}
        if network:
            if not isinstance(network, str):
                sys.exit(f"{network=} is not a string")
            try:
                network = Network(network.lower())
            except ValueError as e:
                valid_networks = [n.value for n in Network]
                sys.exit(f"Invalid network '{network}'. Must be one of: {', '.join(valid_networks)}")
            overrides["network"] = network
        if api_url:
            overrides["api_url"] = api_url
        settings = AppSettings(**overrides)

        # Print important settings
        console.print(f"[bold cyan]Network:[/] {settings.network.value}")
        console.print(f"[bold cyan]Hostname:[/] {settings.hostname}")
        console.print(f"[bold cyan]Node Unit:[/] {settings.node_unit_name}")
        console.print(f"[bold cyan]API URL:[/] {settings.full_api_url}")
        console.print(f"[bold cyan]API Key:[/] {settings.api_key.split('_')[0] if settings.api_key else None}")
    except ValidationError as e:
        console.print("[bold red]Configuration error\n[/]", str(e))
        sys.exit(1)

    try:
        app = Blockperf(console, settings)
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
        done, pending = await asyncio.wait([app_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED)

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
