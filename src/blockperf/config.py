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


ENV_PREFIX = "OPENBLOCKPERF_"


class AppSettings(BaseSettings):
    api_base_url: str = "https://api.openblockperf.cardano.org"
    api_base_port: int = 8080
    api_base_path: str = "/api/v0/"
    api_key: str
    api_clientid: str | None = None
    api_client_secret: str | None = None
    check_interval: int = 2  # Interval in seconds to check for groups/blocks
    min_age: int = 10  # Wait x seconds before even processing a group/block

    local_addr: str = "0.0.0.0"
    local_port: int = 3001
    # Using Field to validate input values match one of the possible enum values
    network: Network = Field(default=Network.MAINNET, validation_alias="network")  # fmt: off

    # Class-level dictionary to store network specific configurations
    _NETWORK_CONFIGS: ClassVar[dict[Network, NetworkConfig]] = {
        # Took network starttimes from shelly-genesis.json
        Network.MAINNET.value: NetworkConfig(
            magic=764824073,
            starttime=1591566291,
        ),
        Network.PREPROD.value: NetworkConfig(
            magic=1,
            starttime=1654041600,
        ),
        Network.PREVIEW.value: NetworkConfig(
            magic=2,
            starttime=1666656000,
        ),
    }

    @property
    def network_config(self) -> NetworkConfig:
        """Retrieve configuration for the current network."""
        # The field validation from self.network ensures it will always the
        # value will always be a valid network
        return self._NETWORK_CONFIGS[self.network.value]


class AppSettingsDev(AppSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX, env_file=".env.dev"
    )


class AppSettingsTest(AppSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX, env_file=".env.test"
    )


class AppSettingsProd(AppSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX, env_file=".env.prod"
    )


def settings() -> AppSettings:
    settings_env_map = {
        "dev": AppSettingsDev,
        "test": AppSettingsProd,
        "production": AppSettingsProd,
    }
    env = os.environ.get("ENV", "dev")
    settings_class = settings_env_map.get(env)
    if not settings_class:
        raise RuntimeError(f"No settings found for {env}")
    return settings_class()
