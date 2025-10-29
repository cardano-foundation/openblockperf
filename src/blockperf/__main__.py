"""
main

The main module is the main entrypoint for the BlockPerf application.

"""

import typer

from blockperf.commands import run_app, version_cmd
from blockperf.logging import setup_logging

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
BlockperfCli.add_typer(run_app)


def cli():
    BlockperfCli()
