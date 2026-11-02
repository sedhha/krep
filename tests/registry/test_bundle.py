import uuid
from typing import Any

import psycopg
import pytest

from krep.api.errors import ApiError
from krep.registry.bundle import resolve_bundle
from krep.registry.links import create_link
from krep.registry.publish import publish
from krep.registry.resources import set_archived
from krep.registry.versions import create_draft
from tests.registry.conftest import (
    MakeClient,
    agent_body,
    caller_for,
    new_agent,
    new_skill,
    publish_skill_versions,
    skill_zip,
    version_id_of,
)


async def published_skill(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, slug: str
) -> uuid.UUID:
    caller = caller_for(tenant)
    skill = await new_skill(conn, caller, slug)
    await publish(conn, caller, skill, 1)
    return skill


async def dep(
    conn: psycopg.AsyncConnection,
    tenant: uuid.UUID,
    source: uuid.UUID,
    target: uuid.UUID,
    auto_load: bool = True,
) -> None:
    await conn.execute(
        "INSERT INTO registry_version_deps (version_id, depends_on_version_id, tenant_id, "
        "relation, auto_load) VALUES (%s, %s, %s, 'uses', %s)",
        (
            await version_id_of(conn, source, 1),
            await version_id_of(conn, target, 1),
            tenant,
            auto_load,
        ),
    )


async def agent_using(
    conn: psycopg.AsyncConnection,
    tenant: uuid.UUID,
    skills: list[uuid.UUID],
    auto_load: bool = True,
    publish_it: bool = True,
) -> uuid.UUID:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    for skill in skills:
        await create_link(conn, caller, agent, skill, "uses", "out", None, auto_load)
    if publish_it:
        await publish(conn, caller, agent, 1)
    return agent


def slugs(bundle: dict[str, Any]) -> list[str]:
    return [d["slug"] for d in bundle["dependencies"]]


async def not_found_of(coro: Any) -> ApiError:
    with pytest.raises(ApiError) as exc:
        await coro
    return exc.value


