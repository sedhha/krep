import hashlib
import uuid
from collections.abc import AsyncIterator

import psycopg
import pytest
import pytest_asyncio
from psycopg import AsyncConnection

from tests.conftest import role_url

TENANT_TABLES = [
    "access_policies", "access_policy_history", "registry", "registry_versions",
    "agents", "skills", "skill_files", "registry_links", "registry_version_deps",
    "search_synonyms",
]


async def use_tenant(conn: AsyncConnection, tenant: uuid.UUID) -> None:
    await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))


async def add_registry(conn: AsyncConnection, tenant: uuid.UUID, slug: str) -> None:
    await use_tenant(conn, tenant)
    await conn.execute(
        "INSERT INTO registry (tenant_id, type, slug, name, created_by, updated_by) "
        "VALUES (%s, 'agent', %s, 'n', 'u', 'u')",
        (tenant, slug),
    )


async def add_file(conn: AsyncConnection, tenant: uuid.UUID, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    await use_tenant(conn, tenant)
    await conn.execute(
        "INSERT INTO skill_files (tenant_id, content_sha256, size_bytes, content) "
        "VALUES (%s, %s, %s, %s)",
        (tenant, digest, len(content), content),
    )
    return digest


async def count(conn: AsyncConnection, query: str, *params: object) -> int:
    cur = await conn.execute(query, params)  # type: ignore[arg-type]
    row = await cur.fetchone()
    assert row is not None
    return row[0]


@pytest.mark.parametrize("table", TENANT_TABLES)
async def test_tenant_tables_enable_and_force_rls_with_policy(
    owner_conn: AsyncConnection, table: str
) -> None:
    cur = await owner_conn.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass",
        (table,),
    )
    assert await cur.fetchone() == (True, True)
    cur = await owner_conn.execute(
        "SELECT policyname FROM pg_policies WHERE tablename = %s", (table,)
    )
    assert await cur.fetchall() == [("tenant_isolation",)]


async def test_ac1_rls_cross_tenant_zero_rows(app_conn: AsyncConnection) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    await add_registry(app_conn, a, "agent-a")
    await add_registry(app_conn, b, "agent-b")
    await use_tenant(app_conn, a)
    assert await count(app_conn, "SELECT count(*) FROM registry WHERE tenant_id = %s", b) == 0
    assert await count(app_conn, "SELECT count(*) FROM registry WHERE tenant_id = %s", a) == 1
    assert await count(app_conn, "SELECT count(*) FROM registry") == 1


async def test_ac1_insert_for_another_tenant_fails_with_check(
    app_conn: AsyncConnection,
) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    await use_tenant(app_conn, a)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await app_conn.execute(
            "INSERT INTO registry (tenant_id, type, slug, name, created_by, updated_by) "
            "VALUES (%s, 'agent', 'forged', 'n', 'u', 'u')",
            (b,),
        )


async def test_ac1_skill_files_are_isolated_per_tenant(app_conn: AsyncConnection) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    digest = await add_file(app_conn, a, b"archive-bytes")
    await add_file(app_conn, b, b"archive-bytes")
    await use_tenant(app_conn, a)
    assert await count(app_conn, "SELECT count(*) FROM skill_files") == 1
    assert (
        await count(
            app_conn,
            "SELECT count(*) FROM skill_files WHERE tenant_id = %s AND content_sha256 = %s",
            b,
            digest,
        )
        == 0
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await app_conn.execute(
            "INSERT INTO skill_files (tenant_id, content_sha256, size_bytes, content) "
            "SELECT %s, content_sha256, size_bytes, content FROM skill_files",
            (b,),
        )


@pytest_asyncio.fixture
async def committed_synonym(migrated_db: str) -> AsyncIterator[uuid.UUID]:
    tenant = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(
        role_url("krep_app", migrated_db), autocommit=False
    ) as conn:
        await use_tenant(conn, tenant)
        await conn.execute(
            "INSERT INTO search_synonyms (tenant_id, terms, created_by) "
            "VALUES (%s, %s, 'u')",
            (tenant, ["refund", "money back"]),
        )
        await conn.commit()
        yield tenant
        await use_tenant(conn, tenant)
        await conn.execute("DELETE FROM search_synonyms WHERE tenant_id = %s", (tenant,))
        await conn.commit()


async def test_rls_unset_and_empty_setting_fail_closed(
    migrated_db: str, committed_synonym: uuid.UUID
) -> None:
    async with await psycopg.AsyncConnection.connect(
        role_url("krep_app", migrated_db)
    ) as conn:
        cur = await conn.execute("SELECT current_setting('app.tenant_id', true)")
        assert await cur.fetchone() == (None,)
        assert await count(conn, "SELECT count(*) FROM search_synonyms") == 0
        await use_tenant(conn, committed_synonym)
        assert await count(conn, "SELECT count(*) FROM search_synonyms") == 1
        await conn.commit()
        cur = await conn.execute("SELECT current_setting('app.tenant_id', true)")
        assert await cur.fetchone() == ("",)
        assert await count(conn, "SELECT count(*) FROM search_synonyms") == 0


async def test_krep_app_has_no_ddl_and_read_only_global_tables(
    app_conn: AsyncConnection,
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await app_conn.execute("CREATE TABLE intruder (id int)")
    await app_conn.rollback()
    statements = {
        "registry_types": "INSERT INTO registry_types (type, subtype_table) VALUES ('tool', 'tools')",
        "link_rules": "INSERT INTO link_rules (source_type, target_type, relation, accept_by) "
        "VALUES ('skill', 'agent', 'uses', 'source')",
        "resource_limits": "INSERT INTO resource_limits (scope_type, limit_key, value) "
        "VALUES ('global', 'x', 1)",
        "token_issuers": "INSERT INTO token_issuers (issuer, audience, jwks_uri, tenant_id) "
        "VALUES ('i', 'a', 'https://x', gen_random_uuid())",
        "api_keys": "INSERT INTO api_keys (tenant_id, name, key_hash) "
        "VALUES (gen_random_uuid(), 'k', '\\x00')",
    }
    for table, statement in statements.items():
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await app_conn.execute(statement)  # type: ignore[arg-type]
        await app_conn.rollback()
        await app_conn.execute(f"SELECT count(*) FROM {table}")  # type: ignore[arg-type]
        for verb in ("UPDATE {t} SET value = value", "DELETE FROM {t}"):
            if table != "resource_limits" and verb.startswith("UPDATE"):
                continue
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await app_conn.execute(verb.format(t=table))  # type: ignore[arg-type]
            await app_conn.rollback()


async def test_resource_limits_visible_to_app_only_for_global_scope(
    app_conn: AsyncConnection,
) -> None:
    cur = await app_conn.execute("SELECT DISTINCT scope_type FROM resource_limits")
    assert await cur.fetchall() == [("global",)]
