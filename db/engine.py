from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings


def create_engine(settings: Settings, *, application_name: str = "order-ops-api") -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,
        connect_args={
            "timeout": settings.db_connect_timeout_seconds,
            "server_settings": {"application_name": application_name},
        },
    )
