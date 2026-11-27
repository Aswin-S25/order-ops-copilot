from collections.abc import Awaitable, Callable
from typing import Annotated

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth import AuthContext, Scope, TokenError, verify_access_token
from app.config import Settings
from app.errors import AuthenticationError, ForbiddenError

logger = structlog.get_logger("app.auth")


def get_app_settings(request: Request) -> Settings:
    return request.state.settings


def get_db_engine(request: Request) -> AsyncEngine:
    return request.state.db_engine


def get_db_sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.state.db_sessions


def get_redis(request: Request) -> Redis:
    return request.state.redis


AppSettingsDep = Annotated[Settings, Depends(get_app_settings)]
DbEngineDep = Annotated[AsyncEngine, Depends(get_db_engine)]
DbSessionsDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_db_sessions)]
RedisDep = Annotated[Redis, Depends(get_redis)]

_bearer = HTTPBearer(auto_error=False)


async def get_auth_context(
    settings: AppSettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthContext:
    if credentials is None:
        raise AuthenticationError("Not authenticated.")
    try:
        return verify_access_token(credentials.credentials, secret=settings.jwt_secret)
    except TokenError as exc:
        logger.info("token_rejected", reason=str(exc))
        raise AuthenticationError("Not authenticated.") from None


AuthDep = Annotated[AuthContext, Depends(get_auth_context)]


def require_scope(scope: Scope) -> Callable[[AuthContext], Awaitable[AuthContext]]:
    async def check(auth: AuthDep) -> AuthContext:
        if scope not in auth.scopes:
            logger.info("scope_denied", user_id=str(auth.user_id), scope=scope.value)
            raise ForbiddenError("This account is not allowed to do that.")
        return auth

    return check
