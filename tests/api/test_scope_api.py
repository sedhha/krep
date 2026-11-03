# pyright: reportUnusedImport=false
# ruff: noqa: F811
import uuid

import httpx
import psycopg
import pytest

from krep.db.tenant import tenant_transaction
from krep.identity.resolve import Caller
from krep.registry.publish import publish
from krep.registry.resources import create_resource
from tests.conftest import role_url
from tests.org.conftest import (  # noqa: F401
    Pool,
    Seed,
    add_policy,
    client,
    jwks,
    keys,
    make_client,
    owner_exec,
    panel_env,
    platform_headers,
    platform_pool,
    pool,
    seed,
)
from tests.registry.conftest import agent_body


async def agent_in(pool: Pool, org: uuid.UUID, slug: str = "scoped-agent") -> uuid.UUID:
    caller = Caller(org, "adm", {"token": {}, "principal": {}}, True, True)
    async with tenant_transaction(pool, org) as conn:
        rid = (await create_resource(conn, caller, agent_body(slug)))["id"]
        await publish(conn, caller, rid, 1)
    return rid


async def test_v2ac12_platform_admin_moves_a_resource_to_global_with_audit(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    migrated_db: str,
) -> None:
    org = await seed.org()
    rid = await agent_in(seed.pool, org.id)
    r = await client.put(
        f"/v1/admin/registry/{rid}/scope",
        json={"organization_id": str(org.id), "scope": "global"},
        headers=platform_headers,
    )
    assert r.status_code == 200
    assert r.json()["scope"] == "global"
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        rows = conn.execute(
            "SELECT action, tenant_id FROM admin_audit_log WHERE target = %s",
            (str(rid),),
        ).fetchall()
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(org.id),))
        conn.execute("DELETE FROM registry WHERE id = %s", (rid,))
        conn.commit()
    assert rows == [("registry.scope.global", org.id)]


async def test_v2ac12_unpublished_and_unknown_resources(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
) -> None:
    org = await seed.org()
    r = await client.put(
        f"/v1/admin/registry/{uuid.uuid4()}/scope",
        json={"organization_id": str(org.id), "scope": "global"},
        headers=platform_headers,
    )
    assert r.status_code == 404


async def test_v2ac6_scope_route_is_platform_only(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    org = await seed.org()
    r = await client.put(
        f"/v1/admin/registry/{uuid.uuid4()}/scope",
        json={"organization_id": str(org.id), "scope": "global"},
        headers={"x-platform-key": "wrong"},
    )
    assert r.status_code == 401


@pytest.mark.parametrize("scope", ["galaxy"])
async def test_scope_route_validates_scope(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    scope: str,
) -> None:
    org = await seed.org()
    r = await client.put(
        f"/v1/admin/registry/{uuid.uuid4()}/scope",
        json={"organization_id": str(org.id), "scope": scope},
        headers=platform_headers,
    )
    assert r.status_code == 422
