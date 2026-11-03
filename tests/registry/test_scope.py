import uuid

import psycopg
import pytest

from krep.api.errors import ApiError
from krep.policy.parser import parse
from krep.policy.store import write_policy
from krep.registry import resources
from krep.registry.resources import (
    create_resource,
    delete_resource,
    get_visible,
    set_archived,
    update_resource,
)
from tests.registry.conftest import World, agent_body, published_agent, scalar


async def scope_of(conn: psycopg.AsyncConnection, rid: uuid.UUID) -> tuple[str, bool]:
    cur = await conn.execute(
        "SELECT scope, product_id IS NOT NULL FROM registry WHERE id = %s", (rid,)
    )
    row = await cur.fetchone()
    assert row is not None
    return row


async def test_v2ac11_open_to_all_at_org_scope_reaches_every_product_not_other_orgs(
    world: World,
) -> None:
    rid = await published_agent(
        world,
        world.caller(world.a, "owner"),
        policies={"read": [world.open[world.a]]},
    )
    conn = world.conn
    for product in (None, "alpha", "beta"):
        assert await get_visible(conn, world.caller(world.a, "x", product=product), rid)
    await world.use(world.b)
    assert await get_visible(conn, world.caller(world.b, "x"), rid) is None


async def test_v2ac11_open_to_all_at_product_scope_reaches_only_that_product(
    world: World,
) -> None:
    rid = await published_agent(
        world,
        world.caller(world.a, "owner", product="alpha"),
        scope="product",
        product="alpha",
        policies={"read": [world.open[world.a]]},
    )
    conn = world.conn
    assert await get_visible(conn, world.caller(world.a, "x", product="alpha"), rid)
    assert (
        await get_visible(conn, world.caller(world.a, "x", product="beta"), rid) is None
    )
    assert await get_visible(conn, world.caller(world.a, "x"), rid) is None


async def test_product_scoped_resource_without_product_is_hidden_even_from_creator(
    world: World,
) -> None:
    rid = await published_agent(
        world, world.caller(world.a, "owner"), scope="product", product="alpha"
    )
    conn = world.conn
    assert await get_visible(conn, world.caller(world.a, "owner"), rid) is None
    assert await get_visible(conn, world.caller(world.a, "owner", product="alpha"), rid)


async def test_v2ac11_global_open_to_all_reaches_every_org(world: World) -> None:
    await world.use(world.a, platform=True)
    rid = await published_agent(
        world, world.caller(world.a, "owner"), policies={"read": [world.open[world.a]]}
    )
    await update_resource(
        world.conn, world.caller(world.a, "owner"), rid, {"scope": "global"}
    )
    await world.use(world.b)
    seen = await get_visible(world.conn, world.caller(world.b, "stranger"), rid)
    assert seen is not None and seen["scope"] == "global"


async def test_v2ac11_restricted_global_policy_uses_the_callers_own_token(
    world: World,
) -> None:
    conn = world.conn
    gold = (
        await write_policy(conn, world.a, "gold", parse('token.tier == "gold"'), "a")
    ).id
    await world.use(world.a, platform=True)
    owner = world.caller(world.a, "owner")
    rid = await published_agent(world, owner, policies={"read": [gold]})
    await update_resource(conn, owner, rid, {"scope": "global"})
    await world.use(world.b)
    assert await get_visible(
        conn, world.caller(world.b, "g", token={"tier": "gold"}), rid
    )
    assert (
        await get_visible(
            conn, world.caller(world.b, "s", token={"tier": "silver"}), rid
        )
        is None
    )


async def test_global_resource_with_broken_policy_is_hidden_not_an_error(
    world: World,
) -> None:
    conn = world.conn
    broken = (
        await write_policy(conn, world.a, "broken", parse('token.a == "b"'), "a")
    ).id
    await conn.execute(
        "UPDATE access_policies SET compiled_path = '$.token.a'::jsonpath WHERE id = %s",
        (broken,),
    )
    await world.use(world.a, platform=True)
    owner = world.caller(world.a, "owner")
    rid = await published_agent(world, owner, policies={"read": [broken]})
    await update_resource(conn, owner, rid, {"scope": "global"})
    await world.use(world.b)
    assert (
        await get_visible(conn, world.caller(world.b, "x", token={"a": "b"}), rid)
        is None
    )


async def test_v2ac12_product_and_org_are_interchangeable_for_the_owners_manager(
    world: World,
) -> None:
    conn = world.conn
    owner = world.caller(world.a, "owner")
    rid = await published_agent(world, owner)
    out = await update_resource(
        conn, owner, rid, {"scope": "product", "product": "alpha"}
    )
    assert (out["scope"], out["product"]) == ("product", "alpha")
    out = await update_resource(conn, owner, rid, {"scope": "org"})
    assert (out["scope"], out["product"]) == ("org", None)


async def test_product_scope_requires_existing_product(world: World) -> None:
    conn = world.conn
    owner = world.caller(world.a, "owner")
    rid = await published_agent(world, owner)
    for changes in ({"scope": "product"}, {"scope": "product", "product": "nope"}):
        with pytest.raises(ApiError) as exc:
            await update_resource(conn, owner, rid, changes)
        assert exc.value.status == 422


