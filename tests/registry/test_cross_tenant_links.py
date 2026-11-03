import uuid
from typing import Any

import psycopg
import pytest

from krep.api.errors import ApiError
from krep.registry.bundle import resolve_bundle
from krep.registry.links import create_link
from krep.registry.prune import VersionInUse, delete_version_rows
from krep.registry.publish import publish
from krep.registry.resources import create_resource, delete_resource, update_resource
from krep.registry.versions import create_draft
from tests.registry.conftest import (
    World,
    agent_body,
    scalar,
    skill_body,
    skill_zip,
    version_id_of,
)


async def make(
    world: World,
    tenant: uuid.UUID,
    kind: str,
    slug: str,
    *,
    scope: str = "org",
    product: str | None = None,
    publish_it: bool = True,
) -> uuid.UUID:
    caller = world.caller(tenant, "owner", admin=True, product=product)
    created = "org" if scope == "global" else scope
    extra = {
        "scope": created,
        "policies": {"read": [world.open[tenant]]},
        **({"product": product} if product else {}),
    }
    await world.use(tenant)
    if kind == "agent":
        body = agent_body(slug, **extra)
    else:
        body = {**skill_body(slug), **extra}
    rid = (await create_resource(world.conn, caller, body))["id"]
    if publish_it:
        await publish(world.conn, caller, rid, 1)
    if scope == "global":
        await world.use(tenant, platform=True)
        await update_resource(world.conn, caller, rid, {"scope": "global"})
        await world.use(tenant)
    return rid


async def link(
    world: World,
    tenant: uuid.UUID,
    source: uuid.UUID,
    target: uuid.UUID,
    product: str | None = None,
    auto_load: bool = False,
) -> dict[str, Any]:
    await world.use(tenant)
    return await create_link(
        world.conn,
        world.caller(tenant, "owner", admin=True, product=product),
        source,
        target,
        "uses",
        "out",
        None,
        auto_load,
    )


async def set_rule(world: World, source: str, target: str, allowed: bool) -> None:
    await world.conn.execute("RESET ROLE")
    await world.conn.execute(
        "UPDATE link_scope_rules SET allowed = %s WHERE source_scope = %s AND target_scope = %s",
        (allowed, source, target),
    )
    await world.conn.execute("SET LOCAL ROLE krep_app")


@pytest.mark.parametrize(
    ("source_scope", "source_product", "target_scope", "target_product"),
    [
        ("org", None, "org", None),
        ("org", None, "product", "alpha"),
        ("product", "alpha", "org", None),
        ("product", "alpha", "product", "alpha"),
        ("global", None, "global", None),
        ("org", None, "global", None),
        ("product", "alpha", "global", None),
    ],
)
async def test_v2ac15_allowed_scope_pairs_link(
    world: World,
    source_scope: str,
    source_product: str | None,
    target_scope: str,
    target_product: str | None,
) -> None:
    source = await make(
        world, world.a, "agent", "src", scope=source_scope, product=source_product
    )
    target = await make(
        world, world.a, "skill", "tgt", scope=target_scope, product=target_product
    )
    out = await link(
        world, world.a, source, target, product=source_product or target_product
    )
    assert out["status"] == "accepted"


@pytest.mark.parametrize(
    ("target_scope", "target_product"), [("org", None), ("product", "alpha")]
)
async def test_v2ac15_global_to_org_or_product_is_422(
    world: World, target_scope: str, target_product: str | None
) -> None:
    source = await make(world, world.a, "agent", "src", scope="global")
    target = await make(
        world, world.a, "skill", "tgt", scope=target_scope, product=target_product
    )
    with pytest.raises(ApiError) as exc:
        await link(world, world.a, source, target, product=target_product)
    assert (exc.value.status, exc.value.error) == (422, "link_scope_not_allowed")


async def test_v2ac15_cross_product_target_is_hidden_not_linkable(
    world: World,
) -> None:
    source = await make(
        world, world.a, "agent", "src", scope="product", product="alpha"
    )
    target = await make(world, world.a, "skill", "tgt", scope="product", product="beta")
    with pytest.raises(ApiError) as exc:
        await link(world, world.a, source, target, product="alpha")
    assert exc.value.status == 404


async def test_v2ac15_flipping_a_seed_row_changes_the_verdict(world: World) -> None:
    source = await make(world, world.a, "agent", "src")
    target = await make(world, world.a, "skill", "tgt", scope="global")
    await set_rule(world, "org", "global", False)
    with pytest.raises(ApiError) as exc:
        await link(world, world.a, source, target)
    assert (exc.value.status, exc.value.error) == (422, "link_scope_not_allowed")
    await set_rule(world, "org", "global", True)
    assert (await link(world, world.a, source, target))["status"] == "accepted"


