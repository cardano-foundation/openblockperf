import asyncio
import contextlib
import signal
import sys
from typing import Annotated

import typer
from rich.console import Console

from openblockperf.apiclient.base import set_stop_event
from openblockperf.app import Blockperf
from openblockperf.utils import async_command

from ._utils import SharedOptions, _settings

console = Console(file=sys.stdout, force_terminal=True)


@async_command
async def run_cmd(
    ctx: typer.Context,
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

    shared: SharedOptions = ctx.obj
    settings = _settings(
        network=shared.network,
        api_url=shared.api_url,
        node_unit_name=node_unit_name,
        config_file=shared.config,
    )
    app = Blockperf(console, settings)

    console.print(f"[bold cyan]Network:[/] {settings.network.value}")
    console.print(f"[bold cyan]Node Name:[/] {settings.node_name}")
    console.print(f"[bold cyan]Node Unit Name:[/] {settings.node_unit_name}")
    console.print(f"[bold cyan]API URL:[/] {settings.full_api_url}")
    console.print(f"[bold cyan]API Key:[/] {settings.api_key.split('_')[0] if settings.api_key else None}")

    shutdown_event = asyncio.Event()
    set_stop_event(shutdown_event)

    loop = asyncio.get_running_loop()
    for sig in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(sig, shutdown_event.set)

    try:
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
    finally:
        await app.stop()
