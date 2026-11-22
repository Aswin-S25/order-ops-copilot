"""Needs the Docker Compose stack: `docker compose up -d`."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from db.engine import create_engine
from tests.support import integration_settings

pytestmark = pytest.mark.integration


def test_ready_with_real_postgres_and_redis() -> None:
    with TestClient(create_app(integration_settings())) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready", "checks": {"postgres": "ok", "redis": "ok"}}


def test_engine_connects_as_least_privileged_runtime_role() -> None:
    # Guards ADR-0003: if DATABASE_URL is ever switched to app_owner or the
    # superuser, RLS would be bypassed silently. This test makes it loud.
    async def whoami() -> tuple[str, str, str]:
        engine = create_engine(integration_settings())
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT current_user, current_database(),"
                            " current_setting('application_name')"
                        )
                    )
                ).one()
        finally:
            await engine.dispose()
        return row[0], row[1], row[2]

    assert asyncio.run(whoami()) == ("app_user", "orderops_test", "order-ops-api")
