import hashlib
import io
import json
import logging
import uuid
import zipfile
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from krep.api.deps import get_caller
from krep.api.errors import install_error_handlers
from krep.api.registry import router as registry_router
from krep.api.versions import router as versions_router
from krep.identity.resolve import Caller
from tests.api.conftest import Pool
from tests.api.test_registry_endpoints import AGENT, BASE
from tests.registry.conftest import skill_zip

META = {"type": "skill", "slug": "refund-flow", "name": "Refund Flow"}


def app_for(pool: Pool, tenant: uuid.UUID | None) -> FastAPI:
    app = FastAPI()
    app.state.pool = pool
    install_error_handlers(app)
    app.include_router(registry_router)
    app.include_router(versions_router)
    if tenant is not None:

        async def caller() -> Caller:
            return Caller(tenant, "u1", {"token": {}, "principal": {}}, True, True)

        app.dependency_overrides[get_caller] = caller
    return app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.fixture
def tenant() -> uuid.UUID:
    return uuid.uuid4()


@pytest_asyncio.fixture
async def owner(pool: Pool, tenant: uuid.UUID) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(app_for(pool, tenant)) as c:
        yield c


async def counts(pool: Pool, tenant: uuid.UUID) -> tuple[int, int]:
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
            files = await (await conn.execute("SELECT count(*) FROM skill_files")).fetchone()
            skills = await (await conn.execute("SELECT count(*) FROM skills")).fetchone()
    assert files is not None and skills is not None
    return files[0], skills[0]


async def create_skill(
    c: httpx.AsyncClient, archive: bytes, **meta: Any
) -> httpx.Response:
    return await c.post(
        BASE,
        data={"metadata": json.dumps({**META, **meta})},
        files={"archive": ("a.zip", archive, "application/zip")},
    )


