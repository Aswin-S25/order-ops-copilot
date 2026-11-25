"""Row-level security against real Postgres, as the runtime role (ADR-0003)."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from db.base import Base
from db.engine import create_engine
from db.models import AuditLog
from db.seed import seed, seed_id
from db.session import create_session_factory, tenant_session
from tests.support import (
    alembic_config,
    empty_test_database,
    integration_settings,
    owner_test_url,
    query_as_tenant,
)

pytestmark = pytest.mark.integration

ALPHA = seed_id("alpha-market")
BETA = seed_id("beta-bazaar")
ORDERS_PER_TENANT = 8
# Every table with a tenant_id column. Driven by the models, so a new tenant table fails
# these tests until a migration gives it RLS.
TENANT_OWNED = sorted(t.name for t in Base.metadata.sorted_tables if "tenant_id" in t.c)
RLS_VIOLATION = "violates row-level security policy"


@pytest.fixture(scope="module", autouse=True)
def seeded_test_database() -> None:
    command.upgrade(alembic_config(owner_test_url()), "head")

    async def run() -> None:
        await empty_test_database()
        engine = create_engine(integration_settings())
        try:
            await seed(engine, password="rls-test-password", now=datetime.now(UTC))
        finally:
            await engine.dispose()

    asyncio.run(run())


def as_runtime_role[T](work: Callable[[AsyncEngine], Awaitable[T]], **overrides: Any) -> T:
    """Run `work` with a fresh app_user engine, then dispose of it."""

    async def run() -> T:
        engine = create_engine(integration_settings(**overrides))
        try:
            return await work(engine)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def audit_entry(tenant_id: Any) -> Any:
    # audit_log needs nothing but a tenant: any rejection below can only come from RLS.
    return insert(AuditLog).values(tenant_id=tenant_id, action="rls_probe", target_type="test")


def test_exactly_the_tenant_owned_tables_force_rls_with_a_policy() -> None:
    forced = query_as_tenant(
        ALPHA,
        "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace"
        " AND relrowsecurity AND relforcerowsecurity",
    )
    policies = query_as_tenant(
        ALPHA,
        "SELECT tablename FROM pg_policies"
        " WHERE schemaname = 'public' AND policyname = 'tenant_isolation'",
    )
    assert sorted(row.relname for row in forced) == TENANT_OWNED
    assert sorted(row.tablename for row in policies) == TENANT_OWNED
    assert "tenants" not in TENANT_OWNED  # login must read it before any tenant is known


def test_without_tenant_context_nothing_is_visible() -> None:
    async def count_every_table(engine: AsyncEngine) -> dict[str, int]:
        async with engine.connect() as conn:
            return {
                name: (
                    await conn.execute(select(func.count()).select_from(Base.metadata.tables[name]))
                ).scalar_one()
                for name in TENANT_OWNED
            }

    assert as_runtime_role(count_every_table) == dict.fromkeys(TENANT_OWNED, 0)


def test_without_tenant_context_writes_are_rejected() -> None:
    async def write(engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            await conn.execute(audit_entry(ALPHA))

    with pytest.raises(ProgrammingError, match=RLS_VIOLATION):
        as_runtime_role(write)


@pytest.mark.parametrize("tenant_id", [ALPHA, BETA], ids=["alpha", "beta"])
def test_a_tenant_sees_only_its_own_rows_even_without_a_filter(tenant_id: Any) -> None:
    rows = query_as_tenant(tenant_id, "SELECT tenant_id FROM orders")  # no WHERE, on purpose
    assert len(rows) == ORDERS_PER_TENANT
    assert {row.tenant_id for row in rows} == {tenant_id}


def test_another_tenants_row_is_invisible_even_by_its_id() -> None:
    # Guessing or leaking an id is not enough: the row does not exist for this tenant.
    beta_order = seed_id("beta-bazaar", "order", "ORD-1001")
    assert query_as_tenant(ALPHA, "SELECT id FROM orders WHERE id = :id", id=beta_order) == []


def test_a_tenant_cannot_write_rows_for_another_tenant() -> None:
    async def write(engine: AsyncEngine) -> None:
        async with tenant_session(create_session_factory(engine), ALPHA) as session:
            await session.execute(audit_entry(BETA))

    with pytest.raises(ProgrammingError, match=RLS_VIOLATION):
        as_runtime_role(write)


def test_tenant_context_ends_with_its_transaction() -> None:
    # One pooled connection, used twice. The second transaction must not inherit the
    # first one's tenant, and the '' left behind must not break the uuid cast (NULLIF).
    count_orders = text("SELECT count(*), pg_backend_pid() FROM orders")

    async def two_transactions(engine: AsyncEngine) -> tuple[int, int, bool]:
        async with tenant_session(create_session_factory(engine), ALPHA) as session:
            inside, first_pid = (await session.execute(count_orders)).one()
        async with engine.connect() as conn:
            after, second_pid = (await conn.execute(count_orders)).one()
        return inside, after, first_pid == second_pid

    result = as_runtime_role(two_transactions, db_pool_size=1, db_max_overflow=0)
    assert result == (ORDERS_PER_TENANT, 0, True)


def test_tenant_session_commits_on_success_and_rolls_back_on_error() -> None:
    marker = {"committed": "rls_commit_probe", "rolled_back": "rls_rollback_probe"}

    async def write_twice(engine: AsyncEngine) -> None:
        sessions = create_session_factory(engine)
        async with tenant_session(sessions, ALPHA) as session:
            await session.execute(audit_entry(ALPHA).values(action=marker["committed"]))
        with pytest.raises(RuntimeError):
            async with tenant_session(sessions, ALPHA) as session:
                await session.execute(audit_entry(ALPHA).values(action=marker["rolled_back"]))
                raise RuntimeError("boom")

    as_runtime_role(write_twice)
    found = query_as_tenant(
        ALPHA,
        "SELECT action FROM audit_log WHERE action = ANY(:actions)",
        actions=list(marker.values()),
    )
    assert [row.action for row in found] == [marker["committed"]]
