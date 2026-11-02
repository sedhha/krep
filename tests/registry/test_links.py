import json
import uuid
from collections.abc import Awaitable
from typing import Any

import psycopg
import pytest

from krep.api.errors import ApiError
from krep.identity.resolve import Caller
from krep.registry.links import (
    accept_link,
    create_link,
    delete_link,
    list_links,
    reject_link,
)
from krep.registry.publish import publish
from krep.registry.resources import delete_resource, set_archived
from krep.registry.versions import create_draft
from tests.registry.conftest import (
    MakeClient,
    agent_body,
    caller_for,
    new_agent,
    new_skill,
    scalar,
    skill_body,
    skill_zip,
)

BASE = "/v1/registry"


async def link(
    conn: psycopg.AsyncConnection,
    caller: Caller,
    resource_id: uuid.UUID,
    other_id: uuid.UUID,
    *,
    direction: str = "out",
    relation: str = "uses",
    pinned_version: int | None = None,
    auto_load: bool = False,
) -> dict[str, Any]:
    return await create_link(
        conn,
        caller,
        resource_id,
        other_id,
        relation,
        direction,
        pinned_version,
        auto_load,
    )


async def error_of(coro: Awaitable[object]) -> ApiError:
    with pytest.raises(ApiError) as exc:
        await coro
    return exc.value


