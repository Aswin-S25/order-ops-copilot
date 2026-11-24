"""Alembic environment: migrations run as app_owner through an async engine (OD-6)."""

import asyncio
from typing import Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from pgvector.sqlalchemy import Vector
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import MigrationSettings
from app.logging_config import configure_logging
from db import models  # noqa: F401  (registers every model on Base.metadata)
from db.base import Base

config = context.config
target_metadata = Base.metadata

# Tests run Alembic in-process and keep pytest's logging setup.
if config.attributes.get("configure_logging", True):
    configure_logging(level="INFO", json_logs=False)


def database_url() -> str:
    # Tests pass the URL in. Otherwise DATABASE_OWNER_URL, which only migrations read.
    url: str | None = config.attributes.get("database_url")
    return url or MigrationSettings().database_owner_url.get_secret_value()


def render_item(type_: str, obj: object, autogen_context: AutogenContext) -> str | Literal[False]:
    # Autogenerate does not know pgvector's type: render it as Vector(n) and add the import.
    if type_ == "type" and isinstance(obj, Vector):
        autogen_context.imports.add("from pgvector.sqlalchemy import Vector")
        return f"Vector({obj.dim})"
    return False  # everything else: Alembic's default rendering


def run_migrations_offline() -> None:
    # `alembic upgrade head --sql` prints the SQL for review without connecting:
    # only the dialect is needed, so no credentials are involved.
    context.configure(
        dialect_name="postgresql", target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_server_default=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(
        database_url(),
        poolclass=pool.NullPool,  # one short-lived connection; nothing to pool
        connect_args={
            "server_settings": {
                "application_name": "order-ops-migrations",
                # Fail fast rather than queue behind a long transaction: a waiting
                # ALTER TABLE blocks every later query on that table.
                "lock_timeout": "5s",
            }
        },
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
