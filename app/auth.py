import asyncio
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import cache
from typing import Self

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from db.models import UserRole

ALGORITHM = "HS256"
ISSUER = "order-ops-copilot"
AUDIENCE = "order-ops-api"


class Scope(StrEnum):
    ORDERS_READ = "orders:read"
    SHIPMENTS_READ = "shipments:read"
    POLICIES_READ = "policies:read"
    REFUNDS_ELIGIBILITY = "refunds:eligibility"
    REFUNDS_REQUEST = "refunds:request"
    REFUNDS_APPROVE = "refunds:approve"
    EMAIL_SEND = "email:send"


# A new scope is granted to nobody until it is added here by name.
ROLE_SCOPES: dict[UserRole, frozenset[Scope]] = {
    UserRole.BUYER: frozenset(
        {
            Scope.ORDERS_READ,
            Scope.SHIPMENTS_READ,
            Scope.POLICIES_READ,
            Scope.REFUNDS_ELIGIBILITY,
            Scope.REFUNDS_REQUEST,
            Scope.EMAIL_SEND,
        }
    ),
    UserRole.SUPPORT: frozenset(
        {
            Scope.ORDERS_READ,
            Scope.SHIPMENTS_READ,
            Scope.POLICIES_READ,
            Scope.REFUNDS_ELIGIBILITY,
            Scope.REFUNDS_REQUEST,
            Scope.REFUNDS_APPROVE,
            Scope.EMAIL_SEND,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: UserRole
    scopes: frozenset[Scope]

    @classmethod
    def for_user(cls, user_id: uuid.UUID, tenant_id: uuid.UUID, role: UserRole) -> Self:
        return cls(user_id=user_id, tenant_id=tenant_id, role=role, scopes=ROLE_SCOPES[role])


_hasher = PasswordHasher()


@cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(32))


def _verify_blocking(password_hash: str | None, password: str) -> bool:
    known_user = password_hash is not None
    try:
        _hasher.verify(password_hash if password_hash is not None else _dummy_hash(), password)
    except (VerificationError, InvalidHashError):
        return False
    return known_user


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    return await asyncio.to_thread(_verify_blocking, password_hash, password)


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


class TokenError(Exception):
    """The token cannot be trusted. The reason is for logs: clients only ever see a 401."""


class _Claims(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    sub: uuid.UUID
    tenant_id: uuid.UUID
    role: UserRole
    scopes: frozenset[Scope]


def issue_access_token(
    context: AuthContext, *, secret: SecretStr, ttl: timedelta, now: datetime | None = None
) -> str:
    issued_at = now if now is not None else datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(context.user_id),
        "tenant_id": str(context.tenant_id),
        "role": context.role.value,
        "scopes": sorted(context.scopes),
        "iat": issued_at,
        "exp": issued_at + ttl,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, secret.get_secret_value(), algorithm=ALGORITHM)


def verify_access_token(token: str, *, secret: SecretStr) -> AuthContext:
    try:
        payload = jwt.decode(
            token,
            secret.get_secret_value(),
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["iss", "aud", "sub", "iat", "exp", "jti"]},
        )

        claims = _Claims.model_validate(payload)
    except (jwt.PyJWTError, ValidationError) as exc:
        raise TokenError(type(exc).__name__) from exc
    if not claims.scopes <= ROLE_SCOPES[claims.role]:
        raise TokenError("scopes exceed the role")
    return AuthContext(
        user_id=claims.sub, tenant_id=claims.tenant_id, role=claims.role, scopes=claims.scopes
    )
