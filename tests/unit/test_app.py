import json
import re
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.config import Settings
from app.errors import NotFoundError
from app.main import create_app


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "database_url": "postgresql+asyncpg://u:p@127.0.0.1:5433/db",
        "redis_url": "redis://127.0.0.1:6379/0",
        "openai_api_key": "sk-test",
        "openai_model": "test-model",
        **overrides,
    }
    return Settings(_env_file=None, **values)


class Item(BaseModel):
    name: str
    quantity: int


def build_app() -> FastAPI:
    app = create_app(make_settings())

    @app.get("/_test/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/_test/not-found")
    async def not_found() -> None:
        raise NotFoundError("Order not found")

    @app.post("/_test/items")
    async def create_item(item: Item) -> Item:
        return item

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app())


def test_generates_request_id_when_absent(client: TestClient) -> None:
    response = client.get("/_test/ok")
    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


def test_propagates_valid_incoming_request_id(client: TestClient) -> None:
    response = client.get("/_test/ok", headers={"X-Request-ID": "client-abc.123"})
    assert response.headers["X-Request-ID"] == "client-abc.123"


@pytest.mark.parametrize("bad_id", ["has space", "a" * 65, "semi;colon"])
def test_replaces_invalid_incoming_request_id(client: TestClient, bad_id: str) -> None:
    response = client.get("/_test/ok", headers={"X-Request-ID": bad_id})
    assert response.headers["X-Request-ID"] != bad_id
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


def test_app_error_uses_envelope(client: TestClient) -> None:
    response = client.get("/_test/not-found")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["message"] == "Order not found"
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_unknown_route_uses_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_keeps_allow_header(client: TestClient) -> None:
    response = client.delete("/_test/ok")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert "GET" in response.headers["Allow"]


def test_validation_error_does_not_echo_input(client: TestClient) -> None:
    response = client.post("/_test/items", json={"name": "x", "quantity": "not-a-number"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["loc"] == ["body", "quantity"]
    assert "not-a-number" not in response.text


def test_unhandled_exception_returns_safe_500(client: TestClient) -> None:
    response = client.get("/_test/boom")
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert "secret internal detail" not in response.text


def test_access_log_is_json_with_request_id(capsys: pytest.CaptureFixture[str]) -> None:
    # Build the app inside the test so logging writes to pytest's captured stdout.
    client = TestClient(build_app())
    client.get("/_test/ok", headers={"X-Request-ID": "trace-me-1"})

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    completed = [r for r in records if r["event"] == "request_completed"]
    assert completed, records
    assert completed[-1]["request_id"] == "trace-me-1"
    assert completed[-1]["status"] == 200
    assert completed[-1]["path"] == "/_test/ok"
    assert completed[-1]["logger"] == "app.request"
