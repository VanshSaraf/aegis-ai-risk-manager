from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.engine import make_url

from apps.api.app.core.config import Settings, normalize_database_url


def test_neon_url_is_normalized_for_sqlalchemy_asyncpg() -> None:
    normalized = normalize_database_url(
        "postgresql://user:secret@example-pooler.neon.tech/aegis"
        "?sslmode=require&channel_binding=require"
    )

    assert normalized == (
        "postgresql+asyncpg://user:secret@example-pooler.neon.tech/aegis?ssl=require"
    )
    _, connect_args = PGDialect_asyncpg().create_connect_args(make_url(normalized))
    assert connect_args["ssl"] == "require"
    assert "sslmode" not in connect_args
    assert "channel_binding" not in connect_args


def test_asyncpg_url_and_local_url_remain_supported() -> None:
    local = "postgresql+asyncpg://aegis:aegis@localhost:5432/aegis"

    assert normalize_database_url(local) == local
    assert (
        normalize_database_url("postgres://user:secret@example.neon.tech/aegis?sslmode=verify-full")
        == "postgresql+asyncpg://user:secret@example.neon.tech/aegis?ssl=verify-full"
    )


def test_cors_parsing_and_direct_migration_url() -> None:
    settings = Settings(
        database_url="postgresql://app:secret@example-pooler.neon.tech/aegis?sslmode=require",
        migration_database_url=(
            "postgresql://owner:secret@example.neon.tech/aegis?sslmode=require"
            "&channel_binding=require"
        ),
        cors_allowed_origins=(" http://localhost:3000, https://aegis.example.vercel.app, ,"),
    )

    assert settings.cors_origins == [
        "http://localhost:3000",
        "https://aegis.example.vercel.app",
    ]
    assert "example-pooler.neon.tech" in settings.database_url
    assert settings.alembic_database_url == (
        "postgresql+asyncpg://owner:secret@example.neon.tech/aegis?ssl=require"
    )
