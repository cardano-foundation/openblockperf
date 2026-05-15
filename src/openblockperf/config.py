import socket
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


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


class AppSettings(BaseSettings):
    """Application settings loaded from environment variables and .env file"""

    model_config = SettingsConfigDict(
        env_prefix="OPENBLOCKPERF_",  # Every ENV Variable assumes this prefix such that all env vars are in a similar "namespace"
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    api_url: str | None = None
    api_port: int = 443
    api_path: str = "/api/v0/"
    api_key: str | None = None
    block_sample_check_interval: int = 2  # Interval in seconds to check for groups/blocks
    min_age: int = 10  # Wait x seconds before even processing a group/block
    node_name: str = socket.gethostname()  # This clients hostname
    node_unit_name: str = "cardano-tracer"
    # Ekg endpoint url
    ekg_url: str = "http://localhost:12798/metrics"

    # Node Sync Check verifies the node is synced with the chain
    sync_check_interval: int = 15  # How often (seconds) to poll sync state
    sync_check_enabled: bool = True  # Whether to enable the sync gate at all (set False to skip during dev/testing)
    sync_check_threshold: float = 99.9

    local_addr: str = "0.0.0.0"
    local_port: int = 3001
    # Using Field() to validate input values match one of the possible enum values
    network: Network = Field(default=Network.MAINNET, validation_alias="network")  # fmt: off

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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Inject an optional JSON/YAML config file as a low-priority source.

        Pass the file path via the ``_config_file`` init kwarg. Sources earlier
        in the returned tuple win, so env vars and explicit init kwargs still
        override values from the file.
        """
        config_file = init_settings.init_kwargs.pop("_config_file", None)

        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
            dotenv_settings,
        ]

        if config_file:
            path = Path(config_file)
            if not path.is_file():
                raise FileNotFoundError(f"Config file not found: {path}")
            suffix = path.suffix.lower()
            if suffix == ".json":
                sources.append(JsonConfigSettingsSource(settings_cls, json_file=path))
            elif suffix in (".yaml", ".yml"):
                sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=path))
            else:
                raise ValueError(
                    f"Unsupported config file extension {suffix!r}. Use .json, .yaml, or .yml"
                )

        sources.append(file_secret_settings)
        return tuple(sources)

    @property
    def full_api_url(self):
        """Return the complete url to the api endpoint. If one is provided
        on the cli, just return that without adding any extra ports or paths.
        """
        # Use api_url if set
        if self.api_url:
            return f"{self.api_url}:{self.api_port}{self.api_path}"

        # else look up from network configuration
        _api_url = self._NETWORK_CONFIGS[self.network.value].api_url
        return f"{_api_url}:{self.api_port}{self.api_path}"

    @property
    def network_config(self) -> NetworkConfig:
        """Retrieve configuration for the current network."""
        # The field validation from self.network ensures value will always be a valid network
        return self._NETWORK_CONFIGS[self.network.value]


# There is no global settings object here because i wanted the cli to
# be able to override things. Hence the settings is created in the command
# and then passed into the app.
