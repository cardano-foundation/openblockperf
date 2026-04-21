import asyncio
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from openblockperf.apiclient import BlockperfApiClient
from openblockperf.calidus import (
    extract_signing_key_from_cbor,
    parse_key_file,
)
from openblockperf.errors import ConfigurationError
from openblockperf.utils import async_command

from ._utils import _settings

console = Console(file=sys.stdout, force_terminal=True)


@async_command
async def register_cmd(
    pool_id: str = typer.Option(
        None,
        "--pool-id",
        "-p",
        help="Pool id (bech32) to register with",
    ),
    calidus_skey: Path = Annotated[
        Path,
        typer.Option(
            None,
            "--calidus-skey",
            help="Calidus secret key to use.",
        ),
    ],
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
    relay_ip: bool = typer.Option(
        False,
        "--relay-ip",
        help="Register using backend-detected relay public IPs (IPv4/IPv6 probes as available).",
    ),
) -> None:
    """The register command."""

    try:
        app_settings = settings(network=network, api_url_override=api_url)
        api = BlockperfApiClient(app_settings)
        if relay_ip:
            if pool_id or calidus_skey:
                console.print(
                    "[yellow]Ignoring --pool-id/--calidus-skey because --relay-ip was requested.[/]"
                )
            cookies: dict[str, str] = {}
            relay_ips: dict[str, str] = {}
            for family in ("v4", "v6"):
                try:
                    probe = await api.request_relay_ip_probe(family)
                    cookies[family] = probe.cookie
                    relay_ips[family] = probe.detected_ip or "validated"
                    detected = f" (detected {probe.detected_ip})" if probe.detected_ip else ""
                    console.print(f"[green]{family} probe accepted{detected}[/]")
                except Exception as e:
                    console.print(f"[yellow]{family} probe unavailable:[/] {e}")

            if not cookies:
                raise ConfigurationError(
                    "Could not validate any public IP family for relay registration (v4/v6)."
                )

            response = await api.submit_relay_ip_registration(
                cookie_v4=cookies.get("v4"),
                cookie_v6=cookies.get("v6"),
            )
            console.print(f"Your new Api key is {response.apikey}")
            # Machine-readable key line for installer automation.
            if "v4" in relay_ips:
                console.print(f"RELAY_IP_V4={relay_ips['v4']}")
            if "v6" in relay_ips:
                console.print(f"RELAY_IP_V6={relay_ips['v6']}")
            console.print(f"API_KEY={response.apikey}")
            return

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
