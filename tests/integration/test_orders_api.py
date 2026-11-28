"""GET /orders/{id}: who may see which order (roadmap Phase 2 exit criteria)."""

import asyncio
import base64
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthContext
from app.main import create_app
from db.engine import create_engine
from db.models import UserRole
from db.seed import seed_id
from db.session import create_session_factory, tenant_session
from services import orders
from tests.support import integration_settings, seed_test_database

pytestmark = [pytest.mark.integration, pytest.mark.security]

PASSWORD = "orders-test-password"
ALPHA_1001 = seed_id("alpha-market", "order", "ORD-1001")  # asha's
ALPHA_1004 = seed_id("alpha-market", "order", "ORD-1004")  # ravi's
BETA_1001 = seed_id("beta-bazaar", "order", "ORD-1001")


@pytest.fixture(scope="module", autouse=True)
def seeded_test_database() -> None:
    seed_test_database(PASSWORD)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app(integration_settings())) as client:
        yield client


def login(client: TestClient, slug: str, handle: str) -> str:
    response = client.post(
        "/auth/login",
        json={"tenant_slug": slug, "email": f"{handle}@example.com", "password": PASSWORD},
    )
    return str(response.json()["access_token"])


def get_order(client: TestClient, order_id: uuid.UUID, as_user: tuple[str, str] | None) -> Any:
    headers = {}
    if as_user is not None:
        headers["Authorization"] = f"Bearer {login(client, *as_user)}"
    return client.get(f"/orders/{order_id}", headers=headers)


def test_a_buyer_reads_their_own_order(client: TestClient) -> None:
    response = get_order(client, ALPHA_1001, ("alpha-market", "asha"))
    order = response.json()
    # The exact contract: a field that goes missing fails here, and so does one added by accident.
    assert set(order) == {
        "id",
        "order_number",
        "buyer_id",
        "seller_name",
        "status",
        "total",
        "placed_at",
        "delivered_at",
        "items",
    }
    assert order["order_number"] == "ORD-1001"
    assert order["status"] == "delivered"
    assert order["delivered_at"] is not None
    assert order["order_number"] == "ORD-1001"
    assert order["buyer_id"] == str(seed_id("alpha-market", "user", "asha"))
    assert order["total"] == {"amount_minor": 2 * 1_299_00 + 899_00, "currency": "INR"}
    assert order["items"] == [
        {
            "sku": "DUP-014",
            "name": "Silk dupatta",
            "quantity": 1,
            "unit_price": {"amount_minor": 899_00, "currency": "INR"},
        },
        {
            "sku": "KUR-001",
            "name": "Cotton kurta",
            "quantity": 2,
            "unit_price": {"amount_minor": 1_299_00, "currency": "INR"},
        },
    ]


@pytest.mark.parametrize("order_id", [ALPHA_1001, ALPHA_1004], ids=["asha's", "ravi's"])
def test_support_reads_any_order_in_its_tenant(client: TestClient, order_id: uuid.UUID) -> None:
    assert get_order(client, order_id, ("alpha-market", "meera")).status_code == 200


@pytest.mark.parametrize(
    ("caller", "order_id"),
    [
        pytest.param(("alpha-market", "ravi"), ALPHA_1001, id="another-buyers-order"),
        pytest.param(("beta-bazaar", "asha"), ALPHA_1001, id="same-email-other-tenant"),
        pytest.param(("beta-bazaar", "meera"), ALPHA_1001, id="support-of-another-tenant"),
        pytest.param(("alpha-market", "asha"), uuid.uuid4(), id="no-such-order"),
    ],
)
def test_an_order_the_caller_may_not_see_does_not_exist(
    client: TestClient, caller: tuple[str, str], order_id: uuid.UUID
) -> None:
    response = get_order(client, order_id, caller)
    assert response.status_code == 404
    # Identical to "no such order": the caller cannot even learn that the id is real.
    assert {**response.json()["error"], "request_id": None} == {
        "code": "NOT_FOUND",
        "message": "Order not found.",
        "request_id": None,
    }


def test_an_order_needs_a_token(client: TestClient) -> None:
    assert get_order(client, ALPHA_1001, None).status_code == 401


def test_a_token_edited_to_claim_another_buyer_is_rejected(client: TestClient) -> None:
    # ravi keeps his real signature but rewrites the payload to say he is asha.
    header, payload, signature = login(client, "alpha-market", "ravi").split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["sub"] = str(seed_id("alpha-market", "user", "asha"))
    edited = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()

    def read_asha_order(token: str) -> int:
        url = f"/orders/{ALPHA_1001}"
        return client.get(url, headers={"Authorization": f"Bearer {token}"}).status_code

    # His real token reaches the ownership check (404); the edited one is stopped before it
    # (401). Without the signature check, the edited one would read asha's order (200).
    assert read_asha_order(f"{header}.{payload}.{signature}") == 404
    assert read_asha_order(f"{header}.{edited}.{signature}") == 401


def test_the_service_filters_by_tenant_even_when_rls_would_not() -> None:
    # A session set to Beta (as if a bug passed the wrong tenant) and Alpha's support
    # user asking for Beta's order: RLS would show it, so only the service's own
    # tenant filter can hide it. The second lookup is the control: the row is there.
    alpha_support = AuthContext.for_user(
        seed_id("alpha-market", "user", "meera"), seed_id("alpha-market"), UserRole.SUPPORT
    )
    beta_support = AuthContext.for_user(
        seed_id("beta-bazaar", "user", "meera"), seed_id("beta-bazaar"), UserRole.SUPPORT
    )

    async def run() -> tuple[bool, bool]:
        engine = create_engine(integration_settings())
        try:
            sessions = create_session_factory(engine)
            async with tenant_session(sessions, seed_id("beta-bazaar")) as session:
                wrong = await orders.get_order(session, alpha_support, BETA_1001)
                right = await orders.get_order(session, beta_support, BETA_1001)
        finally:
            await engine.dispose()
        return wrong is None, right is not None

    assert asyncio.run(run()) == (True, True)
