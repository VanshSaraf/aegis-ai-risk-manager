import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

TEST_DATABASE_URL = os.getenv("AEGIS_TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["AEGIS_DATABASE_URL"] = TEST_DATABASE_URL


@pytest.fixture(scope="session")
def integration_database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("AEGIS_TEST_DATABASE_URL is not configured")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
async def prepared_database(integration_database_url: str) -> AsyncIterator[None]:
    from apps.api.app import models  # noqa: F401
    from apps.api.app.db.base import Base
    from apps.api.app.db.session import engine

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def clean_database(prepared_database: None) -> AsyncIterator[None]:
    from apps.api.app.db.base import Base
    from apps.api.app.db.session import engine

    async with engine.begin() as connection:
        table_names = [table.name for table in reversed(Base.metadata.sorted_tables)]
        if table_names:
            quoted = ", ".join(f'"{name}"' for name in table_names if name != "alembic_version")
            if quoted:
                await connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
async def client(clean_database: None) -> AsyncIterator[AsyncClient]:
    from apps.api.app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client