async def test_v2ac12_global_requires_platform_flag(world: World) -> None:
    conn = world.conn
    admin = world.caller(world.a, "adm", admin=True)
    rid = await published_agent(world, admin)
    with pytest.raises(ApiError) as exc:
        await update_resource(conn, admin, rid, {"scope": "global"})
    assert (exc.value.status, exc.value.error) == (403, "scope_not_allowed")
    with pytest.raises(ApiError) as exc:
        await create_resource(conn, admin, agent_body("g-new", scope="global"))
    assert (exc.value.status, exc.value.error) == (403, "scope_not_allowed")
    assert await scope_of(conn, rid) == ("org", False)


async def test_v2ac12_global_promotion_keeps_row_and_requires_published(
    world: World,
) -> None:
    conn = world.conn
    await world.use(world.a, platform=True)
    owner = world.caller(world.a, "owner")
    draft = (await create_resource(conn, owner, agent_body("draft-one")))["id"]
    with pytest.raises(ApiError) as exc:
        await update_resource(conn, owner, draft, {"scope": "global"})
    assert (exc.value.status, exc.value.error) == (409, "invalid_state")
    rid = await published_agent(world, owner)
    before = await scalar(conn, "SELECT count(*) FROM registry")
    await update_resource(conn, owner, rid, {"scope": "global"})
    assert await scalar(conn, "SELECT count(*) FROM registry") == before
    assert (
        await scalar(conn, "SELECT tenant_id FROM registry WHERE id = %s", rid)
        == world.a
    )


async def test_v2ac12_demoting_a_referenced_global_resource_is_409(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = world.conn
    await world.use(world.a, platform=True)
    owner = world.caller(world.a, "owner", admin=True)
    rid = await published_agent(world, owner)
    await update_resource(conn, owner, rid, {"scope": "global"})

    async def referrers(
        _: psycopg.AsyncConnection, __: uuid.UUID
    ) -> list[dict[str, str]]:
        return [{"slug": "other-org-agent"}]

    monkeypatch.setattr(resources, "foreign_referrers", referrers)
    with pytest.raises(ApiError) as exc:
        await update_resource(conn, owner, rid, {"scope": "org"})
    assert (exc.value.status, exc.value.error) == (409, "resource_in_use")
    monkeypatch.undo()
    out = await update_resource(conn, owner, rid, {"scope": "org"})
    assert out["scope"] == "org"


async def test_v2ac12_non_admin_owner_cannot_demote_global(world: World) -> None:
    conn = world.conn
    await world.use(world.a, platform=True)
    owner = world.caller(world.a, "owner")
    rid = await published_agent(world, owner)
    await update_resource(conn, owner, rid, {"scope": "global"})
    await world.use(world.a)
    with pytest.raises(ApiError) as exc:
        await update_resource(conn, owner, rid, {"scope": "org"})
    assert exc.value.status == 403


async def test_v2ac13_other_tenant_cannot_write_archive_or_delete_global(
    world: World,
) -> None:
    conn = world.conn
    await world.use(world.a, platform=True)
    owner = world.caller(world.a, "owner", admin=True)
    rid = await published_agent(world, owner, policies={"read": [world.open[world.a]]})
    await update_resource(conn, owner, rid, {"scope": "global"})
    await world.use(world.b)
    intruder = world.caller(world.b, "intruder", admin=True)
    for call in (
        lambda: update_resource(conn, intruder, rid, {"name": "Hijacked"}),
        lambda: set_archived(conn, intruder, rid, True),
        lambda: delete_resource(conn, intruder, rid),
    ):
        with pytest.raises(ApiError) as exc:
            await call()
        assert exc.value.status == 403
    await world.use(world.a)
    assert (await update_resource(conn, owner, rid, {"name": "Mine"}))["name"] == "Mine"
    await set_archived(conn, owner, rid, True)
    await delete_resource(conn, owner, rid)


async def test_unknown_scope_is_422(world: World) -> None:
    with pytest.raises(ApiError) as exc:
        await create_resource(
            world.conn, world.caller(world.a), agent_body(scope="galaxy")
        )
    assert exc.value.extra["errors"][0]["field"] == "scope"


async def test_org_scope_rejects_a_product(world: World) -> None:
    with pytest.raises(ApiError) as exc:
        await create_resource(
            world.conn, world.caller(world.a), agent_body(product="alpha")
        )
    assert exc.value.extra["errors"][0]["field"] == "product"


async def test_same_slug_allowed_in_different_products(world: World) -> None:
    conn = world.conn
    for product in ("alpha", "beta"):
        out = await create_resource(
            conn,
            world.caller(world.a),
            agent_body("shared-slug", scope="product", product=product),
        )
        assert out["product"] == product
    with pytest.raises(ApiError) as exc:
        await create_resource(
            conn,
            world.caller(world.a),
            agent_body("shared-slug", scope="product", product="alpha"),
        )
    assert exc.value.error == "slug_taken"
