import hashlib
import io
import uuid
import zipfile
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio

from krep.api.errors import ApiError
from krep.identity.resolve import Caller
from krep.policy.parser import parse
from krep.policy.store import write_policy
from krep.registry.resources import (
    can_edit,
    create_resource,
    delete_resource,
    get_visible,
    list_resources,
    lock_resource,
    set_archived,
    update_resource,
)

AGENT_SPEC: dict[str, Any] = {"model": "claude-sonnet-5-5", "system_prompt": "You help."}


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
        "tags": ["billing"],
        "visibility": "private",
        "spec": AGENT_SPEC,
        **extra,
    }


def skill_body(slug: str = "refund-flow", archive: bytes | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "type": "skill",
        "slug": slug,
        "name": "Refund Flow",
        "archive": archive if archive is not None else skill_zip(slug),
        **extra,
    }


@pytest.fixture
def tenant() -> uuid.UUID:
    return uuid.uuid4()


@pytest_asyncio.fixture
async def conn(app_conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> AsyncIterator[psycopg.AsyncConnection]:
    await app_conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
    yield app_conn


def caller_for(
    tenant: uuid.UUID, user: str = "u1", admin: bool = False, doc: dict[str, Any] | None = None
) -> Caller:
    return Caller(tenant, user, doc or {"token": {}, "principal": {}}, True, admin)


async def count(conn: psycopg.AsyncConnection, table: str) -> int:
    cur = await conn.execute(f"SELECT count(*) FROM {table}")  # type: ignore[arg-type]
    row = await cur.fetchone()
    assert row
    return row[0]


async def publish_raw(conn: psycopg.AsyncConnection, resource_id: uuid.UUID) -> None:
    cur = await conn.execute(
        "UPDATE registry_versions SET status = 'published', published_at = now(), "
        "content_hash = repeat('a', 64) WHERE registry_id = %s RETURNING id",
        (resource_id,),
    )
    row = await cur.fetchone()
    assert row
    await conn.execute(
        "UPDATE registry SET status = 'published', current_version_id = %s WHERE id = %s",
        (row[0], resource_id),
    )


async def test_create_agent_returns_7_2_shape_and_writes_all_rows(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    out = await create_resource(conn, caller_for(tenant), agent_body())
    assert out["type"] == "agent"
    assert out["slug"] == "refund-assistant"
    assert out["status"] == "draft"
    assert out["visibility"] == "private"
    assert out["current_version"] is None
    assert out["version"] == {"version": 1, "status": "draft"}
    cur = await conn.execute(
        "SELECT r.next_version, r.created_by, v.version, v.status, a.model "
        "FROM registry r JOIN registry_versions v ON v.registry_id = r.id "
        "JOIN agents a ON a.version_id = v.id WHERE r.id = %s",
        (out["id"],),
    )
    assert await cur.fetchone() == (2, "u1", 1, "draft", "claude-sonnet-5-5")


async def test_create_duplicate_slug_is_409_slug_taken_and_leaves_one_row(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await create_resource(conn, caller_for(tenant), agent_body())
    with pytest.raises(ApiError) as exc:
        await create_resource(conn, caller_for(tenant), agent_body())
    assert (exc.value.status, exc.value.error) == (409, "slug_taken")
    assert await count(conn, "registry") == 1
    assert await count(conn, "registry_versions") == 1


async def test_create_invalid_spec_is_422_with_field_list_and_writes_nothing(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    body = agent_body(spec={"model": ""}, name="")
    with pytest.raises(ApiError) as exc:
        await create_resource(conn, caller_for(tenant), body)
    assert (exc.value.status, exc.value.error) == (422, "validation_failed")
    fields = {e["field"] for e in exc.value.extra["errors"]}
    assert {"name", "spec.model", "spec.system_prompt"} <= fields
    assert await count(conn, "registry") == 0


async def test_create_unknown_type_is_422(conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> None:
    with pytest.raises(ApiError) as exc:
        await create_resource(conn, caller_for(tenant), agent_body(type="nope"))
    assert exc.value.status == 422
    assert exc.value.extra["errors"][0]["field"] == "type"


async def test_create_ignores_forged_tenant_id_ac1(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    other = uuid.uuid4()
    out = await create_resource(conn, caller_for(tenant), agent_body(tenant_id=str(other)))
    cur = await conn.execute("SELECT tenant_id FROM registry WHERE id = %s", (out["id"],))
    row = await cur.fetchone()
    assert row and row[0] == tenant


async def test_create_skill_writes_registry_version_skill_and_file(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    data = skill_zip()
    out = await create_resource(conn, caller_for(tenant), skill_body(archive=data))
    assert out["version"] == {"version": 1, "status": "draft"}
    sha = hashlib.sha256(data).hexdigest()
    cur = await conn.execute(
        "SELECT s.content_sha256, f.size_bytes, r.description FROM skills s "
        "JOIN skill_files f USING (tenant_id, content_sha256) "
        "JOIN registry r ON r.id = s.registry_id WHERE s.registry_id = %s",
        (out["id"],),
    )
    assert await cur.fetchone() == (sha, len(data), "Handles refunds.")


async def test_create_skill_explicit_description_wins_over_frontmatter(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    out = await create_resource(conn, caller_for(tenant), skill_body(description="Mine."))
    cur = await conn.execute("SELECT description FROM registry WHERE id = %s", (out["id"],))
    row = await cur.fetchone()
    assert row and row[0] == "Mine."


async def test_create_skill_rejected_archive_leaves_nothing_behind(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    with pytest.raises(ApiError) as exc:
        await create_resource(conn, caller_for(tenant), skill_body(archive=b"not a zip"))
    assert (exc.value.status, exc.value.error) == (422, "validation_failed")
    assert exc.value.extra["errors"][0]["field"].startswith("archive")
    for table in ("registry", "registry_versions", "skills", "skill_files"):
        assert await count(conn, table) == 0


async def test_create_skill_slug_must_match_archive_directory(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    with pytest.raises(ApiError) as exc:
        await create_resource(conn, caller_for(tenant), skill_body("other-name", skill_zip("refund-flow")))
    assert exc.value.status == 422
    assert await count(conn, "registry") == 0


async def test_create_skill_with_json_spec_is_422(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    body = skill_body()
    body.pop("archive")
    body["spec"] = {"instructions": "x"}
    with pytest.raises(ApiError) as exc:
        await create_resource(conn, caller_for(tenant), body)
    assert exc.value.status == 422
    assert {"field": "spec", "message": "skills take an archive"} in exc.value.extra["errors"]


async def test_ac16_51st_draft_is_409_with_limit_and_current(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    for i in range(50):
        await create_resource(conn, caller, agent_body(f"agent-{i:02d}"))
    with pytest.raises(ApiError) as exc:
        await create_resource(conn, caller, agent_body("agent-50"))
    assert (exc.value.status, exc.value.error) == (409, "draft_limit_reached")
    assert exc.value.extra["limit"] == 50
    assert exc.value.extra["current"] == 50


async def test_draft_cap_is_per_type(conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> None:
    caller = caller_for(tenant)
    for i in range(50):
        await create_resource(conn, caller, agent_body(f"agent-{i:02d}"))
    out = await create_resource(conn, caller, skill_body())
    assert out["type"] == "skill"


@pytest.mark.parametrize("visibility", ["private", "tenant"])
async def test_ac5_get_visible_matrix_private_and_tenant(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, visibility: str
) -> None:
    out = await create_resource(conn, caller_for(tenant), agent_body(visibility=visibility))
    await publish_raw(conn, out["id"])
    creator = await get_visible(conn, caller_for(tenant, "u1"), out["id"])
    other = await get_visible(conn, caller_for(tenant, "u2"), out["id"])
    assert creator is not None
    assert (other is not None) == (visibility == "tenant")


async def test_ac5_get_visible_restricted_follows_policy(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    policy = await write_policy(conn, tenant, "billing", parse('token.department == "billing"'), "admin")
    out = await create_resource(
        conn, caller_for(tenant), agent_body(visibility="restricted", policy_id=policy.id)
    )
    await publish_raw(conn, out["id"])
    match = caller_for(tenant, "u2", doc={"token": {"department": "billing"}, "principal": {}})
    miss = caller_for(tenant, "u3", doc={"token": {"department": "sales"}, "principal": {}})
    assert await get_visible(conn, match, out["id"]) is not None
    assert await get_visible(conn, miss, out["id"]) is None


async def test_ac5_get_visible_other_tenant_is_none(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    out = await create_resource(conn, caller_for(tenant), agent_body(visibility="tenant"))
    await publish_raw(conn, out["id"])
    stranger = uuid.uuid4()
    await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(stranger),))
    assert await get_visible(conn, caller_for(stranger, "u1"), out["id"]) is None


async def test_ac6_get_visible_missing_id_is_none(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    assert await get_visible(conn, caller_for(tenant), uuid.uuid4()) is None


async def test_draft_visible_only_to_owner_and_admin(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    out = await create_resource(conn, caller_for(tenant), agent_body(visibility="tenant"))
    assert await get_visible(conn, caller_for(tenant, "u1"), out["id"]) is not None
    assert await get_visible(conn, caller_for(tenant, "u2", admin=True), out["id"]) is not None
    assert await get_visible(conn, caller_for(tenant, "u2"), out["id"]) is None


async def test_get_visible_includes_current_version_summary(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    out = await create_resource(conn, caller_for(tenant), agent_body())
    draft = await get_visible(conn, caller_for(tenant), out["id"])
    assert draft and draft["current_version"] is None
    await publish_raw(conn, out["id"])
    published = await get_visible(conn, caller_for(tenant), out["id"])
    assert published and published["current_version"]["version"] == 1
    assert published["current_version"]["content_hash"] == "a" * 64


async def test_can_edit_is_owner_or_admin(conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> None:
    out = await create_resource(conn, caller_for(tenant), agent_body())
    row = await lock_resource(conn, out["id"])
    assert await can_edit(caller_for(tenant, "u1"), row)
    assert await can_edit(caller_for(tenant, "u2", admin=True), row)
    assert not await can_edit(caller_for(tenant, "u2"), row)


async def test_lock_resource_missing_is_404(conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> None:
    with pytest.raises(ApiError) as exc:
        await lock_resource(conn, uuid.uuid4())
    assert exc.value.status == 404


async def test_list_shows_own_with_drafts_and_admin_sees_all(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    mine = await create_resource(conn, caller_for(tenant, "u1"), agent_body("mine-agent"))
    theirs = await create_resource(conn, caller_for(tenant, "u2"), agent_body("their-agent"))
    skill = await create_resource(conn, caller_for(tenant, "u1"), skill_body())
    own = await list_resources(conn, caller_for(tenant, "u1"), type=None, status=None)
    assert {i["id"] for i in own} == {mine["id"], skill["id"]}
    everything = await list_resources(conn, caller_for(tenant, "u3", admin=True), type=None, status=None)
    assert {i["id"] for i in everything} == {mine["id"], theirs["id"], skill["id"]}
    only_agents = await list_resources(conn, caller_for(tenant, "u1"), type="agent", status="draft")
    assert [i["id"] for i in only_agents] == [mine["id"]]
    assert await list_resources(conn, caller_for(tenant, "u1"), type=None, status="published") == []


async def test_update_restricted_requires_policy_id(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    out = await create_resource(conn, caller_for(tenant), agent_body())
    with pytest.raises(ApiError) as exc:
        await update_resource(conn, caller_for(tenant), out["id"], {"visibility": "restricted"})
    assert (exc.value.status, exc.value.error) == (422, "validation_failed")
    assert exc.value.extra["errors"][0]["field"] == "policy_id"


async def test_update_switching_away_from_restricted_keeps_policy_id(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    policy = await write_policy(conn, tenant, "p", parse('token.a == "b"'), "admin")
    out = await create_resource(
        conn, caller_for(tenant), agent_body(visibility="restricted", policy_id=policy.id)
    )
    updated = await update_resource(conn, caller_for(tenant), out["id"], {"visibility": "tenant"})
    assert updated["visibility"] == "tenant"
    cur = await conn.execute("SELECT policy_id FROM registry WHERE id = %s", (out["id"],))
    row = await cur.fetchone()
    assert row and row[0] == policy.id


async def test_update_unknown_policy_is_422(conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> None:
    out = await create_resource(conn, caller_for(tenant), agent_body())
    with pytest.raises(ApiError) as exc:
        await update_resource(
            conn, caller_for(tenant), out["id"], {"visibility": "restricted", "policy_id": uuid.uuid4()}
        )
    assert exc.value.status == 422
    assert exc.value.extra["errors"][0]["field"] == "policy_id"


async def test_update_applies_fields_and_stamps_updater(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    out = await create_resource(conn, caller_for(tenant), agent_body())
    updated = await update_resource(
        conn,
        caller_for(tenant, "u9", admin=True),
        out["id"],
        {"name": "Renamed", "tags": ["x"], "meta": {"k": 1}, "description": "New."},
    )
    assert (updated["name"], updated["tags"], updated["meta"], updated["description"]) == (
        "Renamed",
        ["x"],
        {"k": 1},
        "New.",
    )
    cur = await conn.execute("SELECT updated_by FROM registry WHERE id = %s", (out["id"],))
    row = await cur.fetchone()
    assert row and row[0] == "u9"


async def test_update_by_non_owner_is_403_when_visible_and_404_when_hidden(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    shared = await create_resource(conn, caller_for(tenant, "u1"), agent_body("shared-one", visibility="tenant"))
    await publish_raw(conn, shared["id"])
    hidden = await create_resource(conn, caller_for(tenant, "u1"), agent_body("hidden-one"))
    await publish_raw(conn, hidden["id"])
    with pytest.raises(ApiError) as visible:
        await update_resource(conn, caller_for(tenant, "u2"), shared["id"], {"name": "x"})
    with pytest.raises(ApiError) as invisible:
        await update_resource(conn, caller_for(tenant, "u2"), hidden["id"], {"name": "x"})
    assert visible.value.status == 403
    assert invisible.value.status == 404


async def test_archive_hides_from_other_users_but_owner_still_reads(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    out = await create_resource(conn, caller_for(tenant, "u1"), agent_body(visibility="tenant"))
    await publish_raw(conn, out["id"])
    archived = await set_archived(conn, caller_for(tenant, "u1"), out["id"], True)
    assert archived["status"] == "archived"
    assert await get_visible(conn, caller_for(tenant, "u2"), out["id"]) is None
    assert await get_visible(conn, caller_for(tenant, "u1"), out["id"]) is not None
    restored = await set_archived(conn, caller_for(tenant, "u1"), out["id"], False)
    assert restored["status"] == "published"
    assert await get_visible(conn, caller_for(tenant, "u2"), out["id"]) is not None


async def test_archive_requires_matching_state(conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> None:
    out = await create_resource(conn, caller_for(tenant), agent_body())
    with pytest.raises(ApiError) as draft:
        await set_archived(conn, caller_for(tenant), out["id"], True)
    assert (draft.value.status, draft.value.error) == (409, "invalid_state")
    await publish_raw(conn, out["id"])
    with pytest.raises(ApiError) as published:
        await set_archived(conn, caller_for(tenant), out["id"], False)
    assert published.value.status == 409


async def test_archive_by_non_owner_is_403(conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> None:
    out = await create_resource(conn, caller_for(tenant, "u1"), agent_body(visibility="tenant"))
    await publish_raw(conn, out["id"])
    with pytest.raises(ApiError) as exc:
        await set_archived(conn, caller_for(tenant, "u2"), out["id"], True)
    assert exc.value.status == 403


async def test_delete_agent_without_links_removes_rows(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    out = await create_resource(conn, caller_for(tenant), agent_body())
    await delete_resource(conn, caller_for(tenant), out["id"])
    for table in ("registry", "registry_versions", "agents"):
        assert await count(conn, table) == 0


async def test_ac22_delete_with_inbound_link_is_409_resource_in_use_with_referrers(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    skill = await create_resource(conn, caller_for(tenant), skill_body())
    agent = await create_resource(conn, caller_for(tenant), agent_body())
    await conn.execute(
        "INSERT INTO registry_links (tenant_id, source_id, target_id, relation, origin_id, created_by) "
        "VALUES (%s, %s, %s, 'uses', %s, 'u1')",
        (tenant, agent["id"], skill["id"], agent["id"]),
    )
    with pytest.raises(ApiError) as exc:
        await delete_resource(conn, caller_for(tenant), skill["id"])
    assert (exc.value.status, exc.value.error) == (409, "resource_in_use")
    assert [r["id"] for r in exc.value.extra["referrers"]] == [agent["id"]]
    assert await count(conn, "registry") == 2


async def test_delete_removes_outgoing_links(conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> None:
    skill = await create_resource(conn, caller_for(tenant), skill_body())
    agent = await create_resource(conn, caller_for(tenant), agent_body())
    await conn.execute(
        "INSERT INTO registry_links (tenant_id, source_id, target_id, relation, origin_id, created_by) "
        "VALUES (%s, %s, %s, 'uses', %s, 'u1')",
        (tenant, agent["id"], skill["id"], agent["id"]),
    )
    await delete_resource(conn, caller_for(tenant), agent["id"])
    assert await count(conn, "registry_links") == 0


async def test_delete_skill_releases_archive_unless_shared(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    only = await create_resource(conn, caller_for(tenant), skill_body("only-flow"))
    assert await count(conn, "skill_files") == 1
    await delete_resource(conn, caller_for(tenant), only["id"])
    assert await count(conn, "skills") == 0
    assert await count(conn, "skill_files") == 0


async def test_delete_skill_keeps_archive_shared_with_another_skill(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    data = skill_zip("twin-flow")
    first = await create_resource(conn, caller_for(tenant), skill_body("twin-flow", data))
    await conn.execute(
        "INSERT INTO registry (tenant_id, type, slug, name, created_by, updated_by) "
        "VALUES (%s, 'skill', 'twin-copy', 'Copy', 'u1', 'u1') RETURNING id",
        (tenant,),
    )
    cur = await conn.execute("SELECT id FROM registry WHERE slug = 'twin-copy'")
    copy_id = (await cur.fetchone() or [None])[0]
    cur = await conn.execute(
        "INSERT INTO registry_versions (registry_id, tenant_id, version, created_by) "
        "VALUES (%s, %s, 1, 'u1') RETURNING id",
        (copy_id, tenant),
    )
    version_id = (await cur.fetchone() or [None])[0]
    await conn.execute(
        "INSERT INTO skills (version_id, registry_id, tenant_id, content_sha256) VALUES (%s, %s, %s, %s)",
        (version_id, copy_id, tenant, hashlib.sha256(data).hexdigest()),
    )
    await delete_resource(conn, caller_for(tenant), first["id"])
    assert await count(conn, "skill_files") == 1
    assert await count(conn, "skills") == 1


async def test_delete_by_non_owner_is_403(conn: psycopg.AsyncConnection, tenant: uuid.UUID) -> None:
    out = await create_resource(conn, caller_for(tenant, "u1"), agent_body(visibility="tenant"))
    await publish_raw(conn, out["id"])
    with pytest.raises(ApiError) as exc:
        await delete_resource(conn, caller_for(tenant, "u2"), out["id"])
    assert exc.value.status == 403
