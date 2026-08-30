from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AEGIS_", extra="ignore")

    app_name: str = "Aegis API"
    environment: str = "development"
    database_url: str = Field(default="postgresql+asyncpg://aegis:aegis@localhost:5432/aegis")
    sql_echo: bool = False
    investigator_provider: str = "disabled"
    investigator_max_narrative_chars: int = Field(default=2000, ge=100, le=5000)
    openai_api_key: str | None = None
    cors_allowed_origins: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