async def test_owner_link_out_is_accepted(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    out = await link(conn, caller, agent, skill, auto_load=True)
    assert out["status"] == "accepted"
    assert out["source_id"] == agent and out["target_id"] == skill
    assert out["auto_load"] is True and out["pinned_version"] is None
    assert (
        await scalar(
            conn, "SELECT origin_id FROM registry_links WHERE id = %s", out["id"]
        )
        == agent
    )


async def test_link_in_direction_swaps_source_and_target(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    out = await link(conn, caller, skill, agent, direction="in")
    assert out["source_id"] == agent and out["target_id"] == skill
    assert (
        await scalar(
            conn, "SELECT origin_id FROM registry_links WHERE id = %s", out["id"]
        )
        == skill
    )


async def test_pair_not_in_link_rules_is_422_link_not_allowed(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    a1 = await new_agent(conn, caller, "agent-one")
    a2 = await new_agent(conn, caller, "agent-two")
    err = await error_of(link(conn, caller, a1, a2))
    assert (err.status, err.error) == (422, "link_not_allowed")


async def test_unknown_relation_is_422_link_not_allowed(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    err = await error_of(link(conn, caller, agent, skill, relation="owns"))
    assert (err.status, err.error) == (422, "link_not_allowed")


async def test_auto_load_rejected_when_rule_disallows_it(
    conn: psycopg.AsyncConnection,
    tenant: uuid.UUID,
    owner_conn: psycopg.AsyncConnection,
) -> None:
    await owner_conn.execute(
        "UPDATE link_rules SET auto_load_allowed = false WHERE source_type = 'agent'"
    )
    try:
        await owner_conn.commit()
        caller = caller_for(tenant)
        agent = await new_agent(conn, caller)
        skill = await new_skill(conn, caller)
        err = await error_of(link(conn, caller, agent, skill, auto_load=True))
        assert (err.status, err.error) == (422, "link_not_allowed")
        assert (await link(conn, caller, agent, skill, auto_load=False))[
            "status"
        ] == "accepted"
    finally:
        await owner_conn.execute(
            "UPDATE link_rules SET auto_load_allowed = true WHERE source_type = 'agent'"
        )
        await owner_conn.commit()


async def test_archived_target_is_rejected(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    await publish(conn, caller, skill, 1)
    await set_archived(conn, caller, skill, True)
    err = await error_of(link(conn, caller, agent, skill))
    assert (err.status, err.error) == (409, "resource_archived")


async def test_archived_origin_is_rejected(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    await publish(conn, caller, agent, 1)
    await set_archived(conn, caller, agent, True)
    err = await error_of(link(conn, caller, agent, skill))
    assert (err.status, err.error) == (409, "resource_archived")


async def test_ac1_cross_tenant_target_is_404(
    conn: psycopg.AsyncConnection,
    tenant: uuid.UUID,
    owner_conn: psycopg.AsyncConnection,
) -> None:
    other_tenant = uuid.uuid4()
    await owner_conn.execute(
        "SELECT set_config('app.tenant_id', %s, true)", (str(other_tenant),)
    )
    foreign_skill = await scalar(
        owner_conn,
        "INSERT INTO registry (tenant_id, type, slug, name, visibility, status, created_by, updated_by) "
        "VALUES (%s, 'skill', 'foreign-skill', 'Foreign', 'tenant', 'published', 'x', 'x') RETURNING id",
        other_tenant,
    )
    await owner_conn.commit()
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    err = await error_of(link(conn, caller, agent, foreign_skill))
    assert (err.status, err.error) == (404, "not_found")
    assert await scalar(conn, "SELECT count(*) FROM registry_links") == 0


async def test_link_to_self_is_422(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    err = await error_of(link(conn, caller, agent, agent))
    assert err.status == 422


async def test_creator_without_edit_on_origin_side_is_403(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    owner = caller_for(tenant, "owner")
    agent = await new_agent(conn, owner)
    skill = await new_skill(conn, owner)
    await publish(conn, owner, agent, 1)
    await conn.execute(
        "UPDATE registry SET visibility = 'tenant' WHERE id = %s", (agent,)
    )
    err = await error_of(link(conn, caller_for(tenant, "stranger"), agent, skill))
    assert (err.status, err.error) in {(403, "forbidden"), (404, "not_found")}
    assert await scalar(conn, "SELECT count(*) FROM registry_links") == 0


async def test_hidden_origin_is_404(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    owner = caller_for(tenant, "owner")
    agent = await new_agent(conn, owner)
    skill = await new_skill(conn, owner)
    err = await error_of(link(conn, caller_for(tenant, "stranger"), agent, skill))
    assert (err.status, err.error) == (404, "not_found")


async def test_duplicate_link_is_409_link_exists(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    await link(conn, caller, agent, skill)
    err = await error_of(link(conn, caller, agent, skill))
    assert (err.status, err.error) == (409, "link_exists")


async def test_pinned_version_must_be_a_published_version_of_the_target(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    missing = await error_of(link(conn, caller, agent, skill, pinned_version=3))
    assert (missing.status, missing.error) == (422, "validation_failed")
    draft_only = await error_of(link(conn, caller, agent, skill, pinned_version=1))
    assert (draft_only.status, draft_only.error) == (422, "validation_failed")
    await publish(conn, caller, skill, 1)
    out = await link(conn, caller, agent, skill, pinned_version=1)
    assert out["pinned_version"] == 1
    assert (
        await scalar(
            conn,
            "SELECT v.version FROM registry_links l JOIN registry_versions v ON v.id = l.pinned_version_id "
            "WHERE l.id = %s",
            out["id"],
        )
        == 1
    )


async def test_ac19_skill_initiated_link_on_another_owners_agent_is_pending_until_accepted(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    ravi = caller_for(tenant, "ravi")
    priya = caller_for(tenant, "priya")
    agent = await new_agent(conn, ravi)
    skill = await new_skill(conn, priya)
    await publish(conn, priya, skill, 1)
    await publish(conn, ravi, agent, 1)
    await conn.execute(
        "UPDATE registry SET visibility = 'tenant' WHERE id = %s", (agent,)
    )
    out = await link(conn, priya, skill, agent, direction="in", auto_load=True)
    assert out["status"] == "pending"
    assert out["accept_by"] == "source"
    assert "refund-assistant" in out["waiting_on"]

    forbidden = await error_of(accept_link(conn, priya, out["id"]))
    assert forbidden.status == 403

    await create_draft(conn, ravi, agent)
    await publish(conn, ravi, agent, 2)
    assert await scalar(conn, "SELECT count(*) FROM registry_version_deps") == 0

    accepted = await accept_link(conn, ravi, out["id"])
    assert accepted["status"] == "accepted"

    await create_draft(conn, ravi, agent)
    await publish(conn, ravi, agent, 3)
    assert await scalar(conn, "SELECT count(*) FROM registry_version_deps") == 1


async def test_ac19_rejected_link_stays_out_of_freeze(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    ravi = caller_for(tenant, "ravi")
    priya = caller_for(tenant, "priya")
    agent = await new_agent(conn, ravi)
    skill = await new_skill(conn, priya)
    await publish(conn, priya, skill, 1)
    await publish(conn, ravi, agent, 1)
    await conn.execute(
        "UPDATE registry SET visibility = 'tenant' WHERE id = %s", (agent,)
    )
    out = await link(conn, priya, skill, agent, direction="in")
    rejected = await reject_link(conn, ravi, out["id"])
    assert rejected["status"] == "rejected"
    await create_draft(conn, ravi, agent)
    await publish(conn, ravi, agent, 2)
    assert await scalar(conn, "SELECT count(*) FROM registry_version_deps") == 0
    again = await error_of(accept_link(conn, ravi, out["id"]))
    assert (again.status, again.error) == (409, "invalid_state")


async def test_admin_can_accept_for_the_owner(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    ravi = caller_for(tenant, "ravi")
    priya = caller_for(tenant, "priya")
    agent = await new_agent(conn, ravi)
    skill = await new_skill(conn, priya)
    await publish(conn, ravi, agent, 1)
    await conn.execute(
        "UPDATE registry SET visibility = 'tenant' WHERE id = %s", (agent,)
    )
    out = await link(conn, priya, skill, agent, direction="in")
    assert out["status"] == "pending"
    assert (await accept_link(conn, caller_for(tenant, "root", admin=True), out["id"]))[
        "status"
    ] == "accepted"


async def test_accept_unknown_link_is_404(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    err = await error_of(accept_link(conn, caller_for(tenant), uuid.uuid4()))
    assert (err.status, err.error) == (404, "not_found")


async def test_ac21_direct_cycle_is_422_link_cycle(
    conn: psycopg.AsyncConnection,
    tenant: uuid.UUID,
    owner_conn: psycopg.AsyncConnection,
) -> None:
    await owner_conn.execute(
        "INSERT INTO link_rules VALUES ('skill', 'agent', 'delegates', false, 'source') "
        "ON CONFLICT DO NOTHING"
    )
    await owner_conn.commit()
    try:
        caller = caller_for(tenant)
        agent = await new_agent(conn, caller)
        skill = await new_skill(conn, caller)
        await link(conn, caller, agent, skill)
        err = await error_of(link(conn, caller, skill, agent, relation="delegates"))
        assert (err.status, err.error) == (422, "link_cycle")
        assert await scalar(conn, "SELECT count(*) FROM registry_links") == 1
    finally:
        await owner_conn.execute(
            "DELETE FROM link_rules WHERE source_type = 'skill' AND relation = 'delegates'"
        )
        await owner_conn.commit()


async def test_ac21_transitive_cycle_through_any_relation_is_422(
    conn: psycopg.AsyncConnection,
    tenant: uuid.UUID,
    owner_conn: psycopg.AsyncConnection,
) -> None:
    await owner_conn.execute(
        "INSERT INTO link_rules VALUES ('skill', 'agent', 'delegates', false, 'source'), "
        "('agent', 'agent', 'calls', false, 'source') ON CONFLICT DO NOTHING"
    )
    await owner_conn.commit()
    try:
        caller = caller_for(tenant)
        a = await new_agent(conn, caller, "agent-a")
        b = await new_agent(conn, caller, "agent-b")
        s = await new_skill(conn, caller)
        await link(conn, caller, a, s)
        await link(conn, caller, b, a, relation="calls")
        err = await error_of(link(conn, caller, s, b, relation="delegates"))
        assert (err.status, err.error) == (422, "link_cycle")
    finally:
        await owner_conn.execute(
            "DELETE FROM link_rules WHERE relation IN ('delegates', 'calls')"
        )
        await owner_conn.commit()


async def test_ac21_pending_links_do_not_count_toward_cycles_until_accepted(
    conn: psycopg.AsyncConnection,
    tenant: uuid.UUID,
    owner_conn: psycopg.AsyncConnection,
) -> None:
    await owner_conn.execute(
        "INSERT INTO link_rules VALUES ('skill', 'agent', 'delegates', false, 'source') "
        "ON CONFLICT DO NOTHING"
    )
    await owner_conn.commit()
    try:
        ravi = caller_for(tenant, "ravi")
        priya = caller_for(tenant, "priya")
        agent = await new_agent(conn, ravi)
        skill = await new_skill(conn, priya)
        await publish(conn, priya, skill, 1)
        await publish(conn, ravi, agent, 1)
        await conn.execute(
            "UPDATE registry SET visibility = 'tenant' WHERE id IN (%s, %s)",
            (agent, skill),
        )
        pending = await link(conn, priya, skill, agent, direction="in")
        assert pending["status"] == "pending"
        back = await link(conn, priya, skill, agent, relation="delegates")
        assert back["status"] == "accepted"
        err = await error_of(accept_link(conn, ravi, pending["id"]))
        assert (err.status, err.error) == (422, "link_cycle")
    finally:
        await owner_conn.execute("DELETE FROM link_rules WHERE relation = 'delegates'")
        await owner_conn.commit()


async def test_delete_link_by_owner_of_either_side(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    ravi = caller_for(tenant, "ravi")
    priya = caller_for(tenant, "priya")
    agent = await new_agent(conn, ravi)
    skill = await new_skill(conn, priya)
    await publish(conn, priya, skill, 1)
    await conn.execute(
        "UPDATE registry SET visibility = 'tenant' WHERE id = %s", (skill,)
    )
    out = await link(conn, ravi, agent, skill)
    stranger = await error_of(
        delete_link(conn, caller_for(tenant, "stranger"), out["id"])
    )
    assert stranger.status in (403, 404)
    await delete_link(conn, ravi, out["id"])
    assert await scalar(conn, "SELECT count(*) FROM registry_links") == 0
    missing = await error_of(delete_link(conn, ravi, out["id"]))
    assert missing.status == 404


async def test_list_links_directions_and_status_filter(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    ravi = caller_for(tenant, "ravi")
    priya = caller_for(tenant, "priya")
    agent = await new_agent(conn, ravi, "refund-assistant")
    other_agent = await new_agent(conn, ravi, "other-assistant")
    skill = await new_skill(conn, priya)
    await conn.execute(
        "UPDATE registry SET visibility = 'tenant', status = 'published'"
    )
    await link(conn, ravi, agent, skill)
    pending = await link(conn, priya, skill, other_agent, direction="in")
    assert pending["status"] == "pending"

    out = await list_links(conn, ravi, agent, "out", None)
    assert [i["target_id"] for i in out] == [skill]
    assert await list_links(conn, ravi, agent, "in", None) == []
    both = await list_links(conn, priya, skill, "both", None)
    assert len(both) == 2
    accepted = await list_links(conn, priya, skill, "both", "accepted")
    assert [i["status"] for i in accepted] == ["accepted"]
    only_pending = await list_links(conn, priya, skill, "in", "pending")
    assert [i["id"] for i in only_pending] == [pending["id"]]
    assert {
        "id",
        "relation",
        "direction",
        "status",
        "pinned_version",
        "auto_load",
        "other",
    } <= set(out[0])


async def test_list_links_hides_links_to_unreadable_resources_and_pending_from_non_editors(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    ravi = caller_for(tenant, "ravi")
    agent = await new_agent(conn, ravi)
    skill = await new_skill(conn, ravi)
    await link(conn, ravi, agent, skill)
    await conn.execute(
        "UPDATE registry SET visibility = 'tenant', status = 'published'"
    )
    viewer = caller_for(tenant, "viewer")
    assert len(await list_links(conn, viewer, agent, "out", None)) == 1
    await conn.execute(
        "UPDATE registry SET visibility = 'private' WHERE id = %s", (skill,)
    )
    assert await list_links(conn, viewer, agent, "out", None) == []
    err = await error_of(list_links(conn, viewer, skill, "both", None))
    assert err.status == 404


async def test_ac22_delete_skill_with_real_inbound_link_is_409_with_referrers(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    await link(conn, caller, agent, skill)
    err = await error_of(delete_resource(conn, caller, skill))
    assert (err.status, err.error) == (409, "resource_in_use")
    assert [r["id"] for r in err.extra["referrers"]] == [agent]
    assert await scalar(conn, "SELECT count(*) FROM registry WHERE id = %s", skill) == 1


async def test_deleting_the_link_unblocks_skill_delete(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    caller = caller_for(tenant)
    agent = await new_agent(conn, caller)
    skill = await new_skill(conn, caller)
    out = await link(conn, caller, agent, skill)
    await delete_link(conn, caller, out["id"])
    await delete_resource(conn, caller, skill)
    assert await scalar(conn, "SELECT count(*) FROM registry WHERE id = %s", skill) == 0


async def test_links_endpoints_roundtrip(
    make_client: MakeClient, tenant: uuid.UUID, conn: psycopg.AsyncConnection
) -> None:
    async with (
        make_client(tenant, user="ravi") as ravi,
        make_client(tenant, user="priya") as priya,
    ):
        agent = (await ravi.post(BASE, json=agent_body())).json()["id"]
        skill = (
            await priya.post(
                BASE,
                files={
                    "archive": ("s.zip", skill_zip("refund-flow"), "application/zip")
                },
                data={
                    "metadata": json.dumps(
                        {
                            **{k: v for k, v in skill_body().items() if k != "archive"},
                            "visibility": "tenant",
                        }
                    )
                },
            )
        ).json()["id"]
        await ravi.patch(f"{BASE}/{agent}", json={"visibility": "tenant"})
        assert (
            await priya.post(f"{BASE}/{skill}/versions/1/publish")
        ).status_code == 200
        assert (
            await ravi.post(f"{BASE}/{agent}/versions/1/publish")
        ).status_code == 200
        created = await priya.post(
            f"{BASE}/{skill}/links",
            json={
                "other_id": agent,
                "relation": "uses",
                "direction": "in",
                "auto_load": True,
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "pending" and body["accept_by"] == "source"
        listed = await ravi.get(f"{BASE}/{agent}/links", params={"direction": "out"})
        assert listed.status_code == 200 and len(listed.json()["items"]) == 1
        assert (await priya.post(f"/v1/links/{body['id']}/accept")).status_code == 403
        assert (await ravi.post(f"/v1/links/{body['id']}/accept")).json()[
            "status"
        ] == "accepted"
        assert (await ravi.delete(f"/v1/links/{body['id']}")).status_code == 204
        bad = await ravi.post(
            f"{BASE}/{agent}/links",
            json={"other_id": agent, "relation": "uses", "direction": "sideways"},
        )
        assert bad.status_code == 422 and bad.json()["error"] == "validation_failed"
