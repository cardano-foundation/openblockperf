"""
main

The main module is the main entrypoint for the BlockPerf application."""

import typer

from blockperf.commands.analyze import analyze_app
from blockperf.commands.base import version_cmd
from blockperf.commands.monitor import monitor_app
from blockperf.commands.run import run_app
from blockperf.ui import make_blockperf_ui

# Initialize the Typer application
BlockperfCli = typer.Typer(
    name="blockperf",
    help="A CLI application for block performance analysis",
    add_completion=True,
    no_args_is_help=True,
)

# Add base commands directly to the app
BlockperfCli.command("version")(version_cmd)
BlockperfCli.add_typer(analyze_app)
BlockperfCli.add_typer(monitor_app)
BlockperfCli.add_typer(run_app)


def cli():
    BlockperfCli()


def ui():
    app = make_blockperf_ui()
    app.run()
