"""
main

The main module is the main entrypoint for the BlockPerf application."""

from blockperf.cli import blockperf_app


def run():
    blockperf_app()


if __name__ == "__main__":
    run()
