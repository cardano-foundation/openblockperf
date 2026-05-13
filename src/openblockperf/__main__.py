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
import traceback

import typer
from rich.console import Console

from openblockperf.commands import register_calidus_cmd, register_ip_cmd, run_cmd, version_cmd
from openblockperf.errors import ConfigurationError
from openblockperf.logging import logger, setup_logging

# Initialize the Typer application
BlockperfCli = typer.Typer(
    name="blockperf",
    help="A CLI application for cardano node performance analysis",
    add_completion=False,
    no_args_is_help=True,
)

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
            traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        logger.exception(e)
        if isinstance(e, ExceptionGroup):
            _console.print(f"[bold red]App failed with {len(e.exceptions)} error(s):[/]")
            for exc in e.exceptions:
                _console.print(f"[bold red]- {type(exc).__name__}: {exc!r}[/]")
                if os.getenv("OPENBLOCKPERF_LOG_LEVEL", "INFO") == "DEBUG":
                    traceback.print_exc()
        else:
            _console.print(f"[bold red]Application failed: {e!r}[/]")
            if os.getenv("OPENBLOCKPERF_LOG_LEVEL", "INFO") == "DEBUG":
                traceback.print_exc()
        sys.exit(1)


# Entry point for python -m blockperf
if __name__ == "__main__":
    cli()
