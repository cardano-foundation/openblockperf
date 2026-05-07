import asyncio
import sys
from pathlib import Path
from typing import Annotated

import rich
import typer
from rich.console import Console

from openblockperf.apiclient import BlockperfApiClient
from openblockperf.calidus import (
    extract_signing_key_from_cbor,
    parse_key_file,
)
from openblockperf.clientid import store_client_id
from openblockperf.errors import ConfigurationError
from openblockperf.utils import async_command

from ._utils import _settings

console = Console(file=sys.stdout, force_terminal=True)


async def _register_ip(api: BlockperfApiClient):
    """Register and receive an ApiKey with the clients ip address."""


@async_command
async def register_cmd(  # noqa: PLR0912
    pool_id: Annotated[
        str | None,
        typer.Option(
            "--pool-id",
            "-p",
            help="Pool id (bech32) to register with",
        ),
    ] = None,
    calidus_skey: Annotated[
        Path | None,
        typer.Option(
            "--calidus-skey",
            help="Calidus secret key to use.",
        ),
    ] = None,
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
    register_ip: Annotated[
        bool,
        typer.Option(
            "--register-ip",
            help="Register using backend-detected relay public IPs (IPv4/IPv6 probes as available).",
        ),
    ] = False,
) -> None:
    """The register command."""

    try:
        app_settings = _settings(network=network)
        api = BlockperfApiClient(app_settings)
        if register_ip:
            if pool_id or calidus_skey:
                console.print("[yellow]Ignoring --pool-id/--calidus-skey because --relay-ip was requested.[/]")

            response = await api.clientip_registration()
            if response:
                rich.print(f"ApiKey: {response.apikey}")
                rich.print(f"ClientId: {response.client_id}")
                rich.print(f"IpAddress: {response.ipaddress}")
                store_client_id(response.client_id)

            else:
                # No response returned, nothing to do for registration
                pass
            return
        else:  # If not ip registration, then assume calidus key
            if not pool_id:
                raise ConfigurationError("Missing --pool-id for Calidus registration.")
            if not calidus_skey:
                raise ConfigurationError("Missing --calidus-skey for Calidus registration.")

            challenge = await api.request_registration_challenge(pool_id_bech32=pool_id)
            skey_data = parse_key_file(calidus_skey)
            skey = extract_signing_key_from_cbor(skey_data.get("cborHex"))
            signature = skey.sign(challenge.encode("utf-8"))
            response = await api.submit_signed_challenge(
                signature_hex=signature.hex(),
                pool_id_bech32=pool_id,
            )
            console.print(f"Your new Api key is {response.apikey}")
            console.print(f"API_KEY={response.apikey}")
            await api.test_api_key()

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
