import sys
from typing import Annotated

import rich
import typer
from rich.console import Console

from openblockperf.apiclient import BlockperfApiClient
from openblockperf.apiclient.models import IpRegistrationResponseStatus
from openblockperf.utils import async_command

from ._utils import SharedOptions, _settings

console = Console(file=sys.stdout, force_terminal=True)


@async_command
async def register_ip_cmd(
    ctx: typer.Context,
    force_renewal: Annotated[
        bool,
        typer.Option(
            "--force-renewal",
            help="Reregisters the ip address and returns a new ApiKey. Use this command from a client where you know it has send data prior but the ApiKey is lost. Invalidates the old ApiKey and creates a new one.",
        ),
    ] = False,
    update_ip: Annotated[
        bool,
        typer.Option(
            "--update-ip",
            help="Updates the ip address that is registered with the ApiKey. Use this command from a new client with an existing ApiKey to have the new clients ip be registered with that ApiKey.",
        ),
    ] = False,
) -> None:
    """Register for an ApiKey using your ip address.

    If you dont have a Calidus Key You can register using your ip. Run this command
    from the host where you want to share data. The source ip will be stored
    and the ApiKey will only every be valid from that ip address.
    """
    shared: SharedOptions = ctx.obj
    app_settings = _settings(
        network=shared.network,
        api_url=shared.api_url,
        config_file=shared.config,
    )
    if force_renewal and update_ip:
        console.print("[yellow]You cant provide --force-renewal and --update together! [/]")
        sys.exit(0)

    api = BlockperfApiClient(app_settings, service_mode=False)
    try:
        selected = await api.prepare()
        console.print(f"[bold cyan]API URL:[/] {selected}")
        response = await api.clientip_registration(force_renewal, update_ip)
    finally:
        await api.close()
    if response is None:
        console.print("[bold red]No registration response from API[/]")
        sys.exit(1)
    if response.apikey:
        # Machine-readable line for the installer; keep the human line for operators.
        print(f"API_KEY={response.apikey}", flush=True)
        rich.print(f"ApiKey: {response.apikey}")
    if response.ipaddress:
        print(f"RELAY_IP={response.ipaddress}", flush=True)

    if response.status == IpRegistrationResponseStatus.REGISTERED:
        rich.print(
            "You have successfully registered. Please note the APIKey. It can never be retrieved again. Use --force-renewal to create a new one."
        )
    elif response.status == IpRegistrationResponseStatus.ALREADY_REGISTERED:
        rich.print("You are already registered with this ip address.")
    elif response.status == IpRegistrationResponseStatus.FORCE_RENEWAL:
        rich.print("You have successfully renewed your ApiPkey. Please note that ApiKey.")
    elif response.status == IpRegistrationResponseStatus.UPDATE_IP:
        rich.print(f"You have successfully updated the ip address of your ApiPkey to '{response.ipaddress}'")
    else:
        rich.print(f"Unknown Status in response: {response}")