async def test_v2ac15_rule_table_refuses_global_to_org_allowed(world: World) -> None:
    await world.conn.execute("RESET ROLE")
    with pytest.raises(psycopg.errors.CheckViolation):
        async with world.conn.transaction():
            await world.conn.execute(
                "UPDATE link_scope_rules SET allowed = true "
                "WHERE source_scope = 'global' AND target_scope = 'org'"
            )
    await world.conn.execute("SET LOCAL ROLE krep_app")


async def linked_world(world: World) -> tuple[uuid.UUID, uuid.UUID]:
    skill = await make(world, world.a, "skill", "shared-skill", scope="global")
    agent = await make(world, world.b, "agent", "b-agent", publish_it=False)
    await link(world, world.b, agent, skill, auto_load=True)
    await world.use(world.b)
    await publish(world.conn, world.caller(world.b, "owner", admin=True), agent, 1)
    return skill, agent


async def test_v2ac15_org_agent_publishes_with_frozen_cross_tenant_dependency(
    world: World,
) -> None:
    skill, agent = await linked_world(world)
    await world.use(world.b)
    dep = await scalar(
        world.conn,
        "SELECT depends_on_version_id FROM registry_version_deps d "
        "JOIN registry_versions v ON v.id = d.version_id WHERE v.registry_id = %s",
        agent,
    )
    assert dep == await version_id_of(world.conn, skill, 1)
    assert (
        await scalar(
            world.conn,
            "SELECT tenant_id FROM registry_version_deps WHERE depends_on_version_id = %s",
            dep,
        )
        == world.b
    )


async def test_v2ac15_bundle_for_any_caller_is_unaffected_by_later_global_versions(
    world: World,
) -> None:
    skill, agent = await linked_world(world)
    await world.use(world.a)
    owner = world.caller(world.a, "owner", admin=True)
    draft = await create_draft(
        world.conn, owner, skill, archive=skill_zip("shared-skill", "body 2")
    )
    await publish(world.conn, owner, skill, draft["version"]["version"])
    await world.use(world.b)
    bundle = await resolve_bundle(
        world.conn, world.caller(world.b, "stranger"), agent, None
    )
    assert [(d["slug"], d["version"]) for d in bundle["dependencies"]] == [
        ("shared-skill", 1)
    ]


async def test_v2ac15_global_version_and_resource_are_protected(world: World) -> None:
    skill, _ = await linked_world(world)
    await world.use(world.a)
    version = await version_id_of(world.conn, skill, 1)
    with pytest.raises(VersionInUse) as in_use:
        await delete_version_rows(world.conn, world.a, version)
    assert in_use.value.referrers
    with pytest.raises(ApiError) as exc:
        await delete_resource(
            world.conn, world.caller(world.a, "owner", admin=True), skill
        )
    assert (exc.value.status, exc.value.error) == (409, "resource_in_use")


async def test_referrers_are_counts_for_org_callers_and_slugs_for_platform(
    world: World,
) -> None:
    skill, _ = await linked_world(world)
    owner = world.caller(world.a, "owner", admin=True)
    slug_b = await scalar(
        world.conn, "SELECT slug FROM organizations WHERE id = %s", world.b
    )
    await world.use(world.a)
    with pytest.raises(ApiError) as exc:
        await delete_resource(world.conn, owner, skill)
    assert slug_b not in str(exc.value.extra)
    assert exc.value.extra["referrers"] == [{"count": 2}]
    await world.use(world.a, platform=True)
    with pytest.raises(ApiError) as exc:
        await delete_resource(world.conn, owner, skill)
    assert {r["organization"] for r in exc.value.extra["referrers"]} == {slug_b}


async def test_referrer_lookup_restores_the_callers_tenant(world: World) -> None:
    skill, _ = await linked_world(world)
    await world.use(world.a)
    with pytest.raises(ApiError):
        await delete_resource(
            world.conn, world.caller(world.a, "owner", admin=True), skill
        )
    cur = await world.conn.execute("SELECT current_setting('app.tenant_id')")
    row = await cur.fetchone()
    assert row == (str(world.a),)


async def test_cross_tenant_link_to_a_demoted_resource_is_hidden(
    world: World,
) -> None:
    skill = await make(world, world.a, "skill", "shared-skill", scope="global")
    agent = await make(world, world.b, "agent", "b-agent")
    await world.use(world.a)
    await update_resource(
        world.conn, world.caller(world.a, "owner", admin=True), skill, {"scope": "org"}
    )
    with pytest.raises(ApiError) as exc:
        await link(world, world.b, agent, skill)
    assert exc.value.status == 404


async def test_foreign_global_as_source_is_refused(world: World) -> None:
    skill = await make(world, world.a, "skill", "shared-skill", scope="global")
    agent = await make(world, world.a, "agent", "a-agent", scope="global")
    await world.use(world.b)
    with pytest.raises(ApiError) as exc:
        await create_link(
            world.conn,
            world.caller(world.b, "owner", admin=True),
            skill,
            agent,
            "uses",
            "in",
            None,
            False,
        )
    assert exc.value.status == 403
