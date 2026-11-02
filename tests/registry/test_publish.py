import asyncio
import uuid
from typing import Any

import psycopg
import pytest

from krep.api.errors import ApiError
from krep.db.tenant import tenant_transaction
from krep.registry import publish as publish_module
from krep.registry.publish import publish, set_current
from krep.registry.resources import create_resource, set_archived
from krep.registry.specs import content_hash
from krep.registry.versions import create_draft, delete_version, replace_draft
from tests.registry.conftest import (
    MakeClient,
    Pool,
    agent_body,
    caller_for,
    new_agent,
    new_skill,
    publish_agent_versions,
    scalar,
    skill_zip,
    spec_with,
)

BASE = "/v1/registry"


async def test_publish_sets_version_and_resource_state(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    out = await publish(conn, caller, rid, 1)
    assert out["version"]["version"] == 1
    assert out["version"]["status"] == "published"
    cur = await conn.execute(
        "SELECT v.status, v.published_at IS NOT NULL, v.content_hash, r.status, "
        "r.current_version_id = v.id FROM registry_versions v "
        "JOIN registry r ON r.id = v.registry_id WHERE r.id = %s",
        (rid,),
    )
    fetched = await cur.fetchone()
    assert fetched is not None
    status, has_ts, digest, resource_status, is_current = fetched
    assert (status, has_ts, resource_status, is_current) == (
        "published",
        True,
        "published",
        True,
    )
    full_spec: dict[str, Any] = {
        "model": "claude-sonnet-5-5",
        "model_config": {},
        "system_prompt": "You help.",
        "input_schema": {},
        "output_schema": {},
        "hitl_rules": [],
        "runtime_config": {},
        "tool_refs": [],
    }
    assert digest == content_hash("agent", full_spec)
    assert out["version"]["content_hash"] == digest


async def test_publish_hash_ignores_omitted_defaults(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    a = await new_agent(conn, caller, "agent-a")
    b = (
        await create_resource(
            conn,
            caller,
            agent_body(
                "agent-b",
                spec={
                    "model": "claude-sonnet-5-5",
                    "system_prompt": "You help.",
                    "model_config": {},
                    "tool_refs": [],
                },
            ),
        )
    )["id"]
    one = await publish(conn, caller, a, 1)
    two = await publish(conn, caller, b, 1)
    assert one["version"]["content_hash"] == two["version"]["content_hash"]


async def test_publish_skill_hash_derives_from_content_sha256(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_skill(conn, caller)
    sha = await scalar(
        conn, "SELECT content_sha256 FROM skills WHERE registry_id = %s", rid
    )
    out = await publish(conn, caller, rid, 1)
    assert out["version"]["content_hash"] == content_hash(
        "skill", {"content_sha256": sha}
    )


async def test_publish_non_draft_is_rejected(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish(conn, caller, rid, 1)
    with pytest.raises(ApiError) as exc:
        await publish(conn, caller, rid, 1)
    assert (exc.value.status, exc.value.error) == (409, "version_immutable")


async def test_publish_unknown_version_is_404(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    with pytest.raises(ApiError) as exc:
        await publish(conn, caller, rid, 5)
    assert exc.value.status == 404


async def test_make_current_false_leaves_current_unchanged(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish(conn, caller, rid, 1)
    await create_draft(conn, caller, rid)
    out = await publish(conn, caller, rid, 2, make_current=False)
    assert out["current_version"] == 1
    cur = await conn.execute(
        "SELECT v.version FROM registry r JOIN registry_versions v ON v.id = r.current_version_id "
        "WHERE r.id = %s",
        (rid,),
    )
    assert await cur.fetchone() == (1,)


async def test_first_publish_with_make_current_false_still_becomes_current(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    out = await publish(conn, caller, rid, 1, make_current=False)
    assert out["current_version"] == 1
    assert (
        await scalar(conn, "SELECT status FROM registry WHERE id = %s", rid)
        == "published"
    )


async def test_publishing_identical_spec_reports_no_changes_since_previous(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    first = await publish(conn, caller, rid, 1)
    assert first["warnings"] == []
    await create_draft(conn, caller, rid)
    second = await publish(conn, caller, rid, 2)
    assert second["warnings"] == ["no changes since v1"]
    await create_draft(conn, caller, rid)
    await replace_draft(conn, caller, rid, 3, spec=spec_with("different"))
    assert (await publish(conn, caller, rid, 3))["warnings"] == []


async def test_publish_of_a_draft_whose_spec_went_invalid_is_422_and_changes_nothing(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await conn.execute("UPDATE agents SET model = '   ' WHERE registry_id = %s", (rid,))
    with pytest.raises(ApiError) as exc:
        await publish(conn, caller, rid, 1)
    assert exc.value.status == 422
    assert {
        "field": "spec.model",
        "message": "required non-empty string",
    } in exc.value.extra["errors"]
    assert (
        await scalar(
            conn, "SELECT status FROM registry_versions WHERE registry_id = %s", rid
        )
        == "draft"
    )
    assert (
        await scalar(conn, "SELECT status FROM registry WHERE id = %s", rid) == "draft"
    )


async def test_publish_on_archived_resource_is_rejected(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish(conn, caller, rid, 1)
    await set_archived(conn, caller, rid, True)
    await create_draft(conn, caller, rid)
    with pytest.raises(ApiError) as exc:
        await publish(conn, caller, rid, 2)
    assert (exc.value.status, exc.value.error) == (409, "resource_archived")
    assert (
        await scalar(conn, "SELECT status FROM registry WHERE id = %s", rid)
        == "archived"
    )


async def test_publish_calls_freeze_dependencies_with_the_version_id(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[uuid.UUID] = []

    async def spy(_: psycopg.AsyncConnection, version_id: uuid.UUID) -> None:
        seen.append(version_id)

    monkeypatch.setattr(publish_module, "freeze_dependencies", spy)
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish(conn, caller, rid, 1)
    assert seen == [
        await scalar(
            conn, "SELECT id FROM registry_versions WHERE registry_id = %s", rid
        )
    ]


async def test_publish_by_non_owner_is_403_visible_or_404_hidden(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    owner, other = caller_for(tenant, "u1"), caller_for(tenant, "u2")
    rid = await new_agent(conn, owner)
    with pytest.raises(ApiError) as exc:
        await publish(conn, other, rid, 1)
    assert exc.value.status == 404
    await publish(conn, owner, rid, 1)
    await conn.execute(
        "UPDATE registry SET visibility = 'tenant' WHERE id = %s", (rid,)
    )
    await create_draft(conn, owner, rid)
    with pytest.raises(ApiError) as exc2:
        await publish(conn, other, rid, 2)
    assert exc2.value.status == 403


async def test_ac14_published_version_and_subtype_rows_cannot_be_updated(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    await publish(conn, caller, agent, 1)
    await publish(conn, caller, skill, 1)
    for statement, rid in (
        ("UPDATE registry_versions SET created_by = 'x' WHERE registry_id = %s", agent),
        ("UPDATE agents SET model = 'x' WHERE registry_id = %s", agent),
        ("UPDATE skills SET registry_id = registry_id WHERE registry_id = %s", skill),
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            async with conn.transaction():
                await conn.execute(statement, (rid,))  # type: ignore[arg-type]


async def test_ac18_repoint_current_to_older_retained_version(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish_agent_versions(conn, caller, rid, 3)
    out = await set_current(conn, caller, rid, 1)
    assert out["current_version"] == 1
    cur = await conn.execute(
        "SELECT v.version FROM registry r JOIN registry_versions v ON v.id = r.current_version_id "
        "WHERE r.id = %s",
        (rid,),
    )
    assert await cur.fetchone() == (1,)


async def test_ac18_repoint_to_draft_or_missing_version_fails(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish(conn, caller, rid, 1)
    await create_draft(conn, caller, rid)
    with pytest.raises(ApiError) as draft:
        await set_current(conn, caller, rid, 2)
    with pytest.raises(ApiError) as missing:
        await set_current(conn, caller, rid, 9)
    assert (draft.value.status, draft.value.error) == (409, "version_not_published")
    assert missing.value.status == 404


async def test_ac18_repoint_to_pruned_version_fails(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish_agent_versions(conn, caller, rid, 11)
    with pytest.raises(ApiError) as exc:
        await set_current(conn, caller, rid, 1)
    assert exc.value.status == 404


async def test_ac18_deleting_the_current_version_is_rejected(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    rid = await new_agent(conn, caller)
    await publish(conn, caller, rid, 1)
    with pytest.raises(ApiError) as exc:
        await delete_version(conn, caller, rid, 1)
    assert (exc.value.status, exc.value.error) == (409, "version_is_current")
    assert (
        await scalar(
            conn, "SELECT count(*) FROM registry_versions WHERE registry_id = %s", rid
        )
        == 1
    )


async def test_edit_racing_a_publish_gets_version_immutable(
    pool: Pool, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    async with tenant_transaction(pool, tenant) as setup:
        rid = await new_agent(setup, caller)

    async def edit() -> ApiError:
        async with tenant_transaction(pool, tenant) as other:
            with pytest.raises(ApiError) as exc:
                await replace_draft(other, caller, rid, 1, spec=spec_with("too late"))
            return exc.value

    async with tenant_transaction(pool, tenant) as publisher:
        await publish(publisher, caller, rid, 1)
        task = asyncio.create_task(edit())
        await asyncio.sleep(0.3)
        assert not task.done()
    error = await asyncio.wait_for(task, 5)
    assert error.error == "version_immutable"
    async with tenant_transaction(pool, tenant) as check:
        assert (
            await scalar(
                check, "SELECT system_prompt FROM agents WHERE registry_id = %s", rid
            )
            == "You help."
        )


async def test_api_publish_and_current(
    make_client: MakeClient, tenant: uuid.UUID
) -> None:
    body = {k: v for k, v in agent_body().items()}
    async with make_client(tenant) as c:
        rid = (await c.post(BASE, json=body)).json()["id"]
        r = await c.post(f"{BASE}/{rid}/versions/1/publish")
        assert r.status_code == 200, r.text
        assert r.json()["version"]["status"] == "published"
        assert r.json()["current_version"] == 1
        await c.post(f"{BASE}/{rid}/versions")
        r = await c.post(
            f"{BASE}/{rid}/versions/2/publish", json={"make_current": False}
        )
        assert r.status_code == 200
        assert r.json()["current_version"] == 1
        r = await c.post(f"{BASE}/{rid}/current", json={"version": 2})
        assert r.status_code == 200
        assert (await c.get(f"{BASE}/{rid}")).json()["current_version"]["version"] == 2
        bad = await c.post(f"{BASE}/{rid}/current", json={})
        assert bad.status_code == 422
        gone = await c.post(f"{BASE}/{rid}/current", json={"version": 9})
        assert gone.status_code == 404
        again = await c.post(f"{BASE}/{rid}/versions/1/publish")
        assert again.status_code == 409
        assert again.json()["error"] == "version_immutable"


async def test_api_skill_publish_and_archive_survive(
    make_client: MakeClient, tenant: uuid.UUID, pool: Pool
) -> None:
    caller = caller_for(tenant)
    async with tenant_transaction(pool, tenant) as setup:
        rid = await new_skill(setup, caller)
    async with make_client(tenant) as c:
        assert (await c.post(f"{BASE}/{rid}/versions/1/publish")).status_code == 200
        r = await c.put(
            f"{BASE}/{rid}/versions/1",
            files={
                "archive": ("a.zip", skill_zip("refund-flow", "z"), "application/zip")
            },
        )
        assert r.status_code == 409
        assert r.json()["error"] == "version_immutable"
