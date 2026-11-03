import hashlib

import psycopg
import pytest
from psycopg import AsyncConnection

from tests.db.test_rls import use_tenant
from tests.db.test_v2_schema import organization, resource


async def test_v2ac17_new_tenant_tables_and_memberships(owner_conn: AsyncConnection):
    conn = owner_conn
    a, b = await organization(conn), await organization(conn)
    for tenant in (a, b):
        await use_tenant(conn, tenant)
        await conn.execute(
            "INSERT INTO products (tenant_id,slug,name,created_by) VALUES (%s,'product-one','P','u')",
            (tenant,),
        )
        await conn.execute(
            "INSERT INTO auth_configs (tenant_id,adapter,updated_by) VALUES (%s,'hmac','u')",
            (tenant,),
        )
        await conn.execute(
            "INSERT INTO memberships (tenant_id,user_id,created_by) VALUES (%s,'me','u'),(%s,'other','u')",
            (tenant, tenant),
        )
    await conn.execute("SET LOCAL ROLE krep_app")
    await use_tenant(conn, a)
    await conn.execute("SET LOCAL app.user_id = 'me'")
    for table in ("products", "auth_configs"):
        assert (
            await (await conn.execute(f"SELECT tenant_id FROM {table}")).fetchall()
        ) == [(a,)]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            async with conn.transaction():
                await conn.execute(
                    f"UPDATE {table} SET tenant_id = %s WHERE tenant_id = %s", (b, a)
                )
    assert set(
        await (
            await conn.execute("SELECT tenant_id,user_id FROM memberships")
        ).fetchall()
    ) == {(a, "me"), (a, "other"), (b, "me")}
    assert (
        await conn.execute("DELETE FROM memberships WHERE tenant_id = %s", (b,))
    ).rowcount == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO memberships (tenant_id,user_id,created_by) VALUES (%s,'forged','u')",
                (b,),
            )


async def test_v2ac17_global_reads_do_not_grant_writes_or_unrelated_rows(
    owner_conn: AsyncConnection,
):
    conn = owner_conn
    a, b = await organization(conn), await organization(conn)
    await conn.execute("SET LOCAL app.platform_admin = 'on'")
    global_id = await resource(conn, a, "global")
    await conn.execute(
        "INSERT INTO registry (tenant_id,type,slug,name,created_by,updated_by) VALUES (%s,'agent','private-agent','Private','u','u')",
        (a,),
    )
    cur = await conn.execute(
        "INSERT INTO access_policies (tenant_id,name,ast,source,compiled_path,compiler_version,created_by,updated_by) VALUES (%s,'shared','{}','true','true',1,'u','u'),(%s,'hidden','{}','true','true',1,'u','u') RETURNING id",
        (a, a),
    )
    shared, hidden = [r[0] for r in await cur.fetchall()]
    await conn.execute(
        "INSERT INTO registry_policies VALUES (%s,%s,'read',%s)", (global_id, a, shared)
    )
    cur = await conn.execute(
        "INSERT INTO registry_versions (registry_id,tenant_id,version,created_by) VALUES (%s,%s,1,'u') RETURNING id",
        (global_id, a),
    )
    version = (await cur.fetchone())[0]
    await conn.execute(
        "INSERT INTO agents (version_id,registry_id,tenant_id,model,system_prompt) VALUES (%s,%s,%s,'model','prompt')",
        (version, global_id, a),
    )
    await conn.execute("SET LOCAL ROLE krep_app")
    await use_tenant(conn, b)
    assert await (
        await conn.execute("SELECT id FROM registry WHERE tenant_id = %s", (a,))
    ).fetchall() == [(global_id,)]
    assert await (
        await conn.execute("SELECT id FROM registry_versions")
    ).fetchall() == [(version,)]
    assert await (await conn.execute("SELECT version_id FROM agents")).fetchall() == [
        (version,)
    ]
    assert await (await conn.execute("SELECT id FROM access_policies")).fetchall() == [
        (shared,)
    ]
    assert await (
        await conn.execute("SELECT policy_id FROM registry_policies")
    ).fetchall() == [(shared,)]
    for table in (
        "registry",
        "registry_versions",
        "agents",
        "access_policies",
        "registry_policies",
    ):
        assert (
            await conn.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (a,))
        ).rowcount == 0
    assert (
        await conn.execute(
            "UPDATE registry SET name = 'stolen' WHERE id = %s", (global_id,)
        )
    ).rowcount == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO registry_policies VALUES (%s,%s,'manage',%s)",
                (global_id, a, hidden),
            )


async def test_v2ac17_global_skill_files_only_when_referenced(
    owner_conn: AsyncConnection,
):
    conn = owner_conn
    a, b = await organization(conn), await organization(conn)
    await use_tenant(conn, a)
    await conn.execute("SET LOCAL app.platform_admin = 'on'")
    digests = []
    for content in (b"global", b"private"):
        digest = hashlib.sha256(content).hexdigest()
        digests.append(digest)
        await conn.execute(
            "INSERT INTO skill_files VALUES (%s,%s,%s,%s)",
            (a, digest, len(content), content),
        )
    cur = await conn.execute(
        "INSERT INTO registry (tenant_id,type,slug,name,scope,created_by,updated_by) VALUES (%s,'skill','global-skill','S','global','u','u') RETURNING id",
        (a,),
    )
    rid = (await cur.fetchone())[0]
    cur = await conn.execute(
        "INSERT INTO registry_versions (registry_id,tenant_id,version,created_by) VALUES (%s,%s,1,'u') RETURNING id",
        (rid, a),
    )
    version = (await cur.fetchone())[0]
    await conn.execute(
        "INSERT INTO skills (version_id,registry_id,tenant_id,content_sha256) VALUES (%s,%s,%s,%s)",
        (version, rid, a, digests[0]),
    )
    await conn.execute("SET LOCAL ROLE krep_app")
    await use_tenant(conn, b)
    assert await (await conn.execute("SELECT version_id FROM skills")).fetchall() == [
        (version,)
    ]
    assert await (await conn.execute("SELECT content FROM skill_files")).fetchall() == [
        (b"global",)
    ]
    assert (
        await conn.execute("DELETE FROM skill_files WHERE tenant_id = %s", (a,))
    ).rowcount == 0
