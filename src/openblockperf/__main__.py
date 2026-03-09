"""
main

The main module is the main entrypoint for the BlockPerf application.

The the openblockperf package is installed you can execute the `blockperf`
command. However you can also directly call this (and start the client)
without needing to install it somewhere and execute the module directly
via python -m openblockperf.

"""

import sys

import typer

from .commands import register_cmd, run_cmd, version_cmd
from .logging import setup_logging

setup_logging()

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
BlockperfCli.command("register")(register_cmd)
# BlockperfCli.add_typer(run_app)


# Entry point for blockperf script as defined in pyproject.toml
def cli():
    if sys.platform != "linux":
        sys.exit("Only Linux is supported at this time")
    BlockperfCli()


# Entry point for python -m blockperf
if __name__ == "__main__":
    cli()
