"""Migrations against real Postgres (orderops_test). Needs `docker compose up -d`."""

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from db import models  # noqa: F401  (registers every model on Base.metadata)
from db.base import Base
from db.engine import create_engine
from tests.support import alembic_config, integration_settings, owner_test_url

pytestmark = pytest.mark.integration


def run_as_owner[T](work: Callable[[Connection], T]) -> T:
    async def run() -> T:
        engine = create_async_engine(owner_test_url())
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(work)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def run_as_runtime_role(statement: str) -> Any:
    async def run() -> Any:
        engine = create_engine(integration_settings())
        try:
            async with engine.connect() as conn:
                return (await conn.execute(text(statement))).one()
        finally:
            await engine.dispose()

    return asyncio.run(run())


# Everything a downgrade must restore: columns, constraints, indexes and the runtime
# role's privileges. A forgotten GRANT breaks nothing on re-upgrade, so only a
# before/after comparison can catch it.
SNAPSHOT_QUERIES = (
    "SELECT table_name, column_name, data_type, is_nullable, column_default"
    " FROM information_schema.columns WHERE table_schema = 'public'",
    "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)"
    " FROM pg_constraint WHERE connamespace = 'public'::regnamespace",
    "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public'",
    "SELECT table_name, privilege_type FROM information_schema.role_table_grants"
    " WHERE grantee = 'app_user'",
    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
    " WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'",
    "SELECT tablename, policyname, roles::text, cmd, qual, with_check FROM pg_policies"
    " WHERE schemaname = 'public'",
)


def schema_snapshot(conn: Connection) -> set[tuple[Any, ...]]:
    return {
        (number, *row)
        for number, query in enumerate(SNAPSHOT_QUERIES)
        for row in conn.execute(text(query))
    }


def drop_version_table(conn: Connection) -> None:
    conn.execute(text("DROP TABLE alembic_version"))
    conn.commit()


@pytest.fixture
def at_head() -> None:
    command.upgrade(alembic_config(owner_test_url()), "head")


def test_every_downgrade_restores_the_exact_previous_state() -> None:
    # The "stairway": for each revision, upgrade then downgrade, and the schema and
    # privileges must be exactly what they were before. Then upgrade again, because a
    # leftover object would make the re-run fail with "already exists".
    config = alembic_config(owner_test_url())
    revisions = list(reversed(list(ScriptDirectory.from_config(config).walk_revisions())))
    command.downgrade(config, "base")
    # Start truly fresh: a buggy downgrade must not shape the state we compare against.
    # `stamp base` recreates an empty version table with its default privileges.
    run_as_owner(drop_version_table)
    command.stamp(config, "base")
    for revision in revisions:
        before = run_as_owner(schema_snapshot)
        command.upgrade(config, revision.revision)
        command.downgrade(config, revision.down_revision or "base")
        assert run_as_owner(schema_snapshot) == before, f"{revision.revision} downgrade"
        command.upgrade(config, revision.revision)  # ends at head


def test_models_and_migrations_agree(at_head: None) -> None:
    # Fails when a model changes without a migration, or a migration without its model.
    def diff(conn: Connection) -> list[Any]:
        context = MigrationContext.configure(conn, opts={"compare_server_default": True})
        return compare_metadata(context, Base.metadata)

    assert run_as_owner(diff) == []


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE approval_audit SET details = NULL",
        "DELETE FROM approval_audit",
        "UPDATE audit_log SET details = NULL",
        "DELETE FROM audit_log",
        "UPDATE alembic_version SET version_num = '0001'",
    ],
)
def test_runtime_role_cannot_rewrite_history(at_head: None, statement: str) -> None:
    # Postgres checks privileges before touching any row, so empty tables prove it too.
    with pytest.raises(ProgrammingError, match="permission denied"):
        run_as_runtime_role(statement)


def test_runtime_role_can_still_append_and_read_audit_entries(at_head: None) -> None:
    # The REVOKE must not be broader than intended: approvals still need INSERT.
    row = run_as_runtime_role(
        "SELECT has_table_privilege('approval_audit', 'INSERT'),"
        " has_table_privilege('approval_audit', 'SELECT'),"
        " has_table_privilege('audit_log', 'INSERT'),"
        " has_table_privilege('audit_log', 'SELECT')"
    )
    assert tuple(row) == (True, True, True, True)
