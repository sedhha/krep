from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.config import Settings


async def _open(
    url: str, min_size: int, max_size: int
) -> AsyncConnectionPool[AsyncConnection]:
    pool = AsyncConnectionPool[AsyncConnection](
        url, min_size=min_size, max_size=max_size, open=False
    )
    await pool.open(wait=True)
    return pool


async def open_pool(
    settings: Settings, min_size: int = 1, max_size: int = 10
) -> AsyncConnectionPool[AsyncConnection]:
    return await _open(settings.database_url, min_size, max_size)


async def open_platform_pool(
    settings: Settings, min_size: int = 1, max_size: int = 4
) -> AsyncConnectionPool[AsyncConnection] | None:
    if not settings.platform_database_url:
        return None
    return await _open(settings.platform_database_url, min_size, max_size)
