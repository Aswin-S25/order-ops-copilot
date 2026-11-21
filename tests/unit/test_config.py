import pytest
from pydantic import ValidationError

from app.config import Settings

VALID_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://app_user:db-secret@localhost:5432/orderops",
    "REDIS_URL": "redis://localhost:6379/0",
    "OPENAI_API_KEY": "sk-test-not-a-real-key",
    "OPENAI_MODEL": "test-model",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    # Hermetic: values from the developer's shell must not change test outcomes.
    for key in ("ENV", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def load() -> Settings:
    # _env_file=None: tests must never read the developer's real .env
    return Settings(_env_file=None)


def test_loads_valid_environment(env: pytest.MonkeyPatch) -> None:
    settings = load()
    assert settings.env == "dev"
    assert settings.openai_model == "test-model"
    assert settings.database_url.get_secret_value().endswith("/orderops")


def test_secrets_are_masked_in_repr(env: pytest.MonkeyPatch) -> None:
    text = repr(load())
    assert "db-secret" not in text
    assert "sk-test-not-a-real-key" not in text


def test_rejects_sync_driver_without_leaking_password(env: pytest.MonkeyPatch) -> None:
    env.setenv("DATABASE_URL", "postgresql://app_user:db-secret@localhost:5432/orderops")
    with pytest.raises(ValidationError) as exc_info:
        load()
    assert "db-secret" not in str(exc_info.value)


def test_openai_model_is_required(env: pytest.MonkeyPatch) -> None:
    env.delenv("OPENAI_MODEL")
    with pytest.raises(ValidationError):
        load()


def test_settings_are_immutable(env: pytest.MonkeyPatch) -> None:
    settings = load()
    with pytest.raises(ValidationError):
        settings.log_level = "DEBUG"
