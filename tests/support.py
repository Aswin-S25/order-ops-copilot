"""Shared test helpers (plain functions, importable as tests.support)."""

from typing import Any

from sqlalchemy.engine import make_url

from app.config import Settings


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
        .set(database="orderops_test")
        .render_as_string(hide_password=False)
    )
    return Settings(database_url=test_db_url, env="test", **overrides)
