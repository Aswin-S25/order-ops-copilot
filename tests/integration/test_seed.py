"""The seed against real Postgres (orderops_test), run as the runtime role."""

import asyncio
from datetime import UTC, datetime

import pytest
from alembic import command
from argon2 import PasswordHasher
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from db.engine import create_engine
from db.seed import TENANTS, seed, seed_id
from db.session import create_session_factory, tenant_session
from tests.support import (
    alembic_config,
    empty_test_database,
    integration_settings,
    owner_test_url,
    query_as_tenant,
)

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


def test_first_run_inserts_everything(seed_runs: SeedRuns) -> None:
    assert seed_runs[0] == EXPECTED


def test_second_run_inserts_nothing(seed_runs: SeedRuns) -> None:
    assert seed_runs[1] == dict.fromkeys(EXPECTED, 0)


def test_one_email_is_two_separate_accounts(seed_runs: SeedRuns) -> None:
    # Each tenant sees only its own account, so look inside each tenant in turn.
    ids = [
        row.id
        for slug in TENANTS
        for row in query_as_tenant(
            seed_id(slug), "SELECT id FROM users WHERE email = :email", email="asha@example.com"
        )
    ]
    assert len(set(ids)) == 2


def test_passwords_are_stored_as_argon2id_hashes(seed_runs: SeedRuns) -> None:
    hashes = [
        row.password_hash
        for slug in TENANTS
        for row in query_as_tenant(seed_id(slug), "SELECT password_hash FROM users")
    ]
    # Without this count the loop below passes on zero rows, which is exactly what an
    # unscoped query returns under RLS.
    assert len(hashes) == EXPECTED["users"]
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
        sessions = create_session_factory(engine)
        try:
            async with tenant_session(sessions, tenant_id) as session:
                await session.execute(
                    text("DELETE FROM users WHERE id = :id"),
                    {"id": seed_id("alpha-market", "user", "meera")},
                )
                await session.execute(text(impostor), {"tenant_id": tenant_id})
            with pytest.raises(IntegrityError, match="uq_users_tenant_id_email"):
                await seed(engine, password=PASSWORD, now=NOW)
        finally:
            async with tenant_session(sessions, tenant_id) as session:  # restore the seed
                await session.execute(
                    text("DELETE FROM users WHERE email = 'meera@example.com' AND id <> :id"),
                    {"id": seed_id("alpha-market", "user", "meera")},
                )
            await seed(engine, password=PASSWORD, now=NOW)
            await engine.dispose()

    asyncio.run(run())
