import os
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Network(Enum):
    """All supported networks"""

    MAINNET: str = "mainnet"
    PREPROD: str = "preprod"
    PREVIEW: str = "preview"


@dataclass(frozen=True)
class NetworkConfig:
    """Network specific configurations"""

    magic: int
    starttime: int
    api_url: str


ENV_PREFIX = "OPENBLOCKPERF_"


class AppSettings(BaseSettings):
    api_port: int = 443
    api_path: str = "/api/v0/"
    api_key: str
    api_clientid: str | None = None
    api_client_secret: str | None = None
    check_interval: int = 2  # Interval in seconds to check for groups/blocks
    min_age: int = 10  # Wait x seconds before even processing a group/block

    local_addr: str = "0.0.0.0"
    local_port: int = 3001
    # Using Field() to validate input values match one of the possible enum values
    network: Network = Field(default=Network.MAINNET, validation_alias="network")  # fmt: off

    # Private attribute to store CLI override for API URL
    _api_url_override: str | None = None

    # Class-level dictionary to store network specific configurations
    _NETWORK_CONFIGS: ClassVar[dict[Network, NetworkConfig]] = {
        # Took network starttimes from shelly-genesis.json
        Network.MAINNET.value: NetworkConfig(
            magic=764824073,
            starttime=1591566291,  # Sun Jun 07 2020 21:44:51 GMT+0000
            api_url="https://api.openblockperf.cardano.org",
        ),
        Network.PREPROD.value: NetworkConfig(
            magic=1,
            starttime=1654041600,  # Wed Jun 01 2022 00:00:00 GMT+0000
            api_url="https://preprod.api.openblockperf.cardano.org",
        ),
        Network.PREVIEW.value: NetworkConfig(
            magic=2,
            starttime=1666656000,  # Tue Oct 25 2022 00:00:00 GMT+0000
            api_url="https://preview.api.openblockperf.cardano.org",
        ),
    }

    @property
    def full_api_url(self):
        """Return the complete url to the api endpoint. If one is provided
        on the cli, just return that without adding any extra ports or paths.
        """
        if self._api_url_override:
            return self._api_url_override

        _api_url = self._NETWORK_CONFIGS[self.network.value].api_url
        return f"{_api_url}:{self.api_port}{self.api_path}"

    @property
    def network_config(self) -> NetworkConfig:
        """Retrieve configuration for the current network."""
        # The field validation from self.network ensures value will always be a valid network
        return self._NETWORK_CONFIGS[self.network.value]


class AppSettingsDev(AppSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=".env.dev")


class AppSettingsTest(AppSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=".env.test")


class AppSettingsProd(AppSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=".env.prod")


def settings(
    network: Network | str | None = None,
    api_url_override: str | None = None,
) -> AppSettings:
    """
    Create settings instance with optional CLI overrides.

    Priority order (highest to lowest):
    1. CLI arguments (network, api_url_override)
    2. Environment variables (OPENBLOCKPERF_*)
    3. .env file values
    4. Default values

    Args:
        network: Network override from CLI (highest priority)
        api_url_override: API URL override from CLI (bypasses network-specific URL)
    """
    settings_env_map = {
        "dev": AppSettingsDev,
        "test": AppSettingsProd,
        "production": AppSettingsProd,
    }
    env = os.environ.get("ENV", "dev")
    settings_class = settings_env_map.get(env)
    if not settings_class:
        raise RuntimeError(f"No settings found for {env}")

    # Create settings instance
    settings_instance = settings_class()

    # Apply CLI overrides (highest priority)
    if network is not None:
        # Convert string to Network enum if needed
        if isinstance(network, str):
            try:
                network = Network(network.lower())
            except ValueError:
                valid_networks = [n.value for n in Network]
                raise ValueError(f"Invalid network '{network}'. Must be one of: {', '.join(valid_networks)}")
        # Override the network setting
        settings_instance.network = network

    # Store API URL override if provided (will be used instead of network-derived URL)
    if api_url_override is not None:
        settings_instance._api_url_override = api_url_override

    return settings_instance
