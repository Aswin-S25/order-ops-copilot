"""Shared test helpers (plain functions, importable as tests.support)."""

import asyncio
import uuid
from pathlib import Path
from typing import Any

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import MigrationSettings, Settings
from db.engine import create_engine
from db.session import create_session_factory, tenant_session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE = "orderops_test"


def make_settings(**overrides: Any) -> Settings:
    """Hermetic settings for unit tests: never reads .env, never touches real infra."""
    values: dict[str, Any] = {
        "env": "test",
        "database_url": "postgresql+asyncpg://u:p@127.0.0.1:5433/db",
        "redis_url": "redis://127.0.0.1:6379/0",
        "openai_api_key": "sk-test",
        "openai_model": "test-model",
        **overrides,
    }
    return Settings(_env_file=None, **values)


def integration_settings(**overrides: Any) -> Settings:
    """Real credentials from .env, but always pointed at the orderops_test database."""
    base = Settings()
    test_db_url = (
        make_url(base.database_url.get_secret_value())
        .set(database=TEST_DATABASE)
        .render_as_string(hide_password=False)
    )
    return Settings(database_url=test_db_url, env="test", **overrides)


def owner_test_url() -> str:
    """app_owner credentials from .env, always pointed at orderops_test.

    Migration tests downgrade to an empty schema, so they must never reach the dev database.
    """
    url = MigrationSettings().database_owner_url.get_secret_value()
    return make_url(url).set(database=TEST_DATABASE).render_as_string(hide_password=False)


def alembic_config(database_url: str | None = None) -> Config:
    """Alembic run in-process. Offline (--sql) mode needs no URL."""
    config = Config(toml_file=str(PROJECT_ROOT / "pyproject.toml"))
    config.attributes["configure_logging"] = False  # keep pytest's log capture
    if database_url is not None:
        config.attributes["database_url"] = database_url
    return config


async def empty_test_database() -> None:
    """Delete all application data in orderops_test. TRUNCATE needs the owner role."""
    engine = create_async_engine(owner_test_url())
    try:
        async with engine.begin() as conn:
            # CASCADE follows every foreign key that leads to tenants: all application data.
            await conn.execute(text("TRUNCATE tenants CASCADE"))
    finally:
        await engine.dispose()


def query_as_tenant(tenant_id: uuid.UUID, sql: str, **params: Any) -> list[Any]:
    """One query as app_user, inside a transaction scoped to `tenant_id`."""

    async def run() -> list[Any]:
        engine = create_engine(integration_settings())
        try:
            async with tenant_session(create_session_factory(engine), tenant_id) as session:
                return list((await session.execute(text(sql), params)).all())
        finally:
            await engine.dispose()

    return asyncio.run(run())
