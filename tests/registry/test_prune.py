import asyncio
import uuid

import psycopg
import pytest

from krep.api.errors import ApiError
from krep.db.tenant import tenant_transaction
from krep.registry.prune import version_in_use
from krep.registry.publish import publish, set_current
from krep.registry.versions import (
    create_draft,
    delete_version,
    list_versions,
    replace_draft,
)
from tests.registry.conftest import (
    MakeClient,
    Pool,
    SetLimit,
    agent_body,
    caller_for,
    link_pin,
    new_agent,
    new_skill,
    publish_agent_versions,
    publish_skill_versions,
    scalar,
    spec_with,
    version_id_of,
)

BASE = "/v1/registry"


async def retained(conn: psycopg.AsyncConnection, rid: uuid.UUID) -> list[int]:
    cur = await conn.execute(
        "SELECT version FROM registry_versions WHERE registry_id = %s ORDER BY version", (rid,)
    )
    return [r[0] for r in await cur.fetchall()]


async def add_dep(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, version_id: uuid.UUID, on: uuid.UUID
) -> None:
    await conn.execute(
        "INSERT INTO registry_version_deps (version_id, depends_on_version_id, tenant_id, "
        "relation, auto_load) VALUES (%s, %s, %s, 'uses', true)",
        (version_id, on, tenant),
    )


