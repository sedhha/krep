import uuid

import psycopg
import pytest
from psycopg import AsyncConnection

from tests.conftest import role_url
from tests.db.test_rls import use_tenant


async def organization(conn: AsyncConnection) -> uuid.UUID:
    cur = await conn.execute(
        "INSERT INTO organizations (slug, name, created_by) VALUES (%s, 'Org', 'u') RETURNING id",
        (f"org-{uuid.uuid4().hex}",),
    )
    return (await cur.fetchone())[0]


async def resource(
    conn: AsyncConnection,
    tenant: uuid.UUID,
    scope: str = "org",
    product: uuid.UUID | None = None,
) -> uuid.UUID:
    await use_tenant(conn, tenant)
    cur = await conn.execute(
        "INSERT INTO registry (tenant_id, type, slug, name, created_by, updated_by, scope, product_id) VALUES (%s, 'agent', 'same-slug', 'Agent', 'u', 'u', %s, %s) RETURNING id",
        (tenant, scope, product),
    )
    return (await cur.fetchone())[0]


async def test_v2ac17_platform_and_scope_rules(owner_conn: AsyncConnection):
    cur = await owner_conn.execute(
        "SELECT id, slug FROM organizations WHERE is_platform"
    )
    rows = await cur.fetchall()
    assert len(rows) == 1 and rows[0][1] == "platform"
    assert (await (await owner_conn.execute("SELECT platform_tenant_id()")).fetchone())[
        0
    ] == rows[0][0]
    with pytest.raises(psycopg.errors.UniqueViolation):
        async with owner_conn.transaction():
            await owner_conn.execute(
                "INSERT INTO organizations (slug, name, created_by, is_platform) VALUES ('platform-two', 'P', 'u', true)"
            )
    cur = await owner_conn.execute(
        "SELECT source_scope, target_scope, allowed FROM link_scope_rules"
    )
    assert set(await cur.fetchall()) == {
        (a, b, a != "global" or b == "global")
        for a in ("org", "product", "global")
        for b in ("org", "product", "global")
    }
    with pytest.raises(psycopg.errors.CheckViolation):
        await owner_conn.execute(
            "UPDATE link_scope_rules SET allowed = true WHERE source_scope = 'global' AND target_scope = 'org'"
        )


async def test_v2ac17_scope_constraints_and_product_uniqueness(
    owner_conn: AsyncConnection,
):
    tenant = await organization(owner_conn)
    await use_tenant(owner_conn, tenant)
    cur = await owner_conn.execute(
        "INSERT INTO products (tenant_id, slug, name, created_by) VALUES (%s, 'product-one', 'P', 'u'), (%s, 'product-two', 'P', 'u') RETURNING id",
        (tenant, tenant),
    )
    products = [row[0] for row in await cur.fetchall()]
    await resource(owner_conn, tenant)
    for product in products:
        await resource(owner_conn, tenant, "product", product)
    for scope, product, error in [
        ("product", None, psycopg.errors.CheckViolation),
        ("org", products[0], psycopg.errors.CheckViolation),
        ("global", products[0], psycopg.errors.CheckViolation),
        ("invalid", None, psycopg.errors.CheckViolation),
        ("org", None, psycopg.errors.UniqueViolation),
    ]:
        with pytest.raises(error):
            async with owner_conn.transaction():
                await resource(owner_conn, tenant, scope, product)


async def test_v2ac17_global_scope_requires_flag_on_insert_and_update(
    owner_conn: AsyncConnection,
):
    tenant = await organization(owner_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        async with owner_conn.transaction():
            await resource(owner_conn, tenant, "global")
    rid = await resource(owner_conn, tenant)
    with pytest.raises(psycopg.errors.CheckViolation):
        async with owner_conn.transaction():
            await owner_conn.execute(
                "UPDATE registry SET scope = 'global' WHERE id = %s", (rid,)
            )
    await owner_conn.execute("SET LOCAL app.platform_admin = 'on'")
    await owner_conn.execute(
        "UPDATE registry SET scope = 'global' WHERE id = %s", (rid,)
    )
    await owner_conn.execute("SET LOCAL app.platform_admin = ''")
    await owner_conn.execute(
        "UPDATE registry SET name = 'Renamed' WHERE id = %s", (rid,)
    )
    await owner_conn.execute("UPDATE registry SET scope = 'org' WHERE id = %s", (rid,))


@pytest.mark.parametrize("role", ["krep_app", "krep_platform"])
async def test_v2ac8_role_privileges(migrated_db: str, role: str):
    async with await psycopg.AsyncConnection.connect(
        role_url(role, migrated_db)
    ) as conn:
        for table, statement in [
            (
                "organizations",
                "INSERT INTO organizations (slug,name,created_by) VALUES ('grant-test','G','u')",
            ),
            (
                "platform_admins",
                "INSERT INTO platform_admins (user_id,granted_by) VALUES ('grant-test','u')",
            ),
            (
                "disabled_users",
                "INSERT INTO disabled_users (user_id,disabled_by) VALUES ('grant-test','u')",
            ),
            (
                "admin_audit_log",
                "INSERT INTO admin_audit_log (actor,action) VALUES ('u','test')",
            ),
        ]:
            if role == "krep_app" and table != "admin_audit_log":
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with conn.transaction():
                        await conn.execute(statement)
            else:
                await conn.execute(statement)
            if table != "admin_audit_log":
                await conn.execute(f"SELECT * FROM {table}")
        if role == "krep_app":
            for statement in (
                "SELECT * FROM admin_audit_log",
                "UPDATE admin_audit_log SET actor = 'x'",
                "DELETE FROM admin_audit_log",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with conn.transaction():
                        await conn.execute(statement)
        if role == "krep_platform":
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                async with conn.transaction():
                    await conn.execute(
                        "INSERT INTO products (tenant_id,slug,name,created_by) VALUES (platform_tenant_id(),'forbidden','P','u')"
                    )
        else:
            await conn.execute("SELECT id, username, email, name FROM auth_users")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                async with conn.transaction():
                    await conn.execute('SELECT * FROM auth."user"')
        await conn.rollback()
