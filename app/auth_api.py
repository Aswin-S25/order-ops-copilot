import uuid
from datetime import timedelta
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import (
    AuthContext,
    Scope,
    hash_password,
    issue_access_token,
    needs_rehash,
    verify_password,
)
from app.dependencies import AppSettingsDep, AuthDep, DbSessionsDep
from app.errors import AuthenticationError
from db.models import Tenant, User, UserRole
from db.session import tenant_session

router = APIRouter(prefix="/auth", tags=["auth"])
logger = structlog.get_logger("app.auth")

Normalised = StringConstraints(strip_whitespace=True, to_lower=True, min_length=1)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_slug: Annotated[str, Normalised, Field(max_length=63)]
    email: Annotated[str, Normalised, Field(max_length=320)]
    password: SecretStr = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int


class MeResponse(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: UserRole
    scopes: list[Scope]


async def authenticate(
    sessions: async_sessionmaker[AsyncSession], *, tenant_slug: str, email: str, password: str
) -> AuthContext | None:

    async with sessions() as session:
        tenant_id = await session.scalar(select(Tenant.id).where(Tenant.slug == tenant_slug))
    user = None
    if tenant_id is not None:
        async with tenant_session(sessions, tenant_id) as session:
            user = (
                await session.execute(
                    select(User.id, User.password_hash, User.role, User.is_active).where(
                        User.email == email
                    )
                )
            ).one_or_none()

    password_ok = await verify_password(user.password_hash if user else None, password=password)
    if tenant_id is None or user is None or not password_ok or not user.is_active:
        return None
    if needs_rehash(user.password_hash):
        new_hash = await hash_password(password)
        async with tenant_session(sessions, tenant_id) as session:
            await session.execute(
                update(User)
                .where(User.id == user.id, User.password_hash == user.password_hash)
                .values(password_hash=new_hash)
            )
    return AuthContext.for_user(user.id, tenant_id, user.role)


@router.post("/login")
async def login(
    body: LoginRequest, settings: AppSettingsDep, sessions: DbSessionsDep, response: Response
) -> TokenResponse:
    context = await authenticate(
        sessions,
        tenant_slug=body.tenant_slug,
        email=body.email,
        password=body.password.get_secret_value(),
    )

    if context is None:
        logger.info("login_failed", tenant_slug=body.tenant_slug)
        raise AuthenticationError("Invalid credentials.")
    logger.info("login_succeeded", user_id=str(context.user_id), tenant_id=str(context.tenant_id))
    response.headers["Cache-Control"] = "no-store"
    ttl = settings.access_token_ttl_seconds
    return TokenResponse(
        access_token=issue_access_token(
            context, secret=settings.jwt_secret, ttl=timedelta(seconds=ttl)
        ),
        expires_in=ttl,
    )


@router.get("/me")
async def me(auth: AuthDep) -> MeResponse:
    return MeResponse(
        user_id=auth.user_id, tenant_id=auth.tenant_id, role=auth.role, scopes=sorted(auth.scopes)
    )
