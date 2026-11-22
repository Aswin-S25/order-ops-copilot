import asyncio
from collections.abc import Awaitable
from typing import Literal

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.dependencies import AppSettingsDep, DbEngineDep, RedisDep

router = APIRouter(prefix="/health", tags=["health"])
logger = structlog.get_logger("app.health")

CheckStatus = Literal["ok", "error"]


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


async def _ping_postgres(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _ping_redis(redis: Redis) -> None:
    await redis.ping()


async def _check(dependency: str, probe: Awaitable[object]) -> CheckStatus:
    try:
        await probe
    except Exception:
        logger.warning("readiness_check_failed", dependency=dependency, exc_info=True)
        return "error"
    return "ok"


@router.get("/ready")
async def ready(settings: AppSettingsDep, engine: DbEngineDep, redis: RedisDep) -> JSONResponse:
    timeout = settings.health_check_timeout_seconds
    postgres_status, redis_status = await asyncio.gather(
        _check("postgres", asyncio.wait_for(_ping_postgres(engine), timeout)),
        _check("redis", asyncio.wait_for(_ping_redis(redis), timeout)),
    )
    checks = {"postgres": postgres_status, "redis": redis_status}
    is_ready = all(status == "ok" for status in checks.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"status": "ready" if is_ready else "not_ready", "checks": checks},
    )
