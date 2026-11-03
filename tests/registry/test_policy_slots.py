import uuid

import psycopg
import pytest

from krep.api.errors import ApiError
from krep.policy.parser import parse
from krep.policy.store import write_policy
from krep.registry.policies import list_policies, set_policies
from krep.registry.resources import get_visible, update_resource
from tests.registry.conftest import World, agent_body, published_agent


async def rule(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, name: str, source: str
) -> uuid.UUID:
    return (await write_policy(conn, tenant, name, parse(source), "admin")).id


async def test_v2ac9_no_read_policy_hides_from_others_but_not_creator_or_admin(
    world: World,
) -> None:
    owner = world.caller(world.a, "owner")
    rid = await published_agent(world, owner)
    conn = world.conn
    assert await get_visible(conn, owner, rid) is not None
    assert await get_visible(conn, world.caller(world.a, "adm", admin=True), rid)
    assert await get_visible(conn, world.caller(world.a, "other"), rid) is None


async def test_v2ac10_several_read_policies_are_ored_and_removal_hides(
    world: World,
) -> None:
    conn = world.conn
    owner = world.caller(world.a, "owner")
    billing = await rule(conn, world.a, "billing", 'token.dept == "billing"')
    sales = await rule(conn, world.a, "sales", 'token.dept == "sales"')
    rid = await published_agent(world, owner, policies={"read": [billing, sales]})
    sales_user = world.caller(world.a, "s", token={"dept": "sales"})
    billing_user = world.caller(world.a, "b", token={"dept": "billing"})
    other = world.caller(world.a, "o", token={"dept": "hr"})
    assert await get_visible(conn, sales_user, rid)
    assert await get_visible(conn, billing_user, rid)
    assert await get_visible(conn, other, rid) is None
    await set_policies(conn, owner, rid, "read", [billing])
    assert await get_visible(conn, sales_user, rid) is None
    assert await get_visible(conn, billing_user, rid)


async def test_v2ac14_manage_policy_grants_edit_to_non_owner(world: World) -> None:
    conn = world.conn
    owner = world.caller(world.a, "owner")
    leads = await rule(conn, world.a, "leads", 'token.team == "leads"')
    rid = await published_agent(
        world,
        owner,
        policies={"read": [world.open[world.a]], "manage": [leads]},
    )
    lead = world.caller(world.a, "lead", token={"team": "leads"})
    out = await update_resource(conn, lead, rid, {"name": "Renamed"})
    assert out["name"] == "Renamed"
    assert out["policies"]["manage"] == [leads]
    outsider = world.caller(world.a, "out", token={"team": "other"})
    with pytest.raises(ApiError) as exc:
        await update_resource(conn, outsider, rid, {"name": "Nope"})
    assert exc.value.status == 403


async def test_v2ac14_read_only_caller_cannot_edit_even_when_manage_policy_matches(
    world: World,
) -> None:
    conn = world.conn
    leads = await rule(conn, world.a, "leads", 'token.team == "leads"')
    rid = await published_agent(
        world,
        world.caller(world.a, "owner"),
        policies={"read": [world.open[world.a]], "manage": [leads]},
    )
    reader = world.caller(world.a, "r", write=False, token={"team": "leads"})
    with pytest.raises(ApiError) as exc:
        await update_resource(conn, reader, rid, {"name": "Nope"})
    assert exc.value.status == 403


async def test_manage_policy_does_not_leak_read(world: World) -> None:
    conn = world.conn
    leads = await rule(conn, world.a, "leads", 'token.team == "leads"')
    rid = await published_agent(
        world, world.caller(world.a, "owner"), policies={"manage": [leads]}
    )
    lead = world.caller(world.a, "lead", token={"team": "leads"})
    assert await get_visible(conn, lead, rid) is None


async def test_set_policies_allows_open_to_all_and_dedupes(world: World) -> None:
    conn = world.conn
    owner = world.caller(world.a, "owner")
    rid = await published_agent(world, owner)
    open_id = world.open[world.a]
    await set_policies(conn, owner, rid, "read", [open_id, open_id])
    assert (await list_policies(conn, rid))["read"] == [open_id]


async def test_set_policies_rejects_other_tenant_and_unknown_policy(
    world: World,
) -> None:
    conn = world.conn
    owner = world.caller(world.a, "owner")
    rid = await published_agent(world, owner)
    for bad in (world.open[world.b], uuid.uuid4()):
        with pytest.raises(ApiError) as exc:
            await set_policies(conn, owner, rid, "read", [bad])
        assert exc.value.status == 422
        assert exc.value.extra["errors"][0]["field"] == "policies.read"


async def test_set_policies_enforces_max_ten_per_action(world: World) -> None:
    conn = world.conn
    owner = world.caller(world.a, "owner")
    rid = await published_agent(world, owner)
    ids = [await rule(conn, world.a, f"p{i}", f'token.k == "{i}"') for i in range(11)]
    await set_policies(conn, owner, rid, "read", ids[:10])
    with pytest.raises(ApiError) as exc:
        await set_policies(conn, owner, rid, "read", ids)
    assert (exc.value.status, exc.value.error) == (409, "policy_slot_limit_reached")
    assert exc.value.extra["limit"] == 10
    await set_policies(conn, owner, rid, "manage", ids[:10])


async def test_set_policies_requires_manage_rights(world: World) -> None:
    conn = world.conn
    rid = await published_agent(world, world.caller(world.a, "owner"))
    with pytest.raises(ApiError) as exc:
        await set_policies(
            conn, world.caller(world.a, "other"), rid, "read", [world.open[world.a]]
        )
    assert exc.value.status == 404


async def test_set_policies_rejects_unknown_action(world: World) -> None:
    owner = world.caller(world.a, "owner")
    rid = await published_agent(world, owner)
    with pytest.raises(ApiError) as exc:
        await set_policies(world.conn, owner, rid, "link", [])
    assert exc.value.status == 422


async def test_create_rejects_unknown_policy_action(world: World) -> None:
    from krep.registry.resources import create_resource

    with pytest.raises(ApiError) as exc:
        await create_resource(
            world.conn,
            world.caller(world.a),
            agent_body(policies={"analyze": []}),
        )
    assert exc.value.extra["errors"][0]["field"] == "policies.analyze"
