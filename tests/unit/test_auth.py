"""Passwords, access tokens and AuthContext (ADR-0004). No HTTP, no database."""

import asyncio
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from argon2 import PasswordHasher
from pydantic import SecretStr

from app import auth
from app.auth import (
    AUDIENCE,
    ISSUER,
    ROLE_SCOPES,
    AuthContext,
    Scope,
    TokenError,
    hash_password,
    issue_access_token,
    needs_rehash,
    verify_access_token,
    verify_password,
)
from db.models import UserRole

SECRET = SecretStr("unit-test-signing-key-" * 3)  # 66 bytes: long enough even for HS512
TTL = timedelta(minutes=15)
TENANT = uuid.UUID(int=1)
BUYER = AuthContext.for_user(uuid.UUID(int=2), TENANT, UserRole.BUYER)
SUPPORT = AuthContext.for_user(uuid.UUID(int=3), TENANT, UserRole.SUPPORT)
PASSWORD = "correct horse battery staple"


# --- Scopes ------------------------------------------------------------------------------


@pytest.mark.security
def test_scopes_per_role_match_the_architecture_table() -> None:
    # Written out in full on purpose: changing who may do what must be a deliberate edit
    # here as well as in app/auth.py.
    everyone = {
        Scope.ORDERS_READ,
        Scope.SHIPMENTS_READ,
        Scope.POLICIES_READ,
        Scope.REFUNDS_ELIGIBILITY,
        Scope.REFUNDS_REQUEST,
        Scope.EMAIL_SEND,
    }
    assert ROLE_SCOPES == {
        UserRole.BUYER: everyone,
        UserRole.SUPPORT: everyone | {Scope.REFUNDS_APPROVE},
    }
    assert SUPPORT.scopes == ROLE_SCOPES[UserRole.SUPPORT]


# --- Passwords ---------------------------------------------------------------------------


class SpyHasher(PasswordHasher):
    """Records, for every hash and verify call, whether it ran on the main thread."""

    def __init__(self) -> None:
        super().__init__()
        self.hashed: list[bool] = []
        self.verified: list[bool] = []

    def hash(self, *args: Any, **kwargs: Any) -> str:
        self.hashed.append(threading.current_thread() is threading.main_thread())
        return super().hash(*args, **kwargs)

    def verify(self, *args: Any, **kwargs: Any) -> Any:
        self.verified.append(threading.current_thread() is threading.main_thread())
        return super().verify(*args, **kwargs)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> SpyHasher:
    hasher = SpyHasher()
    monkeypatch.setattr(auth, "_hasher", hasher)
    return hasher


def test_the_right_password_verifies_and_a_wrong_one_does_not() -> None:
    async def run() -> tuple[bool, bool]:
        stored = await hash_password(PASSWORD)
        return await verify_password(stored, PASSWORD), await verify_password(stored, "Correct")

    assert asyncio.run(run()) == (True, False)


@pytest.mark.security
def test_a_corrupt_stored_hash_fails_closed() -> None:
    assert asyncio.run(verify_password("not-an-argon2-hash", PASSWORD)) is False


@pytest.mark.security
def test_an_unknown_user_costs_a_full_verification(spy: SpyHasher) -> None:
    # Returning early would answer "no such email" faster than "wrong password".
    assert asyncio.run(verify_password(None, PASSWORD)) is False
    assert len(spy.verified) == 1


@pytest.mark.security
def test_an_unknown_user_is_rejected_even_if_the_dummy_hash_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The verdict for an unknown user must not depend on what the dummy hash contains.
    monkeypatch.setattr(auth, "_dummy_hash", lambda: PasswordHasher().hash(PASSWORD))
    assert asyncio.run(verify_password(None, PASSWORD)) is False


def test_password_work_runs_off_the_event_loop(spy: SpyHasher) -> None:
    async def run() -> None:
        await verify_password(await hash_password(PASSWORD), PASSWORD)

    asyncio.run(run())
    assert (spy.hashed, spy.verified) == ([False], [False])


def test_hashes_made_with_weaker_settings_need_a_rehash() -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash(PASSWORD)
    current = asyncio.run(hash_password(PASSWORD))
    assert (needs_rehash(weak), needs_rehash(current)) == (True, False)


