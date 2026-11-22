import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from tests.support import make_settings


def unreachable_settings() -> Settings:
    # Port 1 on localhost: nothing listens there, so connections are refused at once.
    return make_settings(
        database_url="postgresql+asyncpg://u:p@127.0.0.1:1/db",
        redis_url="redis://127.0.0.1:1/0",
        health_check_timeout_seconds=1.0,
    )


def test_app_starts_even_when_dependencies_are_down() -> None:
    # `with` runs the lifespan (startup + shutdown); a crash here would raise.
    with TestClient(create_app(unreachable_settings())) as client:
        assert client.get("/health/live").status_code == 200


def test_live_does_not_check_dependencies() -> None:
    with TestClient(create_app(unreachable_settings())) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_503_without_leaking_details() -> None:
    with TestClient(create_app(unreachable_settings())) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    # Exact equality: no error messages, hostnames or ports in the response body.
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgres": "error", "redis": "error"},
    }


def test_failed_readiness_logs_do_not_contain_credentials(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = unreachable_settings().model_copy(
        update={"database_url": SecretStr("postgresql+asyncpg://u:leak-canary@127.0.0.1:1/db")}
    )
    with TestClient(create_app(settings)) as client:
        client.get("/health/ready")
    logs = capsys.readouterr().out
    assert "readiness_check_failed" in logs  # the failure IS logged...
    assert "leak-canary" not in logs  # ...but never with the password
