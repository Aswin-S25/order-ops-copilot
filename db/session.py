import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def tenant_session(
    sessions: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID
) -> AsyncIterator[AsyncSession]:
    async with sessions() as session, session.begin():
        await session.execute(SET_TENANT, {"tenant_id": str(tenant_id)})
        yield session
