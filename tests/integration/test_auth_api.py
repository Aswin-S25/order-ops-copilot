"""Login against real Postgres, as the runtime role, under RLS."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import auth_api
from app.auth import needs_rehash
from app.main import create_app
from db.engine import create_engine
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

PASSWORD = "auth-test-password"
ALPHA, BETA = seed_id("alpha-market"), seed_id("beta-bazaar")


def set_password_hash(tenant_id: Any, handle: str, password_hash: str) -> None:
    async def run() -> None:
        engine = create_engine(integration_settings())
        try:
            async with tenant_session(create_session_factory(engine), tenant_id) as session:
                await session.execute(
                    text("UPDATE users SET password_hash = :hash WHERE email = :email"),
                    {"hash": password_hash, "email": f"{handle}@example.com"},
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def stored_hash(tenant_id: Any, handle: str) -> str:
    rows = query_as_tenant(
        tenant_id,
        "SELECT password_hash FROM users WHERE email = :email",
        email=f"{handle}@example.com",
    )
    assert len(rows) == 1
    return rows[0].password_hash


@pytest.fixture(scope="module", autouse=True)
def seeded_test_database() -> None:
    command.upgrade(alembic_config(owner_test_url()), "head")

    async def run() -> None:
        await empty_test_database()
        engine = create_engine(integration_settings())
        try:
            await seed(engine, password=PASSWORD, now=datetime.now(UTC))
            # Beta's vikram is deactivated; Alpha's vikram, same password, stays active.
            async with tenant_session(create_session_factory(engine), BETA) as session:
                await session.execute(
                    text("UPDATE users SET is_active = false WHERE email = 'vikram@example.com'")
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app(integration_settings())) as client:
        yield client


def login(client: TestClient, slug: str, email: str, password: str = PASSWORD) -> Any:
    return client.post(
        "/auth/login", json={"tenant_slug": slug, "email": email, "password": password}
    )


def me(client: TestClient, token: str) -> dict[str, Any]:
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    return response.json()


def test_login_returns_a_token_that_identifies_the_user(client: TestClient) -> None:
    response = login(client, "alpha-market", "asha@example.com")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert (body["token_type"], body["expires_in"]) == ("bearer", 900)
    caller = me(client, body["access_token"])
    assert caller["user_id"] == str(seed_id("alpha-market", "user", "asha"))
    assert (caller["tenant_id"], caller["role"]) == (str(ALPHA), "buyer")


@pytest.mark.security
def test_the_same_email_in_another_tenant_is_another_account(client: TestClient) -> None:
    callers = [
        me(client, login(client, slug, "asha@example.com").json()["access_token"])
        for slug in ("alpha-market", "beta-bazaar")
    ]
    assert [caller["tenant_id"] for caller in callers] == [str(ALPHA), str(BETA)]
    assert callers[0]["user_id"] != callers[1]["user_id"]


def test_email_and_tenant_slug_are_normalised(client: TestClient) -> None:
    assert login(client, " Alpha-Market ", "  ASHA@Example.com ").status_code == 200


@pytest.mark.security
@pytest.mark.parametrize(
    ("slug", "email", "password"),
    [
        pytest.param("alpha-market", "asha@example.com", "wrong-password", id="wrong-password"),
        pytest.param("alpha-market", "nobody@example.com", PASSWORD, id="unknown-email"),
        pytest.param("gamma-goods", "asha@example.com", PASSWORD, id="unknown-tenant"),
        pytest.param("beta-bazaar", "vikram@example.com", PASSWORD, id="inactive-account"),
    ],
)
def test_every_login_failure_looks_and_costs_the_same(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, slug: str, email: str, password: str
) -> None:
    checks: list[str | None] = []
    real_verify = auth_api.verify_password

    async def counting_verify(password_hash: str | None, password: str) -> bool:
        checks.append(password_hash)
        return await real_verify(password_hash, password)

    monkeypatch.setattr(auth_api, "verify_password", counting_verify)
    response = login(client, slug, email, password)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert {**response.json()["error"], "request_id": None} == {
        "code": "UNAUTHORIZED",
        "message": "Invalid credentials.",
        "request_id": None,
    }
    # Exactly one Argon2 check on every path, so timing does not tell them apart either.
    assert len(checks) == 1


def test_an_inactive_accounts_twin_can_log_in(client: TestClient) -> None:
    # Control for the inactive case above: same password, only is_active differs.
    assert login(client, "alpha-market", "vikram@example.com").status_code == 200


def test_an_outdated_hash_is_upgraded_on_login(client: TestClient) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash(PASSWORD)
    set_password_hash(BETA, "ravi", weak)
    assert login(client, "beta-bazaar", "ravi@example.com").status_code == 200
    upgraded = stored_hash(BETA, "ravi")
    assert upgraded != weak
    assert not needs_rehash(upgraded)
    assert login(client, "beta-bazaar", "ravi@example.com").status_code == 200


def test_an_upgrade_never_overwrites_a_password_changed_meanwhile(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash(PASSWORD)
    changed = PasswordHasher().hash("a-brand-new-password")
    set_password_hash(BETA, "meera", weak)
    real_hash = auth_api.hash_password

    async def password_changes_while_hashing(password: str) -> str:
        await asyncio.to_thread(set_password_hash, BETA, "meera", changed)
        return await real_hash(password)

    monkeypatch.setattr(auth_api, "hash_password", password_changes_while_hashing)
    assert login(client, "beta-bazaar", "meera@example.com").status_code == 200
    assert stored_hash(BETA, "meera") == changed


@pytest.mark.security
def test_login_logs_never_contain_the_email_or_password(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with TestClient(create_app(integration_settings())) as client:
        login(client, "alpha-market", "asha@example.com")
        login(client, "alpha-market", "asha@example.com", "wrong-canary-password")
    logs = capsys.readouterr().out
    assert "login_succeeded" in logs
    assert "login_failed" in logs
    for secret in (PASSWORD, "wrong-canary-password", "asha@example.com"):
        assert secret not in logs
