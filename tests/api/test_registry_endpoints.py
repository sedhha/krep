import asyncio
import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from krep.api.deps import get_caller
from krep.api.errors import install_error_handlers
from krep.api.registry import router
from krep.identity.resolve import Caller
from tests.api.conftest import Pool

BASE = "/v1/registry"
AGENT: dict[str, Any] = {
    "type": "agent",
    "slug": "refund-assistant",
    "name": "Refund Assistant",
    "description": "Handles refunds.",
    "tags": ["billing"],
    "visibility": "tenant",
    "spec": {"model": "claude-sonnet-5-5", "system_prompt": "You help."},
}

MakeRegistryClient = Callable[..., httpx.AsyncClient]


def skill_zip(name: str = "refund-flow") -> bytes:
    md = f"---\nname: {name}\ndescription: Handles refunds.\n---\n# Refunds\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", md)
    return buf.getvalue()


@pytest.fixture
def make_registry_client(pool: Pool) -> MakeRegistryClient:
    def make(
        tenant: uuid.UUID, user: str = "u1", write: bool = True, admin: bool = False
    ) -> httpx.AsyncClient:
        app = FastAPI()
        app.state.pool = pool
        install_error_handlers(app)
        app.include_router(router)

        async def caller() -> Caller:
            return Caller(tenant, user, {"token": {}, "principal": {}}, write or admin, admin)

        app.dependency_overrides[get_caller] = caller
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    return make


@pytest.fixture
def tenant() -> uuid.UUID:
    return uuid.uuid4()


@pytest_asyncio.fixture
async def owner(
    make_registry_client: MakeRegistryClient, tenant: uuid.UUID
) -> AsyncIterator[httpx.AsyncClient]:
    async with make_registry_client(tenant) as c:
        yield c


