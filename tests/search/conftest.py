import uuid
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio

from krep.identity.resolve import Caller
from krep.policy.parser import parse
from krep.policy.store import write_policy
from tests.registry.conftest import world as world


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


async def open_policy(conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> uuid.UUID:
    cur = await conn.execute(
        "INSERT INTO access_policies (tenant_id, name, ast, source, compiled_path, "
        "compiler_version, reserved, kind, created_by, updated_by) "
        "VALUES (%s, 'open-to-all', '{}'::jsonb, 'true', 'true'::jsonpath, 1, true, 'open', "
        "'t', 't') ON CONFLICT (tenant_id, name) DO UPDATE SET kind = 'open' RETURNING id",
        (tenant,),
    )
    row = await cur.fetchone()
    assert row is not None
    return row[0]


async def add_resource(
    conn: psycopg.AsyncConnection,
    tenant: uuid.UUID,
    slug: str,
    name: str,
    *,
    description: str = "",
    tags: list[str] | None = None,
    open: bool = True,
    policies: list[uuid.UUID] | None = None,
    status: str = "published",
    type: str = "agent",
    created_by: str = "u1",
    scope: str = "org",
    product_id: uuid.UUID | None = None,
) -> uuid.UUID:
    cur = await conn.execute(
        "INSERT INTO registry (tenant_id, type, slug, name, description, tags, scope, "
        "product_id, status, created_by, updated_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            tenant,
            type,
            slug,
            name,
            description,
            tags or [],
            scope,
            product_id,
            status,
            created_by,
            created_by,
        ),
    )
    row = await cur.fetchone()
    assert row is not None
    attached = list(policies or [])
    if open:
        attached.append(await open_policy(conn, tenant))
    for policy_id in attached:
        await conn.execute(
            "INSERT INTO registry_policies (registry_id, tenant_id, action, policy_id) "
            "VALUES (%s, %s, 'read', %s)",
            (row[0], tenant, policy_id),
        )
    return row[0]


async def add_policy(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, name: str, rule: str
) -> uuid.UUID:
    return (await write_policy(conn, tenant, name, parse(rule), "admin")).id
