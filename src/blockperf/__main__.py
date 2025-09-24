"""
main

The main module is the main entrypoint for the BlockPerf application."""

from blockperf.app import make_blockperf_cli, make_blockperf_ui


def cli():
    app = make_blockperf_cli()
    app()


def ui():
    app = make_blockperf_ui()
    app.run()
