import io
import uuid
import zipfile
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import psycopg
import pytest
import pytest_asyncio
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool

from krep.api.deps import get_caller
from krep.api.errors import install_error_handlers
from krep.api.links import router as links_router
from krep.api.registry import router as registry_router
from krep.api.versions import router as versions_router
from krep.config import Settings
from krep.db.pool import open_pool
from krep.identity.resolve import Caller
from krep.registry.publish import publish
from krep.registry.resources import create_resource
from krep.registry.versions import create_draft, replace_draft
from tests.conftest import role_url

Pool = AsyncConnectionPool[psycopg.AsyncConnection]
SetLimit = Callable[..., Awaitable[None]]

AGENT_SPEC: dict[str, Any] = {
    "model": "claude-sonnet-5-5",
    "system_prompt": "You help.",
}


def skill_zip(name: str = "refund-flow", body: str = "Body.") -> bytes:
    md = f"---\nname: {name}\ndescription: Handles refunds.\n---\n# Refunds\n{body}\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}/SKILL.md", md)
    return buf.getvalue()


def agent_body(slug: str = "refund-assistant", **extra: Any) -> dict[str, Any]:
    return {
        "type": "agent",
        "slug": slug,
        "name": "Refund Assistant",
        "description": "Handles refunds.",
        "tags": [],
        "spec": AGENT_SPEC,
        **extra,
    }


def skill_body(
    slug: str = "refund-flow", archive: bytes | None = None
) -> dict[str, Any]:
    return {
        "type": "skill",
        "slug": slug,
        "name": "Refund Flow",
        "archive": archive if archive is not None else skill_zip(slug),
    }


def caller_for(tenant: uuid.UUID, user: str = "u1", admin: bool = False) -> Caller:
    return Caller(tenant, user, {"token": {}, "principal": {}}, True, admin)


def spec_with(prompt: str) -> dict[str, Any]:
    return {**AGENT_SPEC, "system_prompt": prompt}


async def scalar(conn: psycopg.AsyncConnection, query: str, *params: Any) -> Any:
    cur = await conn.execute(query, params)  # type: ignore[arg-type]
    row = await cur.fetchone()
    assert row is not None
    return row[0]


async def new_agent(
    conn: psycopg.AsyncConnection, caller: Caller, slug: str = "refund-assistant"
) -> uuid.UUID:
    return (await create_resource(conn, caller, agent_body(slug)))["id"]


async def new_skill(
    conn: psycopg.AsyncConnection,
    caller: Caller,
    slug: str = "refund-flow",
    body: str = "Body.",
) -> uuid.UUID:
    created = await create_resource(
        conn, caller, skill_body(slug, skill_zip(slug, body))
    )
    return created["id"]


async def publish_agent_versions(
    conn: psycopg.AsyncConnection, caller: Caller, resource_id: uuid.UUID, count: int
) -> None:
    await publish(conn, caller, resource_id, 1)
    for n in range(2, count + 1):
        draft = await create_draft(conn, caller, resource_id)
        await replace_draft(
            conn,
            caller,
            resource_id,
            draft["version"]["version"],
            spec=spec_with(f"v{n}"),
        )
        await publish(conn, caller, resource_id, n)


async def publish_skill_versions(
    conn: psycopg.AsyncConnection,
    caller: Caller,
    resource_id: uuid.UUID,
    slug: str,
    count: int,
) -> None:
    await publish(conn, caller, resource_id, 1)
    for n in range(2, count + 1):
        draft = await create_draft(
            conn, caller, resource_id, archive=skill_zip(slug, f"body {n}")
        )
        await publish(conn, caller, resource_id, draft["version"]["version"])


async def link_pin(
    conn: psycopg.AsyncConnection,
    tenant: uuid.UUID,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    pinned_version_id: uuid.UUID,
) -> uuid.UUID:
    return await scalar(
        conn,
        "INSERT INTO registry_links (tenant_id, source_id, target_id, relation, "
        "pinned_version_id, origin_id, status, created_by) "
        "VALUES (%s, %s, %s, 'uses', %s, %s, 'accepted', 'u1') RETURNING id",
        tenant,
        source_id,
        target_id,
        pinned_version_id,
        source_id,
    )


async def version_id_of(
    conn: psycopg.AsyncConnection, resource_id: uuid.UUID, n: int
) -> uuid.UUID:
    return await scalar(
        conn,
        "SELECT id FROM registry_versions WHERE registry_id = %s AND version = %s",
        resource_id,
        n,
    )


