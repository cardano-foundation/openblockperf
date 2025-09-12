import os

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "OPENBLOCKPERF_"


class AppSettings(BaseSettings):
    # openblockperf_api_key: str
    # Interval in seconds to check groups for whether they are ready to process
    eventgroup_inspection_interval: int = 6
    # To not process groups that may be just added right now, i wanted
    # to have some control over when a certain group will get processed.
    eventgroup_min_age: int = 10


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


def load_settings():
    settings_envs = {
        "dev": AppSettingsDev,
        # "test": AppSettingsProd,
        # "production": AppSettingsProd,
    }
    return settings_envs[os.environ.get("ENV", "dev")]()


settings = load_settings()
