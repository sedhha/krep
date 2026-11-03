import hmac

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.config import get_settings

MIN_KEY_LENGTH = 32
PLATFORM_USER = "platform-admin"

Pool = AsyncConnectionPool[AsyncConnection]


def key_matches(candidate: str) -> bool:
    configured = get_settings().platform_admin_key
    if len(configured) < MIN_KEY_LENGTH or not candidate:
        return False
    return hmac.compare_digest(configured.encode(), candidate.encode())


async def is_platform_admin(pool: Pool, user_id: str) -> bool:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM platform_admins WHERE user_id = %s", (user_id,)
        )
        return await cur.fetchone() is not None
