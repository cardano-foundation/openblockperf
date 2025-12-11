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
from blockperf.config import Network, settings
from blockperf.errors import (
    ApiConnectionError,
    BlockperfError,
    ConfigurationError,
)
from blockperf.logging import logger
from blockperf.utils import async_command

console = Console(file=sys.stdout, force_terminal=True)


@async_command
async def register_cmd(
    pool_id: str = typer.Option(
        None,
        "--pool-id",
        "-p",
        help="Pool id (bech32) to register with",
    ),
    calidus_key_id: str = typer.Option(
        None,
        "--calidus-key-id",
        help="Calidus Key to use.",
    ),
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
    """Implements the register command."""
    try:
        app_settings = settings(network=network, api_url_override=api_url)
        api = BlockperfApiClient(app_settings)

        # Ask the server for a registration challenge for that pool_id
        response = await api.register(pool_id=pool_id)
        rich.print(response)

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
        # await app.stop()
        pass
