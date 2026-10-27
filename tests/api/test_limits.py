import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from fastapi import FastAPI

from krep.api.deps import get_caller
from krep.api.errors import install_error_handlers
from krep.api.limits import router
from krep.db.tenant import tenant_transaction
from krep.identity.resolve import Caller
from krep.registry.limits import effective_limits, get_limit
from tests.api.conftest import OwnerExec, Pool


@pytest_asyncio.fixture
async def limits_client(pool: Pool, tenant_id: uuid.UUID) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    app.state.pool = pool
    install_error_handlers(app)
    app.include_router(router)

    async def caller() -> Caller:
        return Caller(tenant_id, "u1", {"token": {}, "principal": {}}, False, False)

    app.dependency_overrides[get_caller] = caller
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def lookup(pool: Pool, tenant: uuid.UUID, key: str, **kwargs: str | None) -> int:
    async with tenant_transaction(pool, tenant) as conn:
        return await get_limit(conn, tenant_id=tenant, key=key, **kwargs)


async def test_global_seed_value_is_returned(pool: Pool, tenant_id: uuid.UUID) -> None:
    assert await lookup(pool, tenant_id, "max_drafts", resource_type="agent") == 50


async def test_unknown_key_raises_lookup_error(pool: Pool, tenant_id: uuid.UUID) -> None:
    async with tenant_transaction(pool, tenant_id) as conn:
        try:
            await get_limit(conn, tenant_id=tenant_id, key="nope")
        except LookupError:
            return
    raise AssertionError("expected LookupError")


async def test_ac17_tenant_row_overrides_global(
    pool: Pool, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    await owner_exec(
        "INSERT INTO resource_limits (scope_type, scope_id, resource_type, limit_key, value) "
        "VALUES ('tenant', %s, 'agent', 'max_drafts', 200)",
        (str(tenant_id),),
    )
    assert await lookup(pool, tenant_id, "max_drafts", resource_type="agent") == 200
    assert await lookup(pool, tenant_id, "max_drafts", resource_type="skill") == 50


async def test_other_tenants_override_does_not_apply(
    pool: Pool, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    await owner_exec(
        "INSERT INTO resource_limits (scope_type, scope_id, resource_type, limit_key, value) "
        "VALUES ('tenant', %s, NULL, 'max_drafts', 7)",
        (str(uuid.uuid4()),),
    )
    assert await lookup(pool, tenant_id, "max_drafts", resource_type="agent") == 50


async def test_type_specific_beats_type_agnostic_at_same_scope(
    pool: Pool, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    for resource_type, value in (("NULL", 11), ("'agent'", 22)):
        await owner_exec(
            "INSERT INTO resource_limits (scope_type, scope_id, resource_type, limit_key, value) "
            f"VALUES ('tenant', %s, {resource_type}, 'max_drafts', %s)",
            (str(tenant_id), value),
        )
    assert await lookup(pool, tenant_id, "max_drafts", resource_type="agent") == 22
    assert await lookup(pool, tenant_id, "max_drafts", resource_type="skill") == 11


async def test_scope_specificity_beats_type_specificity(
    pool: Pool, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    await owner_exec(
        "INSERT INTO resource_limits (scope_type, scope_id, resource_type, limit_key, value) "
        "VALUES ('tenant', %s, NULL, 'max_drafts', 5)",
        (str(tenant_id),),
    )
    assert await lookup(pool, tenant_id, "max_drafts", resource_type="agent") == 5


async def test_get_limits_returns_effective_values(
    limits_client: httpx.AsyncClient, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    await owner_exec(
        "INSERT INTO resource_limits (scope_type, scope_id, resource_type, limit_key, value) "
        "VALUES ('tenant', %s, 'agent', 'max_drafts', 200)",
        (str(tenant_id),),
    )
    resp = await limits_client.get("/v1/limits")
    assert resp.status_code == 200
    body = resp.json()
    assert body["limits"]["max_drafts"] == 50
    assert body["limits"]["max_published_versions"] == 10
    assert body["types"]["agent"] == {"max_drafts": 200}
    assert "skill" not in body["types"]


async def test_effective_limits_for_a_tenant_without_overrides(
    pool: Pool, tenant_id: uuid.UUID
) -> None:
    async with tenant_transaction(pool, tenant_id) as conn:
        result = await effective_limits(conn, tenant_id)
    assert result["limits"]["max_policies"] == 500
    assert result["types"] == {}


async def test_get_registry_types_lists_seeded_types(limits_client: httpx.AsyncClient) -> None:
    resp = await limits_client.get("/v1/registry/types")
    assert resp.status_code == 200
    assert [t["type"] for t in resp.json()["types"]] == ["agent", "skill"]
    assert all(t["description"] for t in resp.json()["types"])
