"""require_scope: 401 for an unknown caller, 403 for a known one without the scope."""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.auth import AuthContext, Scope, issue_access_token
from app.dependencies import require_scope
from app.main import create_app
from db.models import UserRole
from tests.support import make_settings

pytestmark = pytest.mark.security

SETTINGS = make_settings()
TENANT = uuid.UUID(int=1)


def bearer(role: UserRole) -> dict[str, str]:
    context = AuthContext.for_user(uuid.UUID(int=2), TENANT, role)
    token = issue_access_token(context, secret=SETTINGS.jwt_secret, ttl=timedelta(minutes=5))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(SETTINGS)

    # Only support holds refunds:approve, so this route separates the two roles.
    @app.post("/_test/approve")
    async def approve(
        auth: Annotated[AuthContext, Depends(require_scope(Scope.REFUNDS_APPROVE))],
    ) -> dict[str, str]:
        return {"approved_by": str(auth.user_id)}

    with TestClient(app) as client:
        yield client


def test_a_role_with_the_scope_gets_through(client: TestClient) -> None:
    response = client.post("/_test/approve", headers=bearer(UserRole.SUPPORT))
    assert response.status_code == 200
    assert response.json() == {"approved_by": str(uuid.UUID(int=2))}


def test_a_role_without_the_scope_is_forbidden(client: TestClient) -> None:
    response = client.post("/_test/approve", headers=bearer(UserRole.BUYER))
    assert response.status_code == 403
    assert {**response.json()["error"], "request_id": None} == {
        "code": "FORBIDDEN",
        "message": "This account is not allowed to do that.",
        "request_id": None,
    }


def test_an_unknown_caller_is_unauthenticated_not_forbidden(client: TestClient) -> None:
    # 401 comes first: we cannot say what you may do before we know who you are.
    assert client.post("/_test/approve").status_code == 401
