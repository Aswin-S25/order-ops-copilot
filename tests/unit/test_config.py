import pytest
from pydantic import ValidationError

from app.config import MigrationSettings, Settings

VALID_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://app_user:db-secret@localhost:5432/orderops",
    "REDIS_URL": "redis://localhost:6379/0",
    "OPENAI_API_KEY": "sk-test-not-a-real-key",
    "OPENAI_MODEL": "test-model",
    "JWT_SECRET": "jwt-secret-not-a-real-signing-key",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    # Hermetic: values from the developer's shell must not change test outcomes.
    for key in ("ENV", "LOG_LEVEL", "ACCESS_TOKEN_TTL_SECONDS"):
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
    assert "jwt-secret-not-a-real-signing-key" not in text


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


def test_jwt_secret_is_required(env: pytest.MonkeyPatch) -> None:
    env.delenv("JWT_SECRET")
    with pytest.raises(ValidationError):
        load()


def test_short_jwt_secret_is_rejected_without_leaking_it(env: pytest.MonkeyPatch) -> None:
    env.setenv("JWT_SECRET", "too-short-to-sign")
    with pytest.raises(ValidationError) as exc_info:
        load()
    assert "too-short-to-sign" not in str(exc_info.value)


@pytest.mark.parametrize("seconds", ["59", "3601"])
def test_access_token_lifetime_is_bounded(env: pytest.MonkeyPatch, seconds: str) -> None:
    # Too short and every request races its expiry; too long and a stolen token stays
    # useful for hours, because tokens cannot be revoked (ADR-0004).
    env.setenv("ACCESS_TOKEN_TTL_SECONDS", seconds)
    with pytest.raises(ValidationError):
        load()


@pytest.mark.parametrize(
    "variable",
    ["DB_CONNECT_TIMEOUT_SECONDS", "DB_POOL_TIMEOUT_SECONDS", "HEALTH_CHECK_TIMEOUT_SECONDS"],
)
def test_zero_timeouts_are_rejected(env: pytest.MonkeyPatch, variable: str) -> None:
    # A zero timeout passes a naive check but makes every connection attempt fail.
    env.setenv(variable, "0")
    with pytest.raises(ValidationError):
        load()


def test_runtime_settings_never_carry_the_owner_credential() -> None:
    # ADR-0003: the API and workers run as app_user. Even when DATABASE_OWNER_URL is in
    # the environment, the runtime Settings object has no field that could load it.
    assert "database_owner_url" not in Settings.model_fields


def test_migration_settings_reject_sync_driver_without_leaking_password(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("DATABASE_OWNER_URL", "postgresql://app_owner:owner-secret@127.0.0.1:5433/db")
    with pytest.raises(ValidationError) as exc_info:
        MigrationSettings(_env_file=None)
    assert "owner-secret" not in str(exc_info.value)
