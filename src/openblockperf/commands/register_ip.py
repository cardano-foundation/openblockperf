import sys
from typing import Annotated

import rich
import typer
from rich.console import Console

from openblockperf.apiclient import BlockperfApiClient
from openblockperf.apiclient.models import IpRegistrationResponseStatus
from openblockperf.utils import async_command

from ._utils import _settings

console = Console(file=sys.stdout, force_terminal=True)


@async_command
async def register_ip_cmd(
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
