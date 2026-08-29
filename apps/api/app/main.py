from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.app.api.routes import router
from apps.api.app.core.config import get_settings
from apps.api.app.db.session import engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Foundation API for coordinated payment-abuse detection.",
    lifespan=lifespan,
)
app.include_router(router)
