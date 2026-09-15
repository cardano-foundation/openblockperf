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

from openblockperf import __version__
from openblockperf.commands import register_calidus_cmd, register_ip_cmd, run_cmd, version_cmd
from openblockperf.commands._utils import SharedOptions
from openblockperf.errors import ApiError, ConfigurationError
from openblockperf.logging import logger, setup_logging

# Initialize the Typer application
BlockperfCli = typer.Typer(
    name="blockperf",
    help="A CLI application for cardano node performance analysis",
    add_completion=False,
    no_args_is_help=True,
)

CONFIG_ENV_VAR = "OPENBLOCKPERF_CONFIG"


def resolve_config_path(cli_config: Path | None) -> tuple[Path | None, str | None]:
    """Resolve config path from ``--config`` or ``OPENBLOCKPERF_CONFIG``.

    Returns ``(path, source)`` where source is ``\"flag\"``, ``\"env\"``, or ``None``.
    """
    if cli_config is not None:
        return cli_config, "flag"
    env_config = os.getenv(CONFIG_ENV_VAR, "").strip()
    if not env_config:
        return None, None
    env_path = Path(env_config).expanduser()
    if not env_path.is_file():
        raise ConfigurationError(
            f"{CONFIG_ENV_VAR} is set to {env_path} but that file does not exist "
            "or is not a regular file"
        )
    if not os.access(env_path, os.R_OK):
        raise ConfigurationError(f"{CONFIG_ENV_VAR} file is not readable: {env_path}")
    return env_path, "env"


def _print_version_and_exit() -> None:
    """Print a short version line and exit (used by ``--version`` / ``-V``)."""
    typer.echo(f"openblockperf {__version__}")
    raise typer.Exit()


def version_option_callback(value: bool) -> None:
    if value:
        _print_version_and_exit()


@BlockperfCli.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            help="Show the installed openblockperf version and exit.",
            callback=version_option_callback,
            is_eager=True,
        ),
    ] = None,
    network: Annotated[
        str | None,
        typer.Option(
            "--network",
            "-n",
            help="Cardano network to connect to (mainnet, preprod, preview). Used as the API path prefix and chain magic. Defaults to OPENBLOCKPERF_NETWORK env var or 'mainnet'.",
        ),
    ] = None,
    api_url: Annotated[
        str | None,
        typer.Option(
            "--api-url",
            help="""Override API URL and skip SRV discovery (for development/testing).

            Provide the full base URL, including port and path.
            E.g.: http://localhost:8000/mainnet/api/v0
        """,
        ),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help=f"""Path to a JSON or YAML configuration file (extension must be .json, .yaml or .yml).

            Values from the file populate AppSettings. Environment variables and other
            CLI flags still take precedence over the file.

            When omitted, {CONFIG_ENV_VAR} is used if set (installer/wrapper typically
            points this at the installed config.json).
        """,
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
) -> None:
    """Callback implements global flags that are shared to all subcommands via typer.Context."""
    resolved_config, config_source = resolve_config_path(config)
    ctx.obj = SharedOptions(network=network, api_url=api_url, config=resolved_config)
    if resolved_config is not None:
        if config_source == "env":
            rich.print(f"Using config file from {CONFIG_ENV_VAR}: {resolved_config.absolute()}")
        else:
            rich.print(f"Config loaded {resolved_config.absolute()}")


# Add commands directly to the app
BlockperfCli.command("version")(version_cmd)
BlockperfCli.command("run")(run_cmd)
BlockperfCli.command("register-ip")(register_ip_cmd)
BlockperfCli.command("register-calidus")(register_calidus_cmd)

_console = Console(file=sys.stdout, force_terminal=True)


# Entry point for blockperf script as defined in pyproject.toml
def cli():
    # Allow version checks on any platform (useful for local/dev installs).
    if sys.platform != "linux" and not {"--version", "-V"} & set(sys.argv[1:]):
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
    except ApiError as e:
        _console.print(f"[bold red]API error:[/] {e}")
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
