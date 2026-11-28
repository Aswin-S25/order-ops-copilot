"""The HTTP side of auth that needs no database: /auth/me and login input validation."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.auth import AuthContext, issue_access_token
from app.main import create_app
from db.models import UserRole
from tests.support import make_settings

SETTINGS = make_settings()
SUPPORT = AuthContext.for_user(uuid.UUID(int=7), uuid.UUID(int=1), UserRole.SUPPORT)


def token_for(context: AuthContext, now: datetime | None = None) -> str:
    return issue_access_token(
        context, secret=SETTINGS.jwt_secret, ttl=timedelta(minutes=15), now=now
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(SETTINGS)) as client:
        yield client


def test_me_describes_the_caller_from_the_token(client: TestClient) -> None:
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token_for(SUPPORT)}"})
    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(SUPPORT.user_id),
        "tenant_id": str(SUPPORT.tenant_id),
        "role": "support",
        "scopes": sorted(SUPPORT.scopes),
    }


A_DAY_AGO = datetime.now(UTC) - timedelta(days=1)
OTHER_KEY = SecretStr("a-different-signing-key-entirely-0123456789")


@pytest.mark.security
@pytest.mark.parametrize(
    "authorization",
    [
        pytest.param(None, id="no-header"),
        pytest.param("Basic YXNoYTpwYXNzd29yZA==", id="basic-scheme"),
        pytest.param("Bearer not-a-token", id="garbage"),
        pytest.param(f"Bearer {token_for(SUPPORT, now=A_DAY_AGO)}", id="expired"),
        pytest.param(
            "Bearer " + issue_access_token(SUPPORT, secret=OTHER_KEY, ttl=timedelta(minutes=15)),
            id="wrong-key",
        ),
    ],
)
def test_every_rejected_token_gets_the_same_401(
    client: TestClient, authorization: str | None
) -> None:
    headers = {"Authorization": authorization} if authorization else {}
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    # Same body whatever went wrong: the reason is in the server log only.
    assert {**response.json()["error"], "request_id": None} == {
        "code": "UNAUTHORIZED",
        "message": "Not authenticated.",
        "request_id": None,
    }


@pytest.mark.security
def test_a_rejected_token_is_logged_by_reason_never_by_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    expired = token_for(SUPPORT, now=A_DAY_AGO)
    with TestClient(create_app(SETTINGS)) as client:  # built here so capsys sees its logs
        client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    logs = capsys.readouterr().out
    assert "ExpiredSignatureError" in logs
    assert expired not in logs


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"tenant_slug": "alpha-market", "email": "asha@example.com"}, id="no-pw"),
        pytest.param(
            {
                "tenant_slug": "alpha-market",
                "email": "asha@example.com",
                "password": "leak-canary-password",
                "role": "support",
            },
            id="extra-field",
        ),
        pytest.param(
            {"tenant_slug": "alpha-market", "email": "a@example.com", "password": "x" * 1025},
            id="password-too-long",
        ),
    ],
)
def test_malformed_login_bodies_are_rejected_before_any_lookup(
    client: TestClient, body: dict[str, str]
) -> None:
    response = client.post("/auth/login", json=body)
    assert response.status_code == 422
    assert "leak-canary-password" not in response.text
