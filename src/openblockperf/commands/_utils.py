"""Command helper functions."""

import sys

from pydantic import ValidationError

from openblockperf.config import AppSettings, Network


def _settings(network: str | None = None, api_url: str | None = None, node_unit_name: str | None = None) -> AppSettings:
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
        settings = AppSettings(**overrides)
    except ValidationError as e:
        sys.exit(f"Error creating settings: {e!r}")
    return settings
