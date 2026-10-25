from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool


@asynccontextmanager
async def tenant_transaction(
    pool: AsyncConnectionPool[AsyncConnection], tenant_id: UUID
) -> AsyncGenerator[AsyncConnection]:
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
        yield conn
