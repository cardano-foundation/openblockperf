"""
main

The main module is the main entrypoint for the BlockPerf application.

The the openblockperf package is installed you can execute the `blockperf`
command. However you can also directly call this (and start the client)
without needing to install it somewhere and execute the module directly
via python -m openblockperf.

"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Annotated

import rich
import typer
from rich.console import Console

from openblockperf.commands import register_calidus_cmd, register_ip_cmd, run_cmd, version_cmd
from openblockperf.commands._utils import SharedOptions
from openblockperf.errors import ConfigurationError
from openblockperf.logging import logger, setup_logging

# Initialize the Typer application
BlockperfCli = typer.Typer(
    name="blockperf",
    help="A CLI application for cardano node performance analysis",
    add_completion=False,
    no_args_is_help=True,
)


@BlockperfCli.callback()
def main(
    ctx: typer.Context,
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
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="""Path to a JSON or YAML configuration file (extension must be .json, .yaml or .yml).

            Values from the file populate AppSettings. Environment variables and other
            CLI flags still take precedence over the file.
        """,
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
) -> None:
    """Callback implements global flags that are shared to all subcommands via typer.Context."""
    ctx.obj = SharedOptions(network=network, api_url=api_url, config=config)
    if config:
        rich.print(f"Config loaded {config.absolute()}")


# Add commands directly to the app
BlockperfCli.command("version")(version_cmd)
BlockperfCli.command("run")(run_cmd)
BlockperfCli.command("register-ip")(register_ip_cmd)
BlockperfCli.command("register-calidus")(register_calidus_cmd)

_console = Console(file=sys.stdout, force_terminal=True)


# Entry point for blockperf script as defined in pyproject.toml
def cli():
    if sys.platform != "linux":
        sys.exit("Only Linux is supported at this time")
    setup_logging(os.getenv("OPENBLOCKPERF_LOG_LEVEL", "INFO"))
    try:
        BlockperfCli()
    except asyncio.CancelledError:
        _console.print("[bold yellow]Application was cancelled[/]")
        sys.exit(0)
    except ConfigurationError as e:
        _console.print(f"[bold red]Configuration error:[/] {e}")
        if os.getenv("OPENBLOCKPERF_LOG_LEVEL", "INFO") == "DEBUG":
            logger.exception(e)
        sys.exit(1)
    except Exception as e:
        if isinstance(e, ExceptionGroup):
            _console.print(f"[bold red]App failed with {len(e.exceptions)} error(s):[/]")
            for exc in e.exceptions:
                _console.print(f"[bold red]- {type(exc).__name__}: {exc!r}[/]")
                if os.getenv("OPENBLOCKPERF_LOG_LEVEL", "INFO") == "DEBUG":
                    logger.exception(e)
        else:
            _console.print(f"[bold red]Application failed: {e!r}[/]")
            if os.getenv("OPENBLOCKPERF_LOG_LEVEL", "INFO") == "DEBUG":
                logger.exception(e)
        sys.exit(1)


# Entry point for python -m blockperf
if __name__ == "__main__":
    cli()
