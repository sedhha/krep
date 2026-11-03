import uuid

import pytest

from krep.api.errors import ApiError
from krep.org import audit, service
from krep.policy.parser import parse
from tests.org.conftest import AddUser, Pool, Seed, new_slug


async def test_v2ac6_create_organization_rolls_back_as_one_transaction(
    platform_pool: Pool, add_user: AddUser
) -> None:
    await add_user("svc-admin")
    slug = new_slug()
    with pytest.raises(ApiError) as exc:
        async with platform_pool.connection() as conn, conn.transaction():
            await service.create_organization(
                conn,
                "actor",
                slug,
                "Svc",
                "svc-admin",
                None,
                {"adapter": "hmac", "config": {}, "secret": "x"},
            )
    assert exc.value.error == "auth_config_invalid"
    async with platform_pool.connection() as conn:
        cur = await conn.execute("SELECT 1 FROM organizations WHERE slug = %s", (slug,))
        assert await cur.fetchone() is None


async def test_v2ac6_init_capabilities_is_idempotent(
    platform_pool: Pool, seed: Seed
) -> None:
    tenant = (await seed.org(rules=None)).id
    rules = {
        "registry-admins": parse('token.groups == "a"'),
        "registry-writers": parse('token.groups == "w"'),
    }
    async with platform_pool.connection() as conn, conn.transaction():
        await service.init_capabilities(conn, tenant, rules, "ops")
        await service.init_capabilities(
            conn, tenant, {"registry-admins": parse('token.groups == "changed"')}, "ops"
        )
        cur = await conn.execute(
            "SELECT name, rev, source FROM access_policies WHERE tenant_id = %s ORDER BY name",
            (tenant,),
        )
        assert await cur.fetchall() == [
            ("registry-admins", 1, 'token.groups == "a"'),
            ("registry-writers", 1, 'token.groups == "w"'),
        ]


async def test_v2ac8_audit_record_writes_actor_action_and_detail(
    platform_pool: Pool,
) -> None:
    tenant = uuid.uuid4()
    async with platform_pool.connection() as conn, conn.transaction():
        await audit.record(conn, "someone", "x.y", tenant, "target-1", {"k": "v"})
        cur = await conn.execute(
            "SELECT actor, action, tenant_id, target, detail FROM admin_audit_log WHERE tenant_id = %s",
            (tenant,),
        )
        assert await cur.fetchall() == [
            ("someone", "x.y", tenant, "target-1", {"k": "v"})
        ]
