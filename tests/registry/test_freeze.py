import uuid
from typing import Any

import psycopg
import pytest

from krep.api.errors import ApiError
from krep.identity.resolve import Caller
from krep.registry.links import create_link
from krep.registry.publish import publish
from krep.registry.versions import create_draft, replace_draft
from tests.registry.conftest import (
    caller_for,
    new_agent,
    new_skill,
    publish_skill_versions,
    scalar,
    skill_zip,
    spec_with,
    version_id_of,
)


async def deps_of(
    conn: psycopg.AsyncConnection, version_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, bool]]:
    cur = await conn.execute(
        "SELECT depends_on_version_id, relation, auto_load FROM registry_version_deps "
        "WHERE version_id = %s ORDER BY depends_on_version_id",
        (version_id,),
    )
    return [(r[0], r[1], r[2]) for r in await cur.fetchall()]


async def link_agent_to_skill(
    conn: psycopg.AsyncConnection,
    caller: Caller,
    agent: uuid.UUID,
    skill: uuid.UUID,
    pinned: int | None = None,
    auto_load: bool = True,
) -> dict[str, Any]:
    return await create_link(
        conn, caller, agent, skill, "uses", "out", pinned, auto_load
    )


async def republish_agent(
    conn: psycopg.AsyncConnection, caller: Caller, agent: uuid.UUID, prompt: str
) -> int:
    draft = await create_draft(conn, caller, agent)
    n = draft["version"]["version"]
    await replace_draft(conn, caller, agent, n, spec=spec_with(prompt))
    await publish(conn, caller, agent, n)
    return n


async def test_ac20_publish_freezes_unpinned_link_to_skill_current(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    await publish_skill_versions(conn, caller, skill, "refund-flow", 4)
    await link_agent_to_skill(conn, caller, agent, skill)
    await publish(conn, caller, agent, 1)
    skill_v4 = await version_id_of(conn, skill, 4)
    assert await deps_of(conn, await version_id_of(conn, agent, 1)) == [
        (skill_v4, "uses", True)
    ]


async def test_ac20_later_skill_publish_does_not_change_published_agent_deps(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    await publish_skill_versions(conn, caller, skill, "refund-flow", 4)
    await link_agent_to_skill(conn, caller, agent, skill)
    await publish(conn, caller, agent, 1)
    skill_v4 = await version_id_of(conn, skill, 4)
    draft = await create_draft(
        conn, caller, skill, archive=skill_zip("refund-flow", "five")
    )
    await publish(conn, caller, skill, draft["version"]["version"])
    assert draft["version"]["version"] == 5
    assert await deps_of(conn, await version_id_of(conn, agent, 1)) == [
        (skill_v4, "uses", True)
    ]
    n = await republish_agent(conn, caller, agent, "next")
    skill_v5 = await version_id_of(conn, skill, 5)
    assert await deps_of(conn, await version_id_of(conn, agent, n)) == [
        (skill_v5, "uses", True)
    ]
    assert await deps_of(conn, await version_id_of(conn, agent, 1)) == [
        (skill_v4, "uses", True)
    ]


async def test_ac20_pinned_link_freezes_the_pinned_version(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    await publish_skill_versions(conn, caller, skill, "refund-flow", 3)
    await link_agent_to_skill(conn, caller, agent, skill, pinned=2, auto_load=False)
    await publish(conn, caller, agent, 1)
    assert await deps_of(conn, await version_id_of(conn, agent, 1)) == [
        (await version_id_of(conn, skill, 2), "uses", False)
    ]


async def test_freeze_ignores_pending_links(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    owner = caller_for(tenant, "owner")
    agent = await new_agent(conn, owner)
    skill = await new_skill(conn, owner)
    await publish(conn, owner, skill, 1)
    await conn.execute(
        "INSERT INTO registry_links (tenant_id, source_id, target_id, relation, origin_id, status, created_by) "
        "VALUES (%s, %s, %s, 'uses', %s, 'pending', 'x')",
        (tenant, agent, skill, skill),
    )
    await publish(conn, owner, agent, 1)
    assert await scalar(conn, "SELECT count(*) FROM registry_version_deps") == 0


async def test_unpublished_target_is_422_dependency_unpublished_and_nothing_changes(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller, "refund-flow")
    other = await new_skill(conn, caller, "other-flow")
    await publish(conn, caller, other, 1)
    await link_agent_to_skill(conn, caller, agent, other)
    await link_agent_to_skill(conn, caller, agent, skill)
    with pytest.raises(ApiError) as exc:
        await publish(conn, caller, agent, 1)
    assert (exc.value.status, exc.value.error) == (422, "dependency_unpublished")
    assert "refund-flow" in exc.value.message
    assert await scalar(conn, "SELECT count(*) FROM registry_version_deps") == 0
    assert (
        await scalar(
            conn, "SELECT status FROM registry_versions WHERE registry_id = %s", agent
        )
        == "draft"
    )


async def test_ac15_prune_is_blocked_by_a_real_frozen_dependency(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller, "support-bot")
    skill = await new_skill(conn, caller)
    await publish_skill_versions(conn, caller, skill, "refund-flow", 10)
    link = await link_agent_to_skill(conn, caller, agent, skill, pinned=1)
    await publish(conn, caller, agent, 1)
    draft = await create_draft(
        conn, caller, skill, archive=skill_zip("refund-flow", "eleven")
    )
    with pytest.raises(ApiError) as exc:
        await publish(conn, caller, skill, draft["version"]["version"])
    assert (exc.value.status, exc.value.error) == (409, "version_in_use")
    assert exc.value.extra["version_to_remove"] == 1
    kinds = {r["kind"] for r in exc.value.extra["referenced_by"]}
    assert kinds == {"link_pin", "version_dep"}
    assert {r["resource"] for r in exc.value.extra["referenced_by"]} == {"support-bot"}
    assert str(link["id"]) in {
        r.get("link_id") for r in exc.value.extra["referenced_by"]
    }
    assert (
        await scalar(
            conn, "SELECT count(*) FROM registry_versions WHERE registry_id = %s", skill
        )
        == 11
    )
