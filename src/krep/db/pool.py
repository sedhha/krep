from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.config import Settings


async def open_pool(
    settings: Settings, min_size: int = 1, max_size: int = 10
) -> AsyncConnectionPool[AsyncConnection]:
    pool = AsyncConnectionPool[AsyncConnection](
        settings.database_url, min_size=min_size, max_size=max_size, open=False
    )
    await pool.open(wait=True)
    return pool
