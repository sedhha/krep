import asyncio
import json
import uuid

import psycopg
import pytest

from krep.api.errors import ApiError
from krep.db.tenant import tenant_transaction
from krep.registry.publish import publish
from krep.registry.resources import create_resource
from krep.registry.versions import (
    create_draft,
    delete_version,
    get_archive,
    get_version,
    list_versions,
    replace_draft,
)
from tests.registry.conftest import (
    AGENT_SPEC,
    MakeClient,
    Pool,
    SetLimit,
    agent_body,
    caller_for,
    new_agent,
    new_skill,
    scalar,
    skill_body,
    skill_zip,
    spec_with,
)

BASE = "/v1/registry"


async def test_new_draft_copies_current_version_spec(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish(conn, caller, rid, 1)
    out = await create_draft(conn, caller, rid)
    assert out["version"] == {"version": 2, "status": "draft"}
    spec = (await get_version(conn, caller, rid, 2))["spec"]
    assert spec["model"] == AGENT_SPEC["model"]
    assert spec["system_prompt"] == AGENT_SPEC["system_prompt"]
    assert (
        await scalar(conn, "SELECT next_version FROM registry WHERE id = %s", rid) == 3
    )


async def test_new_draft_from_version_copies_that_version(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish(conn, caller, rid, 1)
    await create_draft(conn, caller, rid)
    await replace_draft(conn, caller, rid, 2, spec=spec_with("second"))
    await publish(conn, caller, rid, 2)
    await create_draft(conn, caller, rid, from_version=1)
    assert (await get_version(conn, caller, rid, 3))["spec"][
        "system_prompt"
    ] == "You help."
    await create_draft(conn, caller, rid)
    assert (await get_version(conn, caller, rid, 4))["spec"][
        "system_prompt"
    ] == "second"


async def test_never_published_resource_copies_latest_draft(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await create_draft(conn, caller, rid)
    await replace_draft(conn, caller, rid, 2, spec=spec_with("latest"))
    await create_draft(conn, caller, rid)
    assert (await get_version(conn, caller, rid, 3))["spec"][
        "system_prompt"
    ] == "latest"


async def test_new_draft_from_missing_version_is_404(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    with pytest.raises(ApiError) as exc:
        await create_draft(conn, caller, rid, from_version=9)
    assert exc.value.status == 404


async def test_ac16_drafts_count_toward_cap_and_tenant_override_applies(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, set_limit: SetLimit
) -> None:
    await set_limit("max_drafts", 3)
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await create_draft(conn, caller, rid)
    await create_draft(conn, caller, rid)
    with pytest.raises(ApiError) as exc:
        await create_draft(conn, caller, rid)
    assert exc.value.error == "draft_limit_reached"
    assert exc.value.extra == {"limit": 3, "current": 3}


async def test_skill_draft_copy_shares_the_file_row_and_hash(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_skill(conn, caller)
    await publish(conn, caller, rid, 1)
    await create_draft(conn, caller, rid)
    assert await scalar(conn, "SELECT count(*) FROM skill_files") == 1
    cur = await conn.execute(
        "SELECT count(DISTINCT content_sha256), count(*) FROM skills WHERE registry_id = %s",
        (rid,),
    )
    assert await cur.fetchone() == (1, 2)
    one = await get_version(conn, caller, rid, 1)
    two = await get_version(conn, caller, rid, 2)
    assert one["spec"]["content_sha256"] == two["spec"]["content_sha256"]


async def test_skill_draft_from_upload_creates_its_own_file(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_skill(conn, caller)
    out = await create_draft(
        conn, caller, rid, archive=skill_zip("refund-flow", "changed")
    )
    assert out["version"]["version"] == 2
    assert await scalar(conn, "SELECT count(*) FROM skill_files") == 2


async def test_draft_with_archive_and_from_version_is_422(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_skill(conn, caller)
    with pytest.raises(ApiError) as exc:
        await create_draft(conn, caller, rid, from_version=1, archive=skill_zip())
    assert exc.value.status == 422


async def test_replace_agent_draft_swaps_the_spec(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    out = await replace_draft(conn, caller, rid, 1, spec=spec_with("replaced"))
    assert out["spec"]["system_prompt"] == "replaced"
    assert (
        await scalar(conn, "SELECT count(*) FROM agents WHERE registry_id = %s", rid)
        == 1
    )


async def test_replace_with_invalid_spec_is_422_and_keeps_the_old_one(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    with pytest.raises(ApiError) as exc:
        await replace_draft(conn, caller, rid, 1, spec={"model": ""})
    assert exc.value.status == 422
    assert (await get_version(conn, caller, rid, 1))["spec"][
        "system_prompt"
    ] == "You help."


async def test_replace_published_version_is_409_version_immutable(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish(conn, caller, rid, 1)
    with pytest.raises(ApiError) as exc:
        await replace_draft(conn, caller, rid, 1, spec=spec_with("x"))
    assert (exc.value.status, exc.value.error) == (409, "version_immutable")


async def test_replace_skill_archive_swaps_atomically_and_releases_the_old_file(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_skill(conn, caller)
    before = await scalar(
        conn, "SELECT content_sha256 FROM skills WHERE registry_id = %s", rid
    )
    await replace_draft(
        conn, caller, rid, 1, archive=skill_zip("refund-flow", "new body")
    )
    after = await scalar(
        conn, "SELECT content_sha256 FROM skills WHERE registry_id = %s", rid
    )
    assert after != before
    assert await scalar(conn, "SELECT count(*) FROM skill_files") == 1
    assert await scalar(conn, "SELECT content_sha256 FROM skill_files") == after


async def test_replace_skill_with_invalid_archive_leaves_the_old_one_untouched(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_skill(conn, caller)
    before = await scalar(
        conn, "SELECT content_sha256 FROM skills WHERE registry_id = %s", rid
    )
    with pytest.raises(ApiError) as exc:
        await replace_draft(conn, caller, rid, 1, archive=b"not a zip")
    assert exc.value.status == 422
    assert (
        await scalar(
            conn, "SELECT content_sha256 FROM skills WHERE registry_id = %s", rid
        )
        == before
    )
    assert await scalar(conn, "SELECT count(*) FROM skill_files") == 1


async def test_replace_published_skill_is_409_version_immutable(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_skill(conn, caller)
    await publish(conn, caller, rid, 1)
    with pytest.raises(ApiError) as exc:
        await replace_draft(conn, caller, rid, 1, archive=skill_zip("refund-flow", "x"))
    assert exc.value.error == "version_immutable"


async def test_replace_skill_with_spec_or_agent_with_archive_is_422(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    skill = await new_skill(conn, caller)
    agent = await new_agent(conn, caller)
    with pytest.raises(ApiError) as a:
        await replace_draft(conn, caller, skill, 1, spec={"instructions": "x"})
    with pytest.raises(ApiError) as b:
        await replace_draft(conn, caller, agent, 1, archive=skill_zip())
    assert (a.value.status, b.value.status) == (422, 422)


async def test_non_owner_gets_403_on_visible_and_404_on_hidden(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    owner, other = caller_for(tenant, "u1"), caller_for(tenant, "u2")
    hidden = (await create_resource(conn, owner, agent_body("hidden-one")))["id"]
    shown = (
        await create_resource(conn, owner, agent_body("shown-one", visibility="tenant"))
    )["id"]
    await publish(conn, owner, shown, 1)
    with pytest.raises(ApiError) as a:
        await create_draft(conn, other, hidden)
    with pytest.raises(ApiError) as b:
        await create_draft(conn, other, shown)
    assert (a.value.status, b.value.status) == (404, 403)


async def test_list_shows_drafts_only_to_owner_or_admin(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    owner, other, admin = (
        caller_for(tenant, "u1"),
        caller_for(tenant, "u2"),
        caller_for(tenant, "u3", True),
    )
    rid = (await create_resource(conn, owner, agent_body(visibility="tenant")))["id"]
    await publish(conn, owner, rid, 1)
    await create_draft(conn, owner, rid)
    assert [v["version"] for v in await list_versions(conn, owner, rid)] == [1, 2]
    assert [v["version"] for v in await list_versions(conn, admin, rid)] == [1, 2]
    assert [v["version"] for v in await list_versions(conn, other, rid)] == [1]
    assert "spec" not in (await list_versions(conn, owner, rid))[0]


async def test_get_draft_version_is_404_for_non_editor(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    owner, other = caller_for(tenant, "u1"), caller_for(tenant, "u2")
    rid = (await create_resource(conn, owner, agent_body(visibility="tenant")))["id"]
    await publish(conn, owner, rid, 1)
    await create_draft(conn, owner, rid)
    assert (await get_version(conn, other, rid, 1))["status"] == "published"
    with pytest.raises(ApiError) as exc:
        await get_version(conn, other, rid, 2)
    assert exc.value.status == 404


async def test_get_archive_returns_exact_bytes_and_hash(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    data = skill_zip("refund-flow", "exact")
    rid = (await create_resource(conn, caller, skill_body(archive=data)))["id"]
    got, sha = await get_archive(conn, caller, rid, 1)
    assert got == data
    assert sha == await scalar(
        conn, "SELECT content_sha256 FROM skills WHERE registry_id = %s", rid
    )


async def test_get_archive_is_404_when_version_not_visible_or_not_a_skill(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    owner, other = caller_for(tenant, "u1"), caller_for(tenant, "u2")
    skill = await new_skill(conn, owner)
    agent = await new_agent(conn, owner, "an-agent")
    with pytest.raises(ApiError) as a:
        await get_archive(conn, other, skill, 1)
    with pytest.raises(ApiError) as b:
        await get_archive(conn, owner, agent, 1)
    assert (a.value.status, b.value.status) == (404, 404)


async def test_deleting_a_draft_releases_the_file_only_with_the_last_reference(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_skill(conn, caller)
    await create_draft(conn, caller, rid)
    assert await scalar(conn, "SELECT count(*) FROM skill_files") == 1
    await delete_version(conn, caller, rid, 1)
    assert await scalar(conn, "SELECT count(*) FROM skill_files") == 1
    await delete_version(conn, caller, rid, 2)
    assert await scalar(conn, "SELECT count(*) FROM skill_files") == 0


async def test_delete_unknown_version_is_404(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    with pytest.raises(ApiError) as exc:
        await delete_version(conn, caller, rid, 7)
    assert exc.value.status == 404


async def test_concurrent_upload_of_same_bytes_during_cleanup_keeps_its_file(
    pool: Pool, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    data = skill_zip("shared-skill", "race")
    async with tenant_transaction(pool, tenant) as setup:
        rid = (await create_resource(setup, caller, skill_body("shared-skill", data)))[
            "id"
        ]

    async def upload_same_bytes() -> None:
        async with tenant_transaction(pool, tenant) as other:
            await create_draft(other, caller, rid, archive=data)

    async with tenant_transaction(pool, tenant) as deleter:
        await delete_version(deleter, caller, rid, 1)
        task = asyncio.create_task(upload_same_bytes())
        await asyncio.sleep(0.3)
        assert not task.done()
    await asyncio.wait_for(task, 5)
    async with tenant_transaction(pool, tenant) as check:
        cur = await check.execute(
            "SELECT count(*) FROM skills s JOIN skill_files f "
            "ON f.tenant_id = s.tenant_id AND f.content_sha256 = s.content_sha256 "
            "WHERE s.registry_id = %s",
            (rid,),
        )
        assert (await cur.fetchone()) == (1,)


async def test_api_draft_lifecycle(make_client: MakeClient, tenant: uuid.UUID) -> None:
    async with make_client(tenant) as c:
        created = (
            await c.post(
                BASE, json={k: v for k, v in agent_body().items() if k != "archive"}
            )
        ).json()
        rid = created["id"]
        r = await c.post(f"{BASE}/{rid}/versions", json={"from_version": 1})
        assert r.status_code == 201
        assert r.json()["version"] == {"version": 2, "status": "draft"}
        r = await c.post(f"{BASE}/{rid}/versions")
        assert r.status_code == 201
        assert r.json()["version"]["version"] == 3
        r = await c.put(f"{BASE}/{rid}/versions/2", json={"spec": spec_with("via api")})
        assert r.status_code == 200
        assert r.json()["spec"]["system_prompt"] == "via api"
        assert (await c.get(f"{BASE}/{rid}/versions/2")).json()["spec"][
            "system_prompt"
        ] == "via api"
        listing = (await c.get(f"{BASE}/{rid}/versions")).json()["items"]
        assert [v["version"] for v in listing] == [1, 2, 3]
        assert (await c.delete(f"{BASE}/{rid}/versions/3")).status_code == 204
        assert (await c.get(f"{BASE}/{rid}/versions/3")).status_code == 404
        bad = await c.put(f"{BASE}/{rid}/versions/2", json={"spec": {}})
        assert bad.status_code == 422
        assert bad.json()["error"] == "validation_failed"
        assert (await c.put(f"{BASE}/{rid}/versions/2", json={})).status_code == 422


async def test_api_skill_put_and_archive_download(
    make_client: MakeClient, tenant: uuid.UUID
) -> None:
    metadata = {"type": "skill", "slug": "refund-flow", "name": "Refund Flow"}
    async with make_client(tenant) as c:
        r = await c.post(
            BASE,
            data={"metadata": json.dumps(metadata)},
            files={"archive": ("a.zip", skill_zip(), "application/zip")},
        )
        rid = r.json()["id"]
        new = skill_zip("refund-flow", "second")
        put = await c.put(
            f"{BASE}/{rid}/versions/1",
            files={"archive": ("a.zip", new, "application/zip")},
        )
        assert put.status_code == 200, put.text
        got = await c.get(f"{BASE}/{rid}/versions/1/archive")
        assert got.status_code == 200
        assert got.content == new
        assert got.headers["content-type"] == "application/zip"
        assert got.headers["etag"] == f'"{put.json()["spec"]["content_sha256"]}"'
        assert got.headers["cache-control"] == "private, no-store"
        bad = await c.put(
            f"{BASE}/{rid}/versions/1",
            files={"archive": ("a.zip", b"nope", "application/zip")},
        )
        assert bad.status_code == 422
        assert (await c.get(f"{BASE}/{rid}/versions/1/archive")).content == new
        no_archive = await c.put(f"{BASE}/{rid}/versions/1", json={"spec": {}})
        assert no_archive.status_code == 422
        draft = await c.post(
            f"{BASE}/{rid}/versions",
            files={
                "archive": (
                    "a.zip",
                    skill_zip("refund-flow", "third"),
                    "application/zip",
                )
            },
        )
        assert draft.status_code == 201
        assert draft.json()["version"]["version"] == 2


async def test_api_archive_of_hidden_version_is_404(
    make_client: MakeClient, tenant: uuid.UUID
) -> None:
    metadata = {"type": "skill", "slug": "refund-flow", "name": "Refund Flow"}
    async with make_client(tenant, "u1") as a, make_client(tenant, "u2") as b:
        r = await a.post(
            BASE,
            data={"metadata": json.dumps(metadata)},
            files={"archive": ("a.zip", skill_zip(), "application/zip")},
        )
        rid = r.json()["id"]
        assert (await b.get(f"{BASE}/{rid}/versions/1/archive")).status_code == 404
        assert (await b.get(f"{BASE}/{rid}/versions/1")).status_code == 404
        assert (await b.get(f"{BASE}/{rid}/versions")).status_code == 404


async def test_api_versions_require_write_for_mutations(
    make_client: MakeClient, tenant: uuid.UUID
) -> None:
    async with make_client(tenant, write=False) as reader:
        rid = uuid.uuid4()
        assert (await reader.post(f"{BASE}/{rid}/versions")).status_code == 403
        assert (
            await reader.put(f"{BASE}/{rid}/versions/1", json={"spec": {}})
        ).status_code == 403
        assert (await reader.delete(f"{BASE}/{rid}/versions/1")).status_code == 403
