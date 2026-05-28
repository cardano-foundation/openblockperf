"""Command helper functions."""
import os
import rich
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from openblockperf.config import AppSettings, Network


@dataclass(frozen=True)
class SharedOptions:
    """Options declared on the root Typer callback and shared across subcommands.

    Provided to each subcommand as ``typer.Context`` so each can access
    the same flags without redeclaring them.
    """

    network: str | None = None
    api_url: str | None = None
    config: Path | None = None


def _settings(
    network: str | None = None,
    api_url: str | None = None,
    node_unit_name: str | None = None,
    tracer_log_file: Path | None = None,
    config_file: Path | None = None,
) -> AppSettings:
    """Helper that creates the AppSettings instance.

    Returns:
        The settings instance.
    """
    try:
        overrides = {}
        if network:
            if not isinstance(network, str):
                sys.exit(f"{network=} is not a string")
            try:
                network = Network(network.lower())
            except ValueError:
                valid_networks = [n.value for n in Network]
                sys.exit(f"Invalid network {network!r}. Must be one of: {', '.join(valid_networks)}")
            overrides["network"] = network
        if api_url:
            overrides["api_url"] = api_url
        if node_unit_name:
            overrides["node_unit_name"] = node_unit_name
        if tracer_log_file:
            overrides["tracer_log_file"] = tracer_log_file
        if config_file:
            overrides["_config_file"] = config_file
        settings = AppSettings(**overrides)
    except ValidationError as e:
        sys.exit(f"Error creating settings: {e!r}")
    except (FileNotFoundError, ValueError) as e:
        sys.exit(f"Error loading config file: {e}")
    else:
        if os.getenv("OPENBLOCKPERF_LOG_LEVEL", "INFO") == "DEBUG":
            rich.print(settings)
        return settings
