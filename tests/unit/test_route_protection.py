"""Every route needs a token unless it is on the public list: new routes start protected."""

import re
import uuid
from collections.abc import Iterator

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient

from app.main import create_app
from tests.support import make_settings

pytestmark = pytest.mark.security

# The only routes anyone may call without a token. A route added later fails this file
# until it either requires a token or is deliberately added here.
PUBLIC = {
    ("GET", "/health/live"),
    ("GET", "/health/ready"),
    ("POST", "/auth/login"),
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
}

APP = create_app(make_settings())


def every_route() -> set[tuple[str, str]]:
    # The walk FastAPI's own OpenAPI generator uses, so it sees into included routers,
    # but it also yields the routes hidden from the schema.
    routes = set()
    for route in iter_route_contexts(APP.routes):
        assert route.methods is not None, f"not an HTTP route, decide how to protect it: {route}"
        routes |= {(method, route.path) for method in route.methods - {"HEAD"}}
    return routes


ROUTES = every_route()
PROTECTED = sorted(ROUTES - PUBLIC)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as client:
        yield client


def test_the_route_lists_are_real() -> None:
    # A stale public entry would let a future route at that path skip this check, and a
    # walk that missed the included routers would leave nothing to check.
    assert PUBLIC <= ROUTES
    assert {("GET", "/auth/me"), ("GET", "/orders/{order_id}")} <= set(PROTECTED)


@pytest.mark.parametrize(("method", "path"), PROTECTED, ids=[f"{m} {p}" for m, p in PROTECTED])
def test_every_other_route_needs_a_token(client: TestClient, method: str, path: str) -> None:
    url = re.sub(r"\{[^}]+\}", str(uuid.UUID(int=0)), path)
    response = client.request(method, url)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