async def create_agent(client: httpx.AsyncClient, **extra: Any) -> dict[str, Any]:
    r = await client.post(BASE, json={**AGENT, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_agent_returns_201_shape(owner: httpx.AsyncClient) -> None:
    body = await create_agent(owner)
    assert body["status"] == "draft"
    assert body["current_version"] is None
    assert body["version"] == {"version": 1, "status": "draft"}
    assert uuid.UUID(body["id"])


async def test_create_duplicate_slug_is_409(owner: httpx.AsyncClient) -> None:
    await create_agent(owner)
    r = await owner.post(BASE, json=AGENT)
    assert r.status_code == 409
    assert r.json()["error"] == "slug_taken"


async def test_create_validation_failure_lists_fields(owner: httpx.AsyncClient) -> None:
    r = await owner.post(BASE, json={**AGENT, "slug": "Bad Slug", "spec": {}})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "validation_failed"
    assert {"slug", "spec.model"} <= {e["field"] for e in body["errors"]}


async def test_create_missing_required_field_is_422(owner: httpx.AsyncClient) -> None:
    r = await owner.post(BASE, json={"type": "agent"})
    assert r.status_code == 422
    assert r.json()["error"] == "validation_failed"


async def test_create_requires_write_permission(
    make_registry_client: MakeRegistryClient, tenant: uuid.UUID
) -> None:
    async with make_registry_client(tenant, write=False) as reader:
        r = await reader.post(BASE, json=AGENT)
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


async def test_ac1_forged_tenant_id_is_ignored_and_other_tenant_cannot_read(
    make_registry_client: MakeRegistryClient, tenant: uuid.UUID
) -> None:
    other = uuid.uuid4()
    async with make_registry_client(tenant) as a, make_registry_client(other) as b:
        created = await create_agent(a, tenant_id=str(other))
        assert (await a.get(f"{BASE}/{created['id']}")).status_code == 200
        assert (await b.get(f"{BASE}/{created['id']}")).status_code == 404
        assert (await b.get(BASE)).json()["items"] == []


async def test_create_skill_multipart(owner: httpx.AsyncClient) -> None:
    metadata = {"type": "skill", "slug": "refund-flow", "name": "Refund Flow"}
    r = await owner.post(
        BASE,
        data={"metadata": json.dumps(metadata)},
        files={"archive": ("refund-flow.zip", skill_zip(), "application/zip")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["version"] == {"version": 1, "status": "draft"}
    got = await owner.get(f"{BASE}/{r.json()['id']}")
    assert got.json()["description"] == "Handles refunds."


async def test_create_skill_rejected_archive_is_422_and_nothing_stored(
    owner: httpx.AsyncClient,
) -> None:
    metadata = {"type": "skill", "slug": "refund-flow", "name": "Refund Flow"}
    r = await owner.post(
        BASE,
        data={"metadata": json.dumps(metadata)},
        files={"archive": ("x.zip", b"nope", "application/zip")},
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"].startswith("archive")
    assert (await owner.get(BASE)).json()["items"] == []


async def test_create_skill_with_json_spec_is_422(owner: httpx.AsyncClient) -> None:
    r = await owner.post(
        BASE,
        json={"type": "skill", "slug": "refund-flow", "name": "n", "spec": {"instructions": "x"}},
    )
    assert r.status_code == 422
    assert {"field": "spec", "message": "skills take an archive"} in r.json()["errors"]


async def test_create_multipart_without_metadata_is_422(owner: httpx.AsyncClient) -> None:
    r = await owner.post(BASE, files={"archive": ("x.zip", skill_zip(), "application/zip")})
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "metadata"


async def test_create_multipart_metadata_not_json_is_422(owner: httpx.AsyncClient) -> None:
    r = await owner.post(BASE, data={"metadata": "{nope"})
    assert r.status_code == 422


async def test_ac16_parallel_creates_never_exceed_the_cap(
    owner: httpx.AsyncClient,
) -> None:
    for i in range(45):
        await create_agent(owner, slug=f"seed-{i:02d}")
    results = await asyncio.gather(
        *(owner.post(BASE, json={**AGENT, "slug": f"race-{i:02d}"}) for i in range(10))
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201] * 5 + [409] * 5
    rejected = next(r for r in results if r.status_code == 409).json()
    assert rejected["error"] == "draft_limit_reached"
    assert rejected["limit"] == 50
    listing = await owner.get(BASE, params={"limit": 200})
    assert len(listing.json()["items"]) == 50


async def test_list_filters_and_pagination(owner: httpx.AsyncClient) -> None:
    for i in range(3):
        await create_agent(owner, slug=f"agent-{i}")
    page = await owner.get(BASE, params={"type": "agent", "status": "draft", "limit": 2})
    assert len(page.json()["items"]) == 2
    rest = await owner.get(BASE, params={"limit": 2, "offset": 2})
    assert len(rest.json()["items"]) == 1
    assert (await owner.get(BASE, params={"status": "published"})).json()["items"] == []
    assert (await owner.get(BASE, params={"limit": 0})).status_code == 422


async def test_list_requires_write_permission(
    make_registry_client: MakeRegistryClient, tenant: uuid.UUID
) -> None:
    async with make_registry_client(tenant, write=False) as reader:
        assert (await reader.get(BASE)).status_code == 403


async def test_get_hidden_draft_is_404_not_403(
    make_registry_client: MakeRegistryClient, tenant: uuid.UUID
) -> None:
    async with make_registry_client(tenant, "u1") as a, make_registry_client(tenant, "u2") as b:
        created = await create_agent(a)
        assert (await a.get(f"{BASE}/{created['id']}")).status_code == 200
        assert (await b.get(f"{BASE}/{created['id']}")).status_code == 404
        assert (await b.get(f"{BASE}/{uuid.uuid4()}")).status_code == 404


async def test_patch_updates_fields(owner: httpx.AsyncClient) -> None:
    created = await create_agent(owner)
    r = await owner.patch(f"{BASE}/{created['id']}", json={"name": "Renamed", "tags": ["x"]})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["tags"]) == ("Renamed", ["x"])


async def test_patch_restricted_without_policy_is_422(owner: httpx.AsyncClient) -> None:
    created = await create_agent(owner)
    r = await owner.patch(f"{BASE}/{created['id']}", json={"visibility": "restricted"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "policy_id"


async def test_patch_null_name_is_422(owner: httpx.AsyncClient) -> None:
    created = await create_agent(owner)
    r = await owner.patch(f"{BASE}/{created['id']}", json={"name": None})
    assert r.status_code == 422


async def test_patch_by_non_owner_is_403_for_visible_and_404_for_hidden(
    make_registry_client: MakeRegistryClient, tenant: uuid.UUID, pool: Pool
) -> None:
    async with make_registry_client(tenant, "u1") as a, make_registry_client(tenant, "u2") as b:
        draft = await create_agent(a, slug="draft-one")
        assert (await b.patch(f"{BASE}/{draft['id']}", json={"name": "x"})).status_code == 404


async def test_archive_of_draft_is_409(owner: httpx.AsyncClient) -> None:
    created = await create_agent(owner)
    r = await owner.post(f"{BASE}/{created['id']}/archive")
    assert r.status_code == 409
    assert r.json()["error"] == "invalid_state"
    assert (await owner.post(f"{BASE}/{created['id']}/unarchive")).status_code == 409


async def test_delete_returns_204_then_404(owner: httpx.AsyncClient) -> None:
    created = await create_agent(owner)
    assert (await owner.delete(f"{BASE}/{created['id']}")).status_code == 204
    assert (await owner.get(f"{BASE}/{created['id']}")).status_code == 404
    assert (await owner.delete(f"{BASE}/{created['id']}")).status_code == 404


async def test_types_route_is_not_shadowed_by_id_route(pool: Pool, tenant: uuid.UUID) -> None:
    from krep.api import create_app

    app = create_app()
    app.state.pool = pool

    async def caller() -> Caller:
        return Caller(tenant, "u1", {"token": {}, "principal": {}}, True, False)

    app.dependency_overrides[get_caller] = caller
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"{BASE}/types")
    assert r.status_code == 200
    assert "types" in r.json()
