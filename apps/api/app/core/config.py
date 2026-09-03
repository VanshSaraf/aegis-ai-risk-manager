from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def normalize_database_url(value: str) -> str:
    """Adapt provider PostgreSQL URLs to the asyncpg SQLAlchemy dialect."""
    url = make_url(value)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    if url.drivername != "postgresql+asyncpg":
        return value

    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    # Neon adds this libpq option by default; asyncpg does not accept it.
    query.pop("channel_binding", None)
    if sslmode is not None and "ssl" not in query:
        query["ssl"] = sslmode
    return url.set(query=query).render_as_string(hide_password=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AEGIS_", extra="ignore")

    app_name: str = "Aegis API"
    environment: str = "development"
    database_url: str = Field(default="postgresql+asyncpg://aegis:aegis@localhost:5432/aegis")
    migration_database_url: str | None = None
    sql_echo: bool = False
    investigator_provider: str = "disabled"
    investigator_max_narrative_chars: int = Field(default=2000, ge=100, le=5000)
    openai_api_key: str | None = None
    cors_allowed_origins: str = "http://localhost:3000"
    demo_mode: bool = False

    @field_validator("database_url", "migration_database_url", mode="before")
    @classmethod
    def normalize_postgres_urls(cls, value: object) -> object:
        if isinstance(value, str) and value:
            return normalize_database_url(value)
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def alembic_database_url(self) -> str:
        return self.migration_database_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