async def test_create_with_archive_returns_shape_and_download_matches_bytes(
    owner: httpx.AsyncClient,
) -> None:
    data = skill_zip()
    r = await create_skill(owner, data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type"] == "skill"
    assert body["version"] == {"version": 1, "status": "draft"}
    dl = await owner.get(f"{BASE}/{body['id']}/versions/1/archive")
    assert dl.status_code == 200
    assert dl.content == data
    assert dl.headers["content-type"] == "application/zip"
    assert dl.headers["etag"] == f'"{hashlib.sha256(data).hexdigest()}"'
    assert dl.headers["cache-control"] == "private, no-store"
    got = await owner.get(f"{BASE}/{body['id']}/versions/1")
    spec = got.json()["spec"]
    assert spec["content_sha256"] == hashlib.sha256(data).hexdigest()
    assert spec["size_bytes"] == len(data)


async def test_same_zip_uploaded_as_two_versions_shares_one_file_row(
    owner: httpx.AsyncClient, pool: Pool, tenant: uuid.UUID
) -> None:
    data = skill_zip()
    rid = (await create_skill(owner, data)).json()["id"]
    assert (await owner.post(f"{BASE}/{rid}/versions/1/publish")).status_code == 200
    r = await owner.post(
        f"{BASE}/{rid}/versions", files={"archive": ("a.zip", data, "application/zip")}
    )
    assert r.status_code == 201, r.text
    assert await counts(pool, tenant) == (1, 2)


async def test_draft_copy_from_version_copies_only_the_skills_row(
    owner: httpx.AsyncClient, pool: Pool, tenant: uuid.UUID
) -> None:
    rid = (await create_skill(owner, skill_zip())).json()["id"]
    assert (await owner.post(f"{BASE}/{rid}/versions/1/publish")).status_code == 200
    r = await owner.post(f"{BASE}/{rid}/versions", json={"from_version": 1})
    assert r.status_code == 201, r.text
    assert await counts(pool, tenant) == (1, 2)


async def test_same_zip_in_another_tenant_is_a_separate_file_row(
    pool: Pool, tenant: uuid.UUID
) -> None:
    other = uuid.uuid4()
    data = skill_zip()
    async with client_for(app_for(pool, tenant)) as a, client_for(app_for(pool, other)) as b:
        assert (await create_skill(a, data)).status_code == 201
        assert (await create_skill(b, data)).status_code == 201
    assert await counts(pool, tenant) == (1, 1)
    assert await counts(pool, other) == (1, 1)


async def test_oversized_body_is_413_and_writes_nothing(
    owner: httpx.AsyncClient, pool: Pool, tenant: uuid.UUID
) -> None:
    r = await create_skill(owner, b"\0" * (2 * 1024 * 1024))
    assert r.status_code == 413
    assert r.json()["error"] == "payload_too_large"
    assert await counts(pool, tenant) == (0, 0)
    assert (await owner.get(BASE)).json()["items"] == []


async def test_archive_just_over_cap_is_422_and_writes_nothing(
    owner: httpx.AsyncClient, pool: Pool, tenant: uuid.UUID
) -> None:
    r = await create_skill(owner, b"PK\x03\x04" + b"\0" * (1024 * 1024))
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "archive"
    assert await counts(pool, tenant) == (0, 0)


async def test_invalid_archive_returns_field_errors_and_writes_nothing(
    owner: httpx.AsyncClient, pool: Pool, tenant: uuid.UUID
) -> None:
    r = await create_skill(owner, skill_zip("other-name"))
    assert r.status_code == 422
    assert r.json()["error"] == "validation_failed"
    assert all(e["field"].startswith("archive") for e in r.json()["errors"])
    assert await counts(pool, tenant) == (0, 0)


async def test_skill_without_archive_part_is_422(owner: httpx.AsyncClient) -> None:
    r = await owner.post(BASE, data={"metadata": json.dumps(META)})
    assert r.status_code == 422
    assert (await owner.get(BASE)).json()["items"] == []


async def test_skill_with_json_spec_is_422(owner: httpx.AsyncClient) -> None:
    r = await owner.post(BASE, json={**META, "spec": {"content_sha256": "0" * 64}})
    assert r.status_code == 422
    assert {"field": "spec", "message": "skills take an archive"} in r.json()["errors"]


async def test_replace_draft_with_new_archive_swaps_file(
    owner: httpx.AsyncClient, pool: Pool, tenant: uuid.UUID
) -> None:
    rid = (await create_skill(owner, skill_zip())).json()["id"]
    new = skill_zip(body="Changed.")
    r = await owner.put(
        f"{BASE}/{rid}/versions/1", files={"archive": ("a.zip", new, "application/zip")}
    )
    assert r.status_code == 200, r.text
    dl = await owner.get(f"{BASE}/{rid}/versions/1/archive")
    assert dl.content == new
    assert await counts(pool, tenant) == (1, 1)


async def test_replace_draft_is_atomic_when_upload_is_bad(
    owner: httpx.AsyncClient, pool: Pool, tenant: uuid.UUID
) -> None:
    old = skill_zip()
    rid = (await create_skill(owner, old)).json()["id"]
    r = await owner.put(
        f"{BASE}/{rid}/versions/1", files={"archive": ("a.zip", b"nope", "application/zip")}
    )
    assert r.status_code == 422
    dl = await owner.get(f"{BASE}/{rid}/versions/1/archive")
    assert dl.content == old
    assert await counts(pool, tenant) == (1, 1)


async def test_replace_published_version_is_409_version_immutable(
    owner: httpx.AsyncClient,
) -> None:
    rid = (await create_skill(owner, skill_zip())).json()["id"]
    assert (await owner.post(f"{BASE}/{rid}/versions/1/publish")).status_code == 200
    r = await owner.put(
        f"{BASE}/{rid}/versions/1",
        files={"archive": ("a.zip", skill_zip(body="x"), "application/zip")},
    )
    assert r.status_code == 409
    assert r.json()["error"] == "version_immutable"


async def test_draft_from_upload_on_published_skill(owner: httpx.AsyncClient) -> None:
    rid = (await create_skill(owner, skill_zip())).json()["id"]
    assert (await owner.post(f"{BASE}/{rid}/versions/1/publish")).status_code == 200
    new = skill_zip(body="v2")
    r = await owner.post(
        f"{BASE}/{rid}/versions", files={"archive": ("a.zip", new, "application/zip")}
    )
    assert r.status_code == 201, r.text
    dl = await owner.get(f"{BASE}/{rid}/versions/2/archive")
    assert dl.content == new


async def test_download_hidden_resource_is_404_not_403(
    pool: Pool, tenant: uuid.UUID
) -> None:
    async with client_for(app_for(pool, tenant)) as a:
        rid = (await create_skill(a, skill_zip(), visibility="private")).json()["id"]
        assert (await a.post(f"{BASE}/{rid}/versions/1/publish")).status_code == 200

    async def stranger() -> Caller:
        return Caller(tenant, "someone-else", {"token": {}, "principal": {}}, False, False)

    app = app_for(pool, tenant)
    app.dependency_overrides[get_caller] = stranger
    async with client_for(app) as b:
        r = await b.get(f"{BASE}/{rid}/versions/1/archive")
    assert r.status_code == 404


async def test_download_other_tenants_version_is_404(pool: Pool, tenant: uuid.UUID) -> None:
    async with client_for(app_for(pool, tenant)) as a:
        rid = (await create_skill(a, skill_zip())).json()["id"]
    async with client_for(app_for(pool, uuid.uuid4())) as b:
        r = await b.get(f"{BASE}/{rid}/versions/1/archive")
    assert r.status_code == 404


async def test_download_agent_version_is_404(owner: httpx.AsyncClient) -> None:
    rid = (await owner.post(BASE, json=AGENT)).json()["id"]
    r = await owner.get(f"{BASE}/{rid}/versions/1/archive")
    assert r.status_code == 404


async def test_failing_upload_logs_no_archive_content(
    owner: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SENTINEL-DIR/SKILL.md", "---\nname: SENTINEL-NAME\ndescription: SENTINEL-DESC\n---\n")
    r = await create_skill(owner, buf.getvalue())
    assert r.status_code == 422
    assert "SENTINEL" not in caplog.text


async def test_endpoints_require_auth(pool: Pool) -> None:
    async with client_for(app_for(pool, None)) as c:
        rid = uuid.uuid4()
        assert (await c.post(BASE, data={"metadata": "{}"})).status_code == 401
        assert (await c.get(f"{BASE}/{rid}/versions/1/archive")).status_code == 401
        put = await c.put(f"{BASE}/{rid}/versions/1", files={"archive": ("a", b"x")})
        assert put.status_code == 401
