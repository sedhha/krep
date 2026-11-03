import uuid

import pytest

from krep.api.errors import ApiError
from krep.registry.resources import create_resource, delete_resource, update_resource
from krep.registry.scope import set_scope
from tests.registry.conftest import World, agent_body, published_agent
from tests.registry.test_cross_tenant_links import link, linked_world


async def audit_rows(
    world: World, action: str, target: uuid.UUID
) -> list[tuple[str, str | None]]:
    await world.conn.execute("RESET ROLE")
    cur = await world.conn.execute(
        "SELECT actor, target FROM admin_audit_log WHERE action = %s AND target = %s "
        "ORDER BY id",
        (action, str(target)),
    )
    rows = await cur.fetchall()
    await world.conn.execute("SET LOCAL ROLE krep_app")
    return rows


async def test_v2ac12_global_move_writes_an_audit_row(world: World) -> None:
    await world.use(world.a, platform=True)
    caller = world.caller(world.a, "platform-user")
    rid = await published_agent(world, caller)
    await update_resource(world.conn, caller, rid, {"scope": "global"})
    assert await audit_rows(world, "registry.scope.global", rid) == [
        ("platform-user", str(rid))
    ]


async def test_v2ac12_set_scope_org_admin_is_403_platform_succeeds(
    world: World,
) -> None:
    admin = world.caller(world.a, "adm", admin=True)
    rid = await published_agent(world, admin)
    with pytest.raises(ApiError) as exc:
        await set_scope(world.conn, admin, rid, "global", None)
    assert (exc.value.status, exc.value.error) == (403, "scope_not_allowed")
    await world.use(world.a, platform=True)
    out = await set_scope(world.conn, admin, rid, "global", None)
    assert out["scope"] == "global"
    assert len(await audit_rows(world, "registry.scope.global", rid)) == 1


async def test_v2ac12_set_scope_rejects_unpublished(world: World) -> None:
    await world.use(world.a, platform=True)
    admin = world.caller(world.a, "adm", admin=True)
    draft = (await create_resource(world.conn, admin, agent_body("draft-one")))["id"]
    with pytest.raises(ApiError) as exc:
        await set_scope(world.conn, admin, draft, "global", None)
    assert (exc.value.status, exc.value.error) == (409, "invalid_state")


async def test_v2ac12_set_scope_moves_between_org_and_product(world: World) -> None:
    admin = world.caller(world.a, "adm", admin=True)
    rid = await published_agent(world, admin)
    out = await set_scope(world.conn, admin, rid, "product", "alpha")
    assert (out["scope"], out["product"]) == ("product", "alpha")
    out = await set_scope(world.conn, admin, rid, "org", None)
    assert (out["scope"], out["product"]) == ("org", None)


async def test_v2ac12_real_foreign_link_blocks_demotion_until_removed(
    world: World,
) -> None:
    skill, agent = await linked_world(world)
    await world.use(world.a)
    owner = world.caller(world.a, "owner", admin=True)
    with pytest.raises(ApiError) as exc:
        await set_scope(world.conn, owner, skill, "org", None)
    assert (exc.value.status, exc.value.error) == (409, "resource_in_use")
    await world.use(world.b)
    await delete_resource(world.conn, world.caller(world.b, "owner", admin=True), agent)
    await world.use(world.a)
    assert (await set_scope(world.conn, owner, skill, "org", None))["scope"] == "org"


async def test_v2ac13_other_tenant_cannot_link_from_a_hidden_resource(
    world: World,
) -> None:
    rid = await published_agent(world, world.caller(world.a, "owner", admin=True))
    await world.use(world.b)
    other = await published_agent(
        world, world.caller(world.b, "owner", admin=True), "b-agent"
    )
    with pytest.raises(ApiError) as exc:
        await link(world, world.b, other, rid)
    assert exc.value.status == 404
