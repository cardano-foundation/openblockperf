import asyncio
import os
import sys
import traceback
from typing import Annotated

import rich
import typer
from rich.console import Console

from openblockperf.apiclient import BlockperfApiClient
from openblockperf.apiclient.models import IpRegistrationResponseStatus
from openblockperf.errors import ConfigurationError
from openblockperf.logging import logger
from openblockperf.utils import async_command

from ._utils import _settings

console = Console(file=sys.stdout, force_terminal=True)


@async_command
async def register_ip_cmd(  # noqa: PLR0912, PLR0913, PLR0915
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
    force_renewal: Annotated[
        bool,
        typer.Option(
            "--force-renewal",
            help="Reregisters the IP address and returns a new ApiKey. Use this command from a client where you know it has send data prior but the ApiKey is lost. Invalidates the old ApiKey and creates a new one.",
        ),
    ] = False,
    update_ip: Annotated[
        bool,
        typer.Option(
            "--update-ip",
            help="Updates the IP Address that is registered with the ApiKey. Use this command from a new client with an existing ApiKey to have the new clients ip be registered with that ApiKey.",
        ),
    ] = False,
) -> None:
    """The register command."""

    try:
        app_settings = _settings(network=network)
        api = BlockperfApiClient(app_settings)

        if force_renewal and update_ip:
            console.print("[yellow]You cant provide --force-renewal and --update together! [/]")
            sys.exit(0)

        response = await api.clientip_registration(force_renewal, update_ip)
        if response.apikey:
            rich.print(f"ApiKey: {response.apikey}")

        if response.status == IpRegistrationResponseStatus.REGISTERED:
            rich.print(
                "You have successfully registered. Please note the APIKey. It can never be retrieved again. Use --force-renewal to create a new one."
            )
        elif response.status == IpRegistrationResponseStatus.ALREADY_REGISTERED:
            rich.print("You are already registered with this IP Address.")
        elif response.status == IpRegistrationResponseStatus.FORCE_RENEWAL:
            rich.print("You have successfully renewed your ApiPkey. Please note that ApiKey.")
        elif response.status == IpRegistrationResponseStatus.UPDATE_IP:
            rich.print(f"You have successfully update the ip address of your ApiPkey to '{response.ipaddress}'")
        else:
            rich.print(f"Unknown Status in response: {response}")

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
        logger.exception(e)
        if hasattr(e, "exceptions"):
            console.print(f"[bold red]App failed with {len(e.exceptions)} error(s):[/]")  # fmt: off
            for exc in e.exceptions:
                console.print(f"[bold red]- {type(exc).__name__}: {exc}[/]")
        else:
            if os.getenv("OPENBLOCKPERF_LOG_LEVEL", "INFO") == "DEBUG":
                traceback.print_exc()
            console.print(f"[bold red]Application failed: {e}[/]")
        sys.exit(1)
