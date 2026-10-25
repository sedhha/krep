import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.config import Settings
from krep.db.pool import open_pool
from krep.db.tenant import tenant_transaction
from tests.conftest import role_url


@pytest_asyncio.fixture
async def pool(migrated_db: str) -> AsyncIterator[AsyncConnectionPool[AsyncConnection]]:
    settings = Settings(
        database_url=role_url("krep_app", migrated_db),
        migration_database_url="",
    )
    async with await open_pool(settings, min_size=1, max_size=1) as pool:
        yield pool


async def add_policy(pool: AsyncConnectionPool[AsyncConnection], tenant: uuid.UUID, name: str) -> None:
    async with tenant_transaction(pool, tenant) as conn:
        await conn.execute(
            "INSERT INTO access_policies (tenant_id, name, ast, source, compiled_path, "
            "compiler_version, created_by, updated_by) "
            "VALUES (%s, %s, '{}'::jsonb, 'true', '$'::jsonpath, 1, 'u', 'u')",
            (tenant, name),
        )


async def visible_names(pool: AsyncConnectionPool[AsyncConnection], tenant: uuid.UUID) -> list[str]:
    async with tenant_transaction(pool, tenant) as conn:
        cur = await conn.execute("SELECT name FROM access_policies ORDER BY name")
        return [row[0] for row in await cur.fetchall()]


async def test_tenant_b_on_reused_connection_sees_none_of_a(
    pool: AsyncConnectionPool[AsyncConnection],
) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    await add_policy(pool, a, "only-a")
    assert await visible_names(pool, a) == ["only-a"]
    assert await visible_names(pool, b) == []
    assert await visible_names(pool, a) == ["only-a"]


async def test_tenant_setting_does_not_leak_after_transaction(
    pool: AsyncConnectionPool[AsyncConnection],
) -> None:
    a = uuid.uuid4()
    await add_policy(pool, a, "leak-check")
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) FROM access_policies")
        row = await cur.fetchone()
        assert row is not None and row[0] == 0
