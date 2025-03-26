from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openblockperf_api_key: str


# see BaseSettings for more details
settings = Settings(_env_file=".env", _env_file_encoding="utf-8")
