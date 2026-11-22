from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings


def get_app_settings(request: Request) -> Settings:
    return request.state.settings


def get_db_engine(request: Request) -> AsyncEngine:
    return request.state.db_engine


def get_redis(request: Request) -> Redis:
    return request.state.redis


AppSettingsDep = Annotated[Settings, Depends(get_app_settings)]
DbEngineDep = Annotated[AsyncEngine, Depends(get_db_engine)]
RedisDep = Annotated[Redis, Depends(get_redis)]
