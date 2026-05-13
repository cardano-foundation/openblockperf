import asyncio
import contextlib
import os
import signal
import sys
import traceback
from typing import Annotated

import typer
from rich.console import Console

from openblockperf.app import Blockperf
from openblockperf.errors import ConfigurationError
from openblockperf.utils import async_command

from ._utils import _settings

run_app = typer.Typer(
    name="run",
    help="Run the blockperf client",
    invoke_without_command=True,
)
console = Console(file=sys.stdout, force_terminal=True)


@async_command
async def run_cmd(  # noqa: PLR0912
    network: Annotated[
        str | None,
        typer.Option(
            "--network",
            "-n",
            help="Cardano network to connect to (mainnet, preprod, preview). Defaults to OPENBLOCKPERF_NETWORK env var or 'mainnet'.",
        ),
    ] = None,
    api_url: Annotated[
        str | None,
        typer.Option(
            "--api-url",
            help="""Override API URL (for development/testing). Takes precedence over network-specific URLs.

            You will need to provide the full url, including port and path of the api.
            E.g.: http://localhost:8000/api/v0
        """,
        ),
    ] = None,
    node_unit_name: Annotated[
        str | None,
        typer.Option(
            "--node-unit-name",
            help="""Override unit name of the node this client tries to read logs from journald.

            This is the name of the systemd unit that your cardano-node service runs as.
            Defaults to cardano-node.
        """,
        ),
    ] = None,
) -> None:
    """The run command.

    Creates the AppSettings instance first and then the app itself.
    It then starts two tasks that compose the main application. One is the
    Blockperf app itself which runs Blockperf.start() and the other is a
    the shutdown task. Both are started and given to asyncio's wait function
    which will return when either one finishes. This results in the app.start()
    being run all the time until it either finsihes (never) or receives an
    exception. Or if the signal handler receivs one of the signals defined
    which would make it finish and thus close the program.

    """
    try:
        settings = _settings(network, api_url, node_unit_name)
        app = Blockperf(console, settings)

        console.print(f"[bold cyan]Network:[/] {settings.network.value}")
        console.print(f"[bold cyan]Node Name:[/] {settings.node_name}")
        console.print(f"[bold cyan]Node Unit Name:[/] {settings.node_unit_name}")
        console.print(f"[bold cyan]API URL:[/] {settings.full_api_url}")
        console.print(f"[bold cyan]API Key:[/] {settings.api_key.split('_')[0] if settings.api_key else None}")

        shutdown_event = asyncio.Event()  # Signal handler for Ctrl-SIGINT or SIGTERM os signals

        def signal_handler():
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        for sig in [signal.SIGINT, signal.SIGTERM]:
            loop.add_signal_handler(sig, signal_handler)

        # create app and shutdown_handler as asyncio tasks
        app_task = asyncio.create_task(app.start())
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        # Wait until either one finishes.
        done, pending = await asyncio.wait([app_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED)

        # Cancel any remaining tasks
        for task in pending:
            task.cancel()
            # To not receive multiple asyncio.CancelledError here suppress them
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Check if app_task completed with an exception
        if app_task in done and not app_task.cancelled():
            await app_task  # This will re-raise any exception if there was one

    except KeyboardInterrupt:
        console.print("\n[bold green]Shutdown initiated by user[/]")
        sys.exit(0)
    except asyncio.CancelledError:
        console.print("[bold yellow]Application was cancelled[/]")
        sys.exit(0)
    except ConfigurationError as e:
        console.print(f"[bold red]Configuration error:[/] {e!r}")
        sys.exit(1)
    except Exception as e:
        if hasattr(e, "exceptions"):
            console.print(f"[bold red]App failed with {len(e.exceptions)} error(s):[/]")  # fmt: off
            for exc in e.exceptions:
                if os.getenv("OPENBLOCKPERF_LOG_LEVEL", "INFO") == "DEBUG":
                    traceback.print_exc()
                console.print(f"[bold red]- {type(exc).__name__}: {exc!r}[/]")
        else:
            if os.getenv("OPENBLOCKPERF_LOG_LEVEL", "INFO") == "DEBUG":
                traceback.print_exc()
            console.print(f"[bold red]Application failed: {e!r}[/]")
        sys.exit(1)
    finally:
        await app.stop()
