"""The seed against real Postgres (orderops_test), run as the runtime role."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from argon2 import PasswordHasher
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from db.engine import create_engine
from db.seed import seed, seed_id
from tests.support import alembic_config, integration_settings, owner_test_url

pytestmark = pytest.mark.integration

PASSWORD = "integration-test-password"
NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)
EXPECTED = {
    "tenants": 2,
    "users": 8,
    "orders": 16,
    "order_items": 18,
    "shipments": 12,
    "shipment_events": 20,
}
SeedRuns = tuple[dict[str, int], dict[str, int]]


async def empty_test_database() -> None:
    engine = create_async_engine(owner_test_url())
    try:
        async with engine.begin() as conn:
            # CASCADE follows every foreign key that leads to tenants: all application data.
            await conn.execute(text("TRUNCATE tenants CASCADE"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def seed_runs() -> SeedRuns:
    """Seed an empty, migrated test database twice, as app_user."""
    command.upgrade(alembic_config(owner_test_url()), "head")

    async def run() -> SeedRuns:
        await empty_test_database()
        engine = create_engine(integration_settings())
        try:
            first = await seed(engine, password=PASSWORD, now=NOW)
            second = await seed(engine, password=PASSWORD, now=NOW)
        finally:
            await engine.dispose()
        return first, second

    return asyncio.run(run())


def query(sql: str, **params: Any) -> list[Any]:
    async def run() -> list[Any]:
        engine = create_engine(integration_settings())
        try:
            async with engine.connect() as conn:
                return list((await conn.execute(text(sql), params)).all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_first_run_inserts_everything(seed_runs: SeedRuns) -> None:
    assert seed_runs[0] == EXPECTED


def test_second_run_inserts_nothing(seed_runs: SeedRuns) -> None:
    assert seed_runs[1] == dict.fromkeys(EXPECTED, 0)


def test_one_email_is_two_separate_accounts(seed_runs: SeedRuns) -> None:
    rows = query("SELECT tenant_id FROM users WHERE email = :email", email="asha@example.com")
    assert len({row.tenant_id for row in rows}) == 2


def test_passwords_are_stored_as_argon2id_hashes(seed_runs: SeedRuns) -> None:
    hashes = [row.password_hash for row in query("SELECT password_hash FROM users")]
    assert len(set(hashes)) == len(hashes)  # a fresh salt per user
    for password_hash in hashes:
        assert password_hash.startswith("$argon2id$")
        assert PasswordHasher().verify(password_hash, PASSWORD)


def test_a_different_row_with_the_same_email_is_not_skipped(seed_runs: SeedRuns) -> None:
    # The seed ignores conflicts on id only. A bare ON CONFLICT DO NOTHING would skip
    # this collision and report success while the seeded account does not exist.
    tenant_id = seed_id("alpha-market")
    impostor = (
        "INSERT INTO users (id, tenant_id, email, password_hash, role, display_name)"
        " VALUES (gen_random_uuid(), :tenant_id, 'meera@example.com', 'x', 'support', 'Other')"
    )

    async def run() -> None:
        engine = create_engine(integration_settings())
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM users WHERE id = :id"),
                    {"id": seed_id("alpha-market", "user", "meera")},
                )
                await conn.execute(text(impostor), {"tenant_id": tenant_id})
            with pytest.raises(IntegrityError, match="uq_users_tenant_id_email"):
                await seed(engine, password=PASSWORD, now=NOW)
        finally:
            async with engine.begin() as conn:  # restore the seeded state
                await conn.execute(
                    text("DELETE FROM users WHERE email = 'meera@example.com' AND id <> :id"),
                    {"id": seed_id("alpha-market", "user", "meera")},
                )
            await seed(engine, password=PASSWORD, now=NOW)
            await engine.dispose()

    asyncio.run(run())
