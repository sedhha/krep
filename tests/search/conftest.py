import uuid
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio

from krep.identity.resolve import Caller
from krep.policy.parser import parse
from krep.policy.store import write_policy


@pytest.fixture
def tenant() -> uuid.UUID:
    return uuid.uuid4()


@pytest_asyncio.fixture
async def conn(
    app_conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> AsyncIterator[psycopg.AsyncConnection]:
    await app_conn.execute(
        "SELECT set_config('app.tenant_id', %s, true)", (str(tenant),)
    )
    yield app_conn


def caller_for(
    tenant: uuid.UUID, user: str = "u1", token: dict[str, Any] | None = None
) -> Caller:
    return Caller(tenant, user, {"token": token or {}, "principal": {}}, True, False)


async def add_resource(
    conn: psycopg.AsyncConnection,
    tenant: uuid.UUID,
    slug: str,
    name: str,
    *,
    description: str = "",
    tags: list[str] | None = None,
    visibility: str = "tenant",
    status: str = "published",
    type: str = "agent",
    created_by: str = "u1",
    policy_id: uuid.UUID | None = None,
) -> uuid.UUID:
    cur = await conn.execute(
        "INSERT INTO registry (tenant_id, type, slug, name, description, tags, visibility, "
        "policy_id, status, created_by, updated_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            tenant,
            type,
            slug,
            name,
            description,
            tags or [],
            visibility,
            policy_id,
            status,
            created_by,
            created_by,
        ),
    )
    row = await cur.fetchone()
    assert row is not None
    return row[0]


async def add_policy(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, name: str, rule: str
) -> uuid.UUID:
    return (await write_policy(conn, tenant, name, parse(rule), "admin")).id