async def test_ac15_eleventh_publish_deletes_oldest_non_current_version(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish_agent_versions(conn, caller, rid, 10)
    assert await retained(conn, rid) == list(range(1, 11))
    await create_draft(conn, caller, rid)
    await replace_draft(conn, caller, rid, 11, spec=spec_with("eleven"))
    out = await publish(conn, caller, rid, 11)
    assert out["pruned_versions"] == [1]
    assert await retained(conn, rid) == list(range(2, 12))
    assert await scalar(conn, "SELECT count(*) FROM agents WHERE registry_id = %s", rid) == 10


async def test_prune_skips_the_current_version(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, set_limit: SetLimit
) -> None:
    await set_limit("max_published_versions", 3)
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish_agent_versions(conn, caller, rid, 3)
    await set_current(conn, caller, rid, 1)
    await create_draft(conn, caller, rid)
    await replace_draft(conn, caller, rid, 4, spec=spec_with("four"))
    out = await publish(conn, caller, rid, 4, make_current=False)
    assert out["pruned_versions"] == [2]
    assert await retained(conn, rid) == [1, 3, 4]


async def test_ac17_tenant_limit_override_changes_retention_without_code_change(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, set_limit: SetLimit
) -> None:
    await set_limit("max_published_versions", 2)
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish_agent_versions(conn, caller, rid, 4)
    assert await retained(conn, rid) == [3, 4]


async def test_ac15_pinned_oldest_version_is_409_version_in_use_and_nothing_changes(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    target = await new_agent(conn, caller, "target-agent")
    await publish_agent_versions(conn, caller, target, 10)
    source = await new_agent(conn, caller, "support-bot")
    link_id = await link_pin(conn, tenant, source, target, await version_id_of(conn, target, 1))
    await create_draft(conn, caller, target)
    await replace_draft(conn, caller, target, 11, spec=spec_with("eleven"))
    with pytest.raises(ApiError) as exc:
        await publish(conn, caller, target, 11)
    err = exc.value
    assert (err.status, err.error) == (409, "version_in_use")
    assert err.extra["version_to_remove"] == 1
    assert err.extra["referenced_by"] == [
        {"kind": "link_pin", "resource": "support-bot", "resource_id": str(source), "link_id": str(link_id)}
    ]
    assert "v11" in err.message
    assert "v1" in err.message
    assert await retained(conn, target) == list(range(1, 12))
    assert await scalar(conn, "SELECT status FROM registry_versions WHERE registry_id = %s AND version = 11", target) == "draft"
    cur = await conn.execute(
        "SELECT v.version FROM registry r JOIN registry_versions v ON v.id = r.current_version_id WHERE r.id = %s",
        (target,),
    )
    assert await cur.fetchone() == (10,)


async def test_ac15_version_depended_on_by_another_version_is_409_with_version_dep(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    target = await new_agent(conn, caller, "target-agent")
    await publish_agent_versions(conn, caller, target, 10)
    dependant = await new_agent(conn, caller, "billing-agent")
    await publish_agent_versions(conn, caller, dependant, 7)
    await add_dep(
        conn, tenant, await version_id_of(conn, dependant, 7), await version_id_of(conn, target, 1)
    )
    await create_draft(conn, caller, target)
    with pytest.raises(ApiError) as exc:
        await publish(conn, caller, target, 11)
    assert exc.value.error == "version_in_use"
    assert exc.value.extra["referenced_by"] == [
        {"kind": "version_dep", "resource": "billing-agent", "resource_id": str(dependant), "version": 7}
    ]
    assert await retained(conn, target) == list(range(1, 12))


async def test_version_in_use_lists_every_referrer_kind(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    target = await new_agent(conn, caller, "target-agent")
    await publish(conn, caller, target, 1)
    vid = await version_id_of(conn, target, 1)
    assert await version_in_use(conn, vid) == []
    source = await new_agent(conn, caller, "support-bot")
    await link_pin(conn, tenant, source, target, vid)
    dependant = await new_agent(conn, caller, "billing-agent")
    await publish(conn, caller, dependant, 1)
    await add_dep(conn, tenant, await version_id_of(conn, dependant, 1), vid)
    kinds = sorted(r["kind"] for r in await version_in_use(conn, vid))
    assert kinds == ["link_pin", "version_dep"]


async def test_pruning_with_no_removable_version_is_409_version_limit_reached(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, set_limit: SetLimit
) -> None:
    await set_limit("max_published_versions", 1)
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish(conn, caller, rid, 1)
    await create_draft(conn, caller, rid)
    with pytest.raises(ApiError) as exc:
        await publish(conn, caller, rid, 2, make_current=False)
    assert (exc.value.status, exc.value.error) == (409, "version_limit_reached")
    assert await retained(conn, rid) == [1, 2]


async def test_pruning_a_skill_version_releases_its_file(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, set_limit: SetLimit
) -> None:
    await set_limit("max_published_versions", 2, "skill")
    caller = caller_for(tenant)
    rid = await new_skill(conn, caller, "refund-flow", "body 1")
    await publish_skill_versions(conn, caller, rid, "refund-flow", 3)
    assert await retained(conn, rid) == [2, 3]
    assert await scalar(conn, "SELECT count(*) FROM skill_files") == 2


async def test_pruning_keeps_a_file_still_used_by_a_surviving_version(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, set_limit: SetLimit
) -> None:
    await set_limit("max_published_versions", 2, "skill")
    caller = caller_for(tenant)
    rid = await new_skill(conn, caller)
    await publish(conn, caller, rid, 1)
    await create_draft(conn, caller, rid)
    await publish(conn, caller, rid, 2)
    await create_draft(conn, caller, rid)
    await publish(conn, caller, rid, 3)
    assert await retained(conn, rid) == [2, 3]
    assert await scalar(conn, "SELECT count(*) FROM skill_files") == 1


async def test_delete_published_non_current_version_succeeds_when_unreferenced(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish_agent_versions(conn, caller, rid, 3)
    await delete_version(conn, caller, rid, 1)
    assert await retained(conn, rid) == [2, 3]
    assert [v["version"] for v in await list_versions(conn, caller, rid)] == [2, 3]


async def test_delete_published_pinned_version_is_409_version_in_use(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    target = await new_agent(conn, caller, "target-agent")
    await publish_agent_versions(conn, caller, target, 2)
    source = await new_agent(conn, caller, "support-bot")
    await link_pin(conn, tenant, source, target, await version_id_of(conn, target, 1))
    with pytest.raises(ApiError) as exc:
        await delete_version(conn, caller, target, 1)
    assert (exc.value.status, exc.value.error) == (409, "version_in_use")
    assert exc.value.extra["version_to_remove"] == 1
    assert [r["kind"] for r in exc.value.extra["referenced_by"]] == ["link_pin"]
    assert await retained(conn, target) == [1, 2]


async def test_parallel_publishes_of_the_same_resource_serialise(
    pool: Pool, tenant: uuid.UUID, set_limit: SetLimit
) -> None:
    await set_limit("max_published_versions", 3)
    caller = caller_for(tenant)
    async with tenant_transaction(pool, tenant) as setup:
        rid = await new_agent(setup, caller)
        await publish_agent_versions(setup, caller, rid, 3)
        for n in (4, 5):
            await create_draft(setup, caller, rid)
            await replace_draft(setup, caller, rid, n, spec=spec_with(f"v{n}"))

    async def publish_in_own_transaction(n: int) -> None:
        async with tenant_transaction(pool, tenant) as c:
            await publish(c, caller, rid, n)

    await asyncio.wait_for(
        asyncio.gather(publish_in_own_transaction(4), publish_in_own_transaction(5)), 10
    )
    async with tenant_transaction(pool, tenant) as check:
        assert await retained(check, rid) == [3, 4, 5]
        assert await scalar(check, "SELECT count(*) FROM agents WHERE registry_id = %s", rid) == 3


async def test_api_delete_version_conflicts_and_success(
    make_client: MakeClient, tenant: uuid.UUID
) -> None:
    async with make_client(tenant) as c:
        rid = (await c.post(BASE, json=agent_body())).json()["id"]
        await c.post(f"{BASE}/{rid}/versions/1/publish")
        r = await c.delete(f"{BASE}/{rid}/versions/1")
        assert r.status_code == 409
        assert r.json()["error"] == "version_is_current"
        await c.post(f"{BASE}/{rid}/versions")
        await c.post(f"{BASE}/{rid}/versions/2/publish")
        assert (await c.delete(f"{BASE}/{rid}/versions/1")).status_code == 204
        assert (await c.get(f"{BASE}/{rid}/versions/1")).status_code == 404