# --- Access tokens -----------------------------------------------------------------------


def forge(*, key: str | None = None, algorithm: str = "HS256", **changes: Any) -> str:
    """A token for BUYER, built by hand. `changes` override claims; None removes one."""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(BUYER.user_id),
        "tenant_id": str(BUYER.tenant_id),
        "role": "buyer",
        "scopes": sorted(BUYER.scopes),
        "iat": now,
        "exp": now + TTL,
        "jti": "forged",
        **changes,
    }
    payload = {name: value for name, value in claims.items() if value is not None}
    if algorithm == "none":
        return jwt.encode(payload, None, algorithm="none")
    return jwt.encode(payload, key or SECRET.get_secret_value(), algorithm=algorithm)


def test_a_token_round_trips_to_the_same_context() -> None:
    for context in (BUYER, SUPPORT):
        token = issue_access_token(context, secret=SECRET, ttl=TTL)
        assert verify_access_token(token, secret=SECRET) == context


def test_a_token_carries_exactly_the_documented_claims() -> None:
    now = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
    first, second = (
        jwt.decode(
            issue_access_token(BUYER, secret=SECRET, ttl=TTL, now=now),
            options={"verify_signature": False},
        )
        for _ in range(2)
    )
    # Exactly these: nothing personal (no email), nothing the server must not reveal.
    assert first == {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(BUYER.user_id),
        "tenant_id": str(TENANT),
        "role": "buyer",
        "scopes": sorted(ROLE_SCOPES[UserRole.BUYER]),
        "iat": int(now.timestamp()),
        "exp": int((now + TTL).timestamp()),
        "jti": first["jti"],
    }
    assert first["jti"] != second["jti"]


def test_the_forging_helper_makes_valid_tokens() -> None:
    # Without this control, a broken forge() would make every rejection below pass.
    assert verify_access_token(forge(), secret=SECRET) == BUYER


ONE_HOUR_AGO = datetime.now(UTC) - timedelta(hours=1)
IN_ONE_HOUR = datetime.now(UTC) + timedelta(hours=1)


@pytest.mark.security
@pytest.mark.parametrize(
    "token",
    [
        pytest.param(forge(key="a-different-signing-key-" * 3), id="wrong-secret"),
        pytest.param(forge(algorithm="none"), id="alg-none"),
        pytest.param(forge(algorithm="HS512"), id="other-algorithm"),
        pytest.param(forge(exp=ONE_HOUR_AGO, iat=ONE_HOUR_AGO - TTL), id="expired"),
        pytest.param(forge(iat=IN_ONE_HOUR, exp=IN_ONE_HOUR + TTL), id="issued-in-future"),
        pytest.param(forge(aud="another-service"), id="wrong-audience"),
        pytest.param(forge(iss="someone-else"), id="wrong-issuer"),
        pytest.param(forge(exp=None), id="no-expiry"),
        pytest.param(forge(jti=None), id="no-token-id"),
        pytest.param(forge(tenant_id=None), id="no-tenant"),
        pytest.param(forge(sub="asha@example.com"), id="subject-not-a-uuid"),
        pytest.param(forge(role="admin"), id="unknown-role"),
        pytest.param(forge(scopes=["orders:read", "everything:*"]), id="unknown-scope"),
        pytest.param(
            forge(scopes=sorted(ROLE_SCOPES[UserRole.SUPPORT])), id="scopes-beyond-the-role"
        ),
        pytest.param("not-a-token", id="garbage"),
    ],
)
def test_untrustworthy_tokens_are_rejected(token: str) -> None:
    with pytest.raises(TokenError):
        verify_access_token(token, secret=SECRET)


@pytest.mark.security
def test_a_token_edited_after_signing_is_rejected() -> None:
    # Keep the buyer's real signature, swap in a payload that says "support".
    header, _, signature = issue_access_token(BUYER, secret=SECRET, ttl=TTL).split(".")
    promoted = forge(role="support", scopes=sorted(ROLE_SCOPES[UserRole.SUPPORT])).split(".")[1]
    with pytest.raises(TokenError):
        verify_access_token(f"{header}.{promoted}.{signature}", secret=SECRET)