async def open_policy(conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> uuid.UUID:
    return await scalar(
        conn,
        "INSERT INTO access_policies (tenant_id, name, ast, source, compiled_path, "
        "compiler_version, reserved, kind, created_by, updated_by) "
        "VALUES (%s, 'open-to-all', '{}'::jsonb, 'true', 'true'::jsonpath, 1, true, 'open', "
        "'t', 't') ON CONFLICT (tenant_id, name) DO UPDATE SET kind = 'open' RETURNING id",
        tenant,
    )


async def share(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, *resource_ids: uuid.UUID
) -> None:
    policy = await open_policy(conn, tenant)
    for resource_id in resource_ids:
        await conn.execute(
            "INSERT INTO registry_policies (registry_id, tenant_id, action, policy_id) "
            "VALUES (%s, %s, 'read', %s) ON CONFLICT DO NOTHING",
            (resource_id, tenant, policy),
        )


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


@pytest_asyncio.fixture
async def pool(migrated_db: str) -> AsyncIterator[Pool]:
    settings = Settings(
        database_url=role_url("krep_app", migrated_db), migration_database_url=""
    )
    async with await open_pool(settings, min_size=1, max_size=6) as pool:
        yield pool


@pytest_asyncio.fixture
async def set_limit(migrated_db: str, tenant: uuid.UUID) -> AsyncIterator[SetLimit]:
    async with await psycopg.AsyncConnection.connect(
        role_url("krep_owner", migrated_db), autocommit=True
    ) as owner:

        async def run(
            key: str, value: int, resource_type: str | None = "agent"
        ) -> None:
            await owner.execute(
                "INSERT INTO resource_limits (scope_type, scope_id, resource_type, limit_key, value) "
                "VALUES ('tenant', %s, %s, %s, %s)",
                (str(tenant), resource_type, key, value),
            )

        yield run


MakeClient = Callable[..., httpx.AsyncClient]


@pytest.fixture
def make_client(pool: Pool) -> MakeClient:
    def make(
        tenant: uuid.UUID, user: str = "u1", write: bool = True, admin: bool = False
    ) -> httpx.AsyncClient:
        app = FastAPI()
        app.state.pool = pool
        install_error_handlers(app)
        app.include_router(registry_router)
        app.include_router(versions_router)
        app.include_router(links_router)

        async def caller() -> Caller:
            return Caller(
                tenant, user, {"token": {}, "principal": {}}, write or admin, admin
            )

        app.dependency_overrides[get_caller] = caller
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        )

    return make


@dataclass
class World:
    conn: psycopg.AsyncConnection
    a: uuid.UUID
    b: uuid.UUID
    products: dict[str, uuid.UUID]
    open: dict[uuid.UUID, uuid.UUID]

    async def use(self, tenant: uuid.UUID, platform: bool = False) -> None:
        await self.conn.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (str(tenant),)
        )
        await self.conn.execute(
            "SELECT set_config('app.platform_admin', %s, true)",
            ("on" if platform else "",),
        )

    def caller(
        self,
        tenant: uuid.UUID,
        user: str = "u1",
        *,
        admin: bool = False,
        write: bool = True,
        product: str | None = None,
        token: dict[str, Any] | None = None,
    ) -> Caller:
        return Caller(
            tenant,
            user,
            {"token": token or {}, "principal": {}},
            write or admin,
            admin,
            self.products[product] if product else None,
        )


async def published_agent(
    world: World,
    caller: Caller,
    slug: str = "refund-assistant",
    **extra: Any,
) -> uuid.UUID:
    created = await create_resource(world.conn, caller, agent_body(slug, **extra))
    await publish(world.conn, caller, created["id"], 1)
    return created["id"]


@pytest_asyncio.fixture
async def world(owner_conn: psycopg.AsyncConnection) -> AsyncIterator[World]:
    a, b = uuid.uuid4(), uuid.uuid4()
    products: dict[str, uuid.UUID] = {}
    opens: dict[uuid.UUID, uuid.UUID] = {}
    for tenant in (a, b):
        await owner_conn.execute(
            "INSERT INTO organizations (id, slug, name, created_by) VALUES (%s, %s, 'Org', 'u')",
            (tenant, f"org-{tenant.hex[:12]}"),
        )
        await owner_conn.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (str(tenant),)
        )
        opens[tenant] = await open_policy(owner_conn, tenant)
    await owner_conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(a),))
    for slug in ("alpha", "beta"):
        products[slug] = await scalar(
            owner_conn,
            "INSERT INTO products (tenant_id, slug, name, created_by) "
            "VALUES (%s, %s, %s, 'u') RETURNING id",
            a,
            slug,
            slug,
        )
    await owner_conn.execute("SET LOCAL ROLE krep_app")
    yield World(owner_conn, a, b, products, opens)
