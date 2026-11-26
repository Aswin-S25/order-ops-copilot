from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import TypedDict

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.redis_client import create_redis
from db.engine import create_engine
from db.session import create_session_factory

logger = structlog.get_logger("app.lifespan")


class AppState(TypedDict):
    settings: Settings
    db_engine: AsyncEngine
    db_sessions: async_sessionmaker[AsyncSession]
    redis: Redis


def make_lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[AppState]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[AppState]:
        engine = create_engine(settings)
        redis = create_redis(settings)
        logger.info("startup_completed", env=settings.env)
        try:
            yield {
                "settings": settings,
                "db_engine": engine,
                "db_sessions": create_session_factory(engine),
                "redis": redis,
            }
        finally:
            await redis.aclose()
            await engine.dispose()
            logger.info("shutdown_completed")

    return lifespan
