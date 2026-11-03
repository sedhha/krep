import uuid

import psycopg

from krep.registry.resources import update_resource
from krep.search.engine import registry_search
from tests.registry.conftest import World, published_agent


async def slugs(
    world: World, caller_args: dict[str, object], **kw: object
) -> list[str]:
    tenant = caller_args.pop("tenant")
    assert isinstance(tenant, uuid.UUID)
    caller = world.caller(tenant, **caller_args)  # type: ignore[arg-type]
    hits = await registry_search(world.conn, caller, q="", limit=50, **kw)  # type: ignore[arg-type]
    return sorted(h.slug for h in hits)


async def seed(world: World) -> None:
    open_a = world.open[world.a]
    owner = world.caller(world.a, "owner")
    await published_agent(world, owner, "org-agent", policies={"read": [open_a]})
    await published_agent(
        world,
        owner,
        "alpha-agent",
        scope="product",
        product="alpha",
        policies={"read": [open_a]},
    )
    await published_agent(world, owner, "private-agent")


async def test_v2ac11_search_scope_reach(world: World) -> None:
    await seed(world)
    assert await slugs(world, {"tenant": world.a, "user": "x"}) == ["org-agent"]
    assert await slugs(world, {"tenant": world.a, "user": "x", "product": "alpha"}) == [
        "alpha-agent",
        "org-agent",
    ]
    assert await slugs(world, {"tenant": world.a, "user": "x", "product": "beta"}) == [
        "org-agent"
    ]


async def test_v2ac9_search_creator_and_admin_see_own_hidden_not_others(
    world: World,
) -> None:
    await seed(world)
    assert "private-agent" in await slugs(world, {"tenant": world.a, "user": "owner"})
    assert "private-agent" in await slugs(
        world, {"tenant": world.a, "user": "adm", "admin": True}
    )
    assert "private-agent" not in await slugs(world, {"tenant": world.a, "user": "x"})


async def test_v2ac11_search_global_open_and_restricted(world: World) -> None:
    conn: psycopg.AsyncConnection = world.conn
    from krep.policy.parser import parse
    from krep.policy.store import write_policy

    gold = (
        await write_policy(conn, world.a, "gold", parse('token.tier == "gold"'), "a")
    ).id
    await world.use(world.a, platform=True)
    owner = world.caller(world.a, "owner")
    for slug, policy in (("global-open", world.open[world.a]), ("global-gold", gold)):
        rid = await published_agent(world, owner, slug, policies={"read": [policy]})
        await update_resource(conn, owner, rid, {"scope": "global"})
    await world.use(world.b)
    assert await slugs(world, {"tenant": world.b, "user": "x"}) == ["global-open"]
    assert await slugs(
        world, {"tenant": world.b, "user": "g", "token": {"tier": "gold"}}
    ) == ["global-gold", "global-open"]
    assert (
        await slugs(
            world,
            {"tenant": world.b, "user": "g", "token": {"tier": "gold"}},
            scope="org",
        )
        == []
    )
    assert await slugs(
        world,
        {"tenant": world.b, "user": "g", "token": {"tier": "gold"}},
        scope="global",
    ) == ["global-gold", "global-open"]
