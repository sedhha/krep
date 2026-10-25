import uuid
from typing import Any, LiteralString

import psycopg
import pytest
from psycopg import AsyncConnection

TENANT = str(uuid.uuid4())

TABLES = {
    "registry_types", "access_policies", "access_policy_history", "registry",
    "registry_versions", "agents", "skills", "link_rules", "registry_links",
    "registry_version_deps", "resource_limits", "search_synonyms",
    "token_issuers", "api_keys",
}

INDEXES = {
    "access_policies_tenant", "registry_tenant_type_status", "registry_tags_gin",
    "registry_tsv_gin", "registry_name_trgm", "registry_versions_drafts",
    "registry_links_src", "registry_links_tgt", "registry_version_deps_rev",
    "search_synonyms_tenant",
}


async def scope_tenant(conn: AsyncConnection) -> None:
    await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT,))
    await conn.execute(
        "INSERT INTO registry_types (type, subtype_table) VALUES ('agent', 'agents') "
        "ON CONFLICT DO NOTHING"
    )


async def insert_registry(conn: AsyncConnection, **overrides: Any) -> None:
    values: dict[str, Any] = {
        "slug": "my-agent", "name": "My agent", "description": "", "tags": [],
        "visibility": "private", "policy_id": None, **overrides,
    }
    await conn.execute(
        "INSERT INTO registry (tenant_id, type, slug, name, description, tags, "
        "visibility, policy_id, created_by, updated_by) "
        "VALUES (%(tenant)s, 'agent', %(slug)s, %(name)s, %(description)s, %(tags)s, "
        "%(visibility)s, %(policy_id)s, 'u', 'u')",
        {"tenant": TENANT, **values},
    )


async def test_tables_exist(owner_conn: AsyncConnection) -> None:
    cur = await owner_conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    assert TABLES <= {r[0] for r in await cur.fetchall()}


async def test_indexes_exist(owner_conn: AsyncConnection) -> None:
    cur = await owner_conn.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
    )
    assert INDEXES <= {r[0] for r in await cur.fetchall()}


async def test_extensions_present(owner_conn: AsyncConnection) -> None:
    cur = await owner_conn.execute(
        "SELECT extname FROM pg_extension WHERE extname IN ('pg_trgm', 'pgcrypto')"
    )
    assert {r[0] for r in await cur.fetchall()} == {"pg_trgm", "pgcrypto"}


async def test_restricted_visibility_requires_policy(owner_conn: AsyncConnection) -> None:
    await scope_tenant(owner_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        await insert_registry(owner_conn, visibility="restricted", policy_id=None)


async def test_private_visibility_without_policy_is_allowed(owner_conn: AsyncConnection) -> None:
    await scope_tenant(owner_conn)
    await insert_registry(owner_conn)


@pytest.mark.parametrize(
    "overrides",
    [
        {"slug": "A-upper"},
        {"slug": "x"},
        {"slug": "-leading-dash"},
        {"slug": "a" * 64},
        {"name": ""},
        {"name": "n" * 121},
        {"description": "d" * 2001},
        {"tags": [f"t{i}" for i in range(21)]},
        {"visibility": "public"},
    ],
)
async def test_registry_checks_fire(
    owner_conn: AsyncConnection, overrides: dict[str, Any]
) -> None:
    await scope_tenant(owner_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        await insert_registry(owner_conn, **overrides)


async def test_registry_type_check_on_registry_types(owner_conn: AsyncConnection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        await owner_conn.execute(
            "INSERT INTO registry_types (type, subtype_table) VALUES ('Bad-Type', 'x')"
        )


async def _registry_id(conn: AsyncConnection) -> uuid.UUID:
    await scope_tenant(conn)
    await insert_registry(conn)
    cur = await conn.execute("SELECT id FROM registry WHERE slug = 'my-agent'")
    row = await cur.fetchone()
    assert row is not None
    return row[0]


@pytest.mark.parametrize(
    "status,published,content_hash,ok",
    [
        ("draft", False, None, True),
        ("published", True, "abc", True),
        ("published", True, None, False),
        ("published", False, "abc", False),
        ("draft", True, None, False),
        ("draft", False, "abc", False),
    ],
)
async def test_version_status_ties_to_publish_columns(
    owner_conn: AsyncConnection,
    status: str,
    published: bool,
    content_hash: str | None,
    ok: bool,
) -> None:
    registry_id = await _registry_id(owner_conn)
    statement: LiteralString = (
        "INSERT INTO registry_versions (registry_id, tenant_id, version, status, "
        "published_at, content_hash, created_by) "
        "VALUES (%s, %s, 1, %s, CASE WHEN %s THEN now() END, %s, 'u')"
    )
    params = (registry_id, TENANT, status, published, content_hash)
    if ok:
        await owner_conn.execute(statement, params)
    else:
        with pytest.raises(psycopg.errors.CheckViolation):
            await owner_conn.execute(statement, params)


async def test_version_status_rejects_unknown_value(owner_conn: AsyncConnection) -> None:
    registry_id = await _registry_id(owner_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        await owner_conn.execute(
            "INSERT INTO registry_versions (registry_id, tenant_id, version, status, created_by) "
            "VALUES (%s, %s, 1, 'archived', 'u')",
            (registry_id, TENANT),
        )


async def test_slug_unique_per_tenant_and_type(owner_conn: AsyncConnection) -> None:
    await scope_tenant(owner_conn)
    await insert_registry(owner_conn)
    with pytest.raises(psycopg.errors.UniqueViolation):
        await insert_registry(owner_conn)
