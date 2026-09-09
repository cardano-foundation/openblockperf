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
            help="Replaces all IP bindings on an existing ApiKey with the proven IPv4/IPv6 set. Requires api_key in config (or OPENBLOCKPERF_API_KEY). Do not combine with --force-renewal.",
        ),
    ] = False,
) -> None:
    """Register for an ApiKey bound to this relay's public IP(s).

    On dual-stack hosts the client proves IPv4 and IPv6 separately via
    ``/registration/ip/proof``, then submits both short-lived tokens to
    ``/registration/ip`` so one ApiKey is valid on either family. If a proof
    fails, registration falls back to legacy single-stack binding and warns.
    """
    shared: SharedOptions = ctx.obj
    app_settings = _settings(
        network=shared.network,
        api_url=shared.api_url,
        config_file=shared.config,
    )
    if force_renewal and update_ip:
        console.print("[yellow]You cant provide --force-renewal and --update-ip together![/]")
        sys.exit(1)

    if update_ip and not app_settings.api_key:
        console.print(
            "[bold red]--update-ip requires an existing api_key in the config file "
            "or OPENBLOCKPERF_API_KEY.[/]"
        )
        sys.exit(1)

    api = BlockperfApiClient(app_settings, service_mode=False)
    try:
        selected = await api.prepare()
        console.print(f"[bold cyan]API URL:[/] {selected}")
        console.print(f"[bold cyan]X-Hostname:[/] {app_settings.node_name}")
        response, proofs, used_legacy = await api.register_ip(
            force=force_renewal,
            update_ip=update_ip,
        )
    finally:
        await api.close()

    for family, label in (("v4", "IPv4"), ("v6", "IPv6")):
        if family not in proofs:
            console.print(f"[yellow]{label} proof unavailable[/]")
            continue
        proof = proofs[family]
        detected = f" (detected {proof.ip})" if proof.ip else ""
        console.print(f"[green]{label} proof accepted{detected}[/]")
        ip_value = proof.ip or "validated"
        print(f"RELAY_IP_{family.upper()}={ip_value}", flush=True)

    if used_legacy:
        console.print(
            "[yellow]Fell back to legacy single-stack registration. "
            "The other address family may get 401 until you re-run with "
            "working proofs (use --update-ip once you have an api_key).[/]"
        )
    elif len(proofs) == 1:
        console.print(
            "[yellow]Only one address family was proven. "
            "The other family may get 401 until you run --update-ip with both proofs.[/]"
        )

    if response is None:
        console.print("[bold red]No registration response from API[/]")
        sys.exit(1)
    if response.apikey:
        # Machine-readable line for the installer; keep the human line for operators.
        print(f"API_KEY={response.apikey}", flush=True)
        rich.print(f"ApiKey: {response.apikey}")
    if response.ipaddresses:
        print(f"RELAY_IPS={','.join(response.ipaddresses)}", flush=True)
        rich.print(f"Bound IPs: {', '.join(response.ipaddresses)}")
    if response.ipaddress:
        print(f"RELAY_IP={response.ipaddress}", flush=True)

    if response.status == IpRegistrationResponseStatus.REGISTERED:
        rich.print(
            "You have successfully registered. Please note the APIKey. It can never be retrieved again. Use --force-renewal to create a new one."
        )
    elif response.status == IpRegistrationResponseStatus.ALREADY_REGISTERED:
        rich.print("You are already registered with this ip address.")
    elif response.status == IpRegistrationResponseStatus.FORCE_RENEWAL:
        rich.print("You have successfully renewed your ApiKey. Please note that ApiKey.")
    elif response.status == IpRegistrationResponseStatus.UPDATE_IP:
        bound = (
            ", ".join(response.ipaddresses)
            if response.ipaddresses
            else (response.ipaddress or "updated set")
        )
        rich.print(f"You have successfully updated the IP binding(s) of your ApiKey to '{bound}'")
    else:
        rich.print(f"Unknown Status in response: {response}")
