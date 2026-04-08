"""Command helper functions."""

import sys

from pydantic import ValidationError

from openblockperf.config import AppSettings, Network


def _settings(network: str | None, api_url: str | None) -> AppSettings:
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
            except ValueError as e:
                valid_networks = [n.value for n in Network]
                sys.exit(f"Invalid network {network!r}. Must be one of: {', '.join(valid_networks)}")
            overrides["network"] = network
        if api_url:
            overrides["api_url"] = api_url
        settings = AppSettings(**overrides)
    except ValidationError as e:
        sys.exit(f"Error creating settings: {e!r}")
    return settings
