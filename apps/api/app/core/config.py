from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AEGIS_", extra="ignore")

    app_name: str = "Aegis API"
    environment: str = "development"
    database_url: str = Field(default="postgresql+asyncpg://aegis:aegis@localhost:5432/aegis")
    sql_echo: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
