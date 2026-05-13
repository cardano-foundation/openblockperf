import asyncio
import os
import sys
import traceback
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
from openblockperf.logging import logger
from openblockperf.utils import async_command

from ._utils import _settings

console = Console(file=sys.stdout, force_terminal=True)


@async_command
async def register_calidus_cmd(  # noqa: PLR0912
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
) -> None:
    """The register command."""

    try:
        app_settings = _settings(network=network)
        api = BlockperfApiClient(app_settings)
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