async def test_published_root_returns_frozen_auto_load_deps_only(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    loaded = await published_skill(conn, tenant, "loaded-skill")
    lazy = await published_skill(conn, tenant, "lazy-skill")
    agent = await new_agent(conn, caller)
    await create_link(conn, caller, agent, loaded, "uses", "out", None, True)
    await create_link(conn, caller, agent, lazy, "uses", "out", None, False)
    await publish(conn, caller, agent, 1)
    bundle = await resolve_bundle(conn, caller, agent, None)
    assert bundle["root"]["id"] == agent and bundle["root"]["version"] == 1
    assert bundle["root"]["type"] == "agent" and "system_prompt" in bundle["root"]["spec"]
    assert slugs(bundle) == ["loaded-skill"]
    dependency = bundle["dependencies"][0]
    assert (dependency["id"], dependency["type"], dependency["version"]) == (loaded, "skill", 1)
    assert dependency["relation"] == "uses"


async def test_skill_dependency_spec_is_a_reference_never_zip_bytes(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    skill = await published_skill(conn, tenant, "refund-flow")
    agent = await agent_using(conn, tenant, [skill])
    bundle = await resolve_bundle(conn, caller_for(tenant), agent, None)
    spec = bundle["dependencies"][0]["spec"]
    data = skill_zip("refund-flow")
    assert set(spec) == {"content_sha256", "size_bytes", "archive_path"}
    assert spec["size_bytes"] == len(data)
    assert spec["archive_path"] == f"/v1/registry/{skill}/versions/1/archive"


async def test_ac20_later_skill_publish_does_not_change_published_bundle(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    skill = await new_skill(conn, caller, "refund-flow")
    agent = await new_agent(conn, caller)
    await publish_skill_versions(conn, caller, skill, "refund-flow", 1)
    await create_link(conn, caller, agent, skill, "uses", "out", None, True)
    await publish(conn, caller, agent, 1)
    before = await resolve_bundle(conn, caller, agent, 1)
    draft = await create_draft(conn, caller, skill, archive=skill_zip("refund-flow", "v2"))
    await publish(conn, caller, skill, draft["version"]["version"])
    after = await resolve_bundle(conn, caller, agent, 1)
    assert after == before
    assert after["dependencies"][0]["version"] == 1


async def test_version_omitted_resolves_current(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    skill = await published_skill(conn, tenant, "refund-flow")
    agent = await agent_using(conn, tenant, [skill])
    caller = caller_for(tenant)
    assert await resolve_bundle(conn, caller, agent, None) == await resolve_bundle(
        conn, caller, agent, 1
    )


async def test_chain_is_truncated_at_depth_5(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    chain = [await published_skill(conn, tenant, f"chain-{i}") for i in range(1, 8)]
    for source, target in zip(chain, chain[1:]):
        await dep(conn, tenant, source, target)
    agent = await agent_using(conn, tenant, [chain[0]])
    bundle = await resolve_bundle(conn, caller_for(tenant), agent, None)
    assert slugs(bundle) == [f"chain-{i}" for i in range(1, 6)]


async def test_cycle_in_frozen_deps_terminates_with_each_dependency_once(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    first = await published_skill(conn, tenant, "cycle-a")
    second = await published_skill(conn, tenant, "cycle-b")
    await dep(conn, tenant, first, second)
    await dep(conn, tenant, second, first)
    agent = await agent_using(conn, tenant, [first])
    bundle = await resolve_bundle(conn, caller_for(tenant), agent, None)
    assert slugs(bundle) == ["cycle-a", "cycle-b"]


async def test_dependency_reached_by_two_paths_appears_once(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    left = await published_skill(conn, tenant, "left-skill")
    right = await published_skill(conn, tenant, "right-skill")
    shared = await published_skill(conn, tenant, "shared-skill")
    await dep(conn, tenant, left, shared)
    await dep(conn, tenant, right, shared)
    agent = await agent_using(conn, tenant, [left, right])
    bundle = await resolve_bundle(conn, caller_for(tenant), agent, None)
    assert sorted(slugs(bundle)) == ["left-skill", "right-skill", "shared-skill"]


async def test_root_without_deps_has_empty_dependencies(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    await publish(conn, caller, agent, 1)
    assert (await resolve_bundle(conn, caller, agent, None))["dependencies"] == []


async def test_draft_root_resolves_live_accepted_links_and_skips_pending(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    accepted = await published_skill(conn, tenant, "accepted-skill")
    pending = await published_skill(conn, tenant, "pending-skill")
    agent = await agent_using(conn, tenant, [accepted], publish_it=False)
    await conn.execute(
        "INSERT INTO registry_links (tenant_id, source_id, target_id, relation, auto_load, "
        "origin_id, status, created_by) VALUES (%s, %s, %s, 'uses', true, %s, 'pending', 'u2')",
        (tenant, agent, pending, pending),
    )
    bundle = await resolve_bundle(conn, caller, agent, 1)
    assert slugs(bundle) == ["accepted-skill"]
    assert bundle["root"]["version"] == 1


async def test_draft_root_follows_pinned_link_and_frozen_deps_below_it(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    top = await new_skill(conn, caller, "top-skill")
    await publish_skill_versions(conn, caller, top, "top-skill", 2)
    below = await published_skill(conn, tenant, "below-skill")
    await dep(conn, tenant, top, below)
    agent = await new_agent(conn, caller)
    await create_link(conn, caller, agent, top, "uses", "out", 1, True)
    bundle = await resolve_bundle(conn, caller, agent, 1)
    assert [(d["slug"], d["version"]) for d in bundle["dependencies"]] == [("top-skill", 1), ("below-skill", 1)]


async def test_invisible_root_is_404(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    agent = await agent_using(conn, tenant, [])
    err = await not_found_of(resolve_bundle(conn, caller_for(tenant, "stranger"), agent, None))
    assert (err.status, err.error) == (404, "not_found")
    err = await not_found_of(resolve_bundle(conn, caller_for(tenant), uuid.uuid4(), None))
    assert err.status == 404


async def test_dependency_included_though_caller_cannot_discover_it(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    owner = caller_for(tenant)
    skill = await published_skill(conn, tenant, "hidden-skill")
    agent = await new_agent(conn, owner)
    await create_link(conn, owner, agent, skill, "uses", "out", None, True)
    await conn.execute("UPDATE registry SET visibility = 'tenant' WHERE id = %s", (agent,))
    await publish(conn, owner, agent, 1)
    stranger = caller_for(tenant, "stranger")
    bundle = await resolve_bundle(conn, stranger, agent, None)
    assert slugs(bundle) == ["hidden-skill"]


async def test_archived_dependency_still_resolves(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    skill = await published_skill(conn, tenant, "refund-flow")
    agent = await agent_using(conn, tenant, [skill])
    await set_archived(conn, caller, skill, True)
    assert slugs(await resolve_bundle(conn, caller, agent, None)) == ["refund-flow"]


async def test_unknown_version_and_foreign_draft_are_404(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    owner = caller_for(tenant)
    agent = await agent_using(conn, tenant, [])
    await conn.execute("UPDATE registry SET visibility = 'tenant' WHERE id = %s", (agent,))
    await create_draft(conn, owner, agent)
    stranger = caller_for(tenant, "stranger")
    for version in (99, 2, 0):
        err = await not_found_of(resolve_bundle(conn, stranger, agent, version))
        assert (err.status, err.error) == (404, "not_found")
    assert (await resolve_bundle(conn, owner, agent, 2))["root"]["version"] == 2


async def test_unpublished_resource_without_version_param_is_404(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    err = await not_found_of(resolve_bundle(conn, caller, agent, None))
    assert err.status == 404


async def test_bundle_query_never_selects_skill_file_content() -> None:
    from krep.registry import bundle

    assert "skill_files" not in bundle.BUNDLE_QUERY


async def test_http_bundle_route(make_client: MakeClient, tenant: uuid.UUID) -> None:
    async with make_client(tenant) as client:
        agent = (await client.post("/v1/registry", json=agent_body())).json()["id"]
        assert (await client.post(f"/v1/registry/{agent}/versions/1/publish")).status_code == 200
        ok = await client.get(f"/v1/registry/{agent}/bundle")
        assert ok.status_code == 200
        assert ok.json()["dependencies"] == [] and ok.json()["root"]["version"] == 1
        bad = await client.get(f"/v1/registry/{agent}/bundle", params={"version": "abc"})
        assert (bad.status_code, bad.json()["error"]) == (422, "validation_failed")
        missing = await client.get(f"/v1/registry/{agent}/bundle", params={"version": 9})
        assert (missing.status_code, missing.json()["error"]) == (404, "not_found")
