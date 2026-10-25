import hashlib
import uuid
from typing import Any, LiteralString

import psycopg
import psycopg.sql
import pytest
from psycopg import AsyncConnection

TENANT = str(uuid.uuid4())

TABLES = {
    "registry_types", "access_policies", "access_policy_history", "registry",
    "registry_versions", "agents", "skills", "skill_files", "link_rules", "registry_links",
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
        "INSERT INTO registry_types (type, subtype_table) "
        "VALUES ('agent', 'agents'), ('skill', 'skills') ON CONFLICT DO NOTHING"
    )


async def insert_registry(
    conn: AsyncConnection, type: str = "agent", **overrides: Any
) -> None:
    values: dict[str, Any] = {
        "slug": "my-agent", "name": "My agent", "description": "", "tags": [],
        "visibility": "private", "policy_id": None, **overrides,
    }
    await conn.execute(
        "INSERT INTO registry (tenant_id, type, slug, name, description, tags, "
        "visibility, policy_id, created_by, updated_by) "
        "VALUES (%(tenant)s, %(type)s, %(slug)s, %(name)s, %(description)s, %(tags)s, "
        "%(visibility)s, %(policy_id)s, 'u', 'u')",
        {"tenant": TENANT, "type": type, **values},
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
        ("draft", True, "abc", False),
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


ZIP = b"PK\x03\x04skill-bytes"
OTHER_TENANT = str(uuid.uuid4())


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def _put_file(
    conn: AsyncConnection, content: bytes = ZIP, tenant: str = TENANT
) -> str:
    await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
    digest = sha256(content)
    await conn.execute(
        "INSERT INTO skill_files (tenant_id, content_sha256, size_bytes, content) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (tenant, digest, len(content), content),
    )
    await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT,))
    return digest


async def _skill_version(
    conn: AsyncConnection, slug: str = "my-skill"
) -> tuple[uuid.UUID, uuid.UUID]:
    await scope_tenant(conn)
    await insert_registry(conn, type="skill", slug=slug)
    cur = await conn.execute("SELECT id FROM registry WHERE slug = %s", (slug,))
    row = await cur.fetchone()
    assert row is not None
    registry_id: uuid.UUID = row[0]
    cur = await conn.execute(
        "INSERT INTO registry_versions (registry_id, tenant_id, version, created_by) "
        "VALUES (%s, %s, 1, 'u') RETURNING id",
        (registry_id, TENANT),
    )
    row = await cur.fetchone()
    assert row is not None
    return registry_id, row[0]


async def _insert_skill(
    conn: AsyncConnection, ids: tuple[uuid.UUID, uuid.UUID], digest: str
) -> None:
    registry_id, version_id = ids
    await conn.execute(
        "INSERT INTO skills (version_id, registry_id, tenant_id, content_sha256) "
        "VALUES (%s, %s, %s, %s)",
        (version_id, registry_id, TENANT, digest),
    )


async def _count(conn: AsyncConnection, table: str) -> int:
    cur = await conn.execute(
        psycopg.sql.SQL("SELECT count(*) FROM {}").format(psycopg.sql.Identifier(table))
    )
    row = await cur.fetchone()
    assert row is not None
    return row[0]


async def _columns(conn: AsyncConnection, table: str) -> set[str]:
    cur = await conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    )
    return {r[0] for r in await cur.fetchall()}


async def test_skills_reference_an_archive_by_hash_not_instructions(
    owner_conn: AsyncConnection,
):
    skills = await _columns(owner_conn, "skills")
    assert "content_sha256" in skills
    assert not {"instructions", "resources", "size_bytes"} & skills
    assert {"content_sha256", "size_bytes", "content"} <= await _columns(
        owner_conn, "skill_files"
    )


async def test_skill_with_archive_is_accepted(owner_conn: AsyncConnection):
    await scope_tenant(owner_conn)
    ids = await _skill_version(owner_conn)
    await _insert_skill(owner_conn, ids, await _put_file(owner_conn))


async def test_skill_must_reference_an_existing_archive(owner_conn: AsyncConnection):
    ids = await _skill_version(owner_conn)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await _insert_skill(owner_conn, ids, sha256(b"never uploaded"))


async def test_identical_archives_in_a_tenant_share_one_file(owner_conn: AsyncConnection):
    digest = await _put_file(owner_conn)
    await _insert_skill(owner_conn, await _skill_version(owner_conn, "skill-a"), digest)
    await _insert_skill(owner_conn, await _skill_version(owner_conn, "skill-b"), digest)
    await _put_file(owner_conn)
    assert await _count(owner_conn, "skills") == 2
    assert await _count(owner_conn, "skill_files") == 1


async def test_identical_archives_in_different_tenants_are_stored_separately(
    owner_conn: AsyncConnection,
):
    await scope_tenant(owner_conn)
    await _put_file(owner_conn, tenant=TENANT)
    await _put_file(owner_conn, tenant=OTHER_TENANT)
    cur = await owner_conn.execute(
        "SELECT count(*) FROM skill_files WHERE content_sha256 = %s", (sha256(ZIP),)
    )
    row = await cur.fetchone()
    assert row is not None and row[0] == 2


async def test_referenced_archive_cannot_be_deleted(owner_conn: AsyncConnection):
    digest = await _put_file(owner_conn)
    await _insert_skill(owner_conn, await _skill_version(owner_conn), digest)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await owner_conn.execute(
            "DELETE FROM skill_files WHERE tenant_id = %s AND content_sha256 = %s",
            (TENANT, digest),
        )


async def test_archive_is_deletable_once_no_skill_references_it(
    owner_conn: AsyncConnection,
):
    digest = await _put_file(owner_conn)
    ids = await _skill_version(owner_conn)
    await _insert_skill(owner_conn, ids, digest)
    await owner_conn.execute("DELETE FROM registry_versions WHERE id = %s", (ids[1],))
    cur = await owner_conn.execute(
        "DELETE FROM skill_files WHERE tenant_id = %s AND content_sha256 = %s",
        (TENANT, digest),
    )
    assert cur.rowcount == 1


async def test_orphan_cleanup_keeps_archives_still_referenced(owner_conn: AsyncConnection):
    digest = await _put_file(owner_conn)
    first = await _skill_version(owner_conn, "skill-a")
    await _insert_skill(owner_conn, first, digest)
    await _insert_skill(owner_conn, await _skill_version(owner_conn, "skill-b"), digest)
    await owner_conn.execute("DELETE FROM registry_versions WHERE id = %s", (first[1],))
    cur = await owner_conn.execute(
        "DELETE FROM skill_files f WHERE f.tenant_id = %s AND NOT EXISTS ("
        "SELECT 1 FROM skills s WHERE s.tenant_id = f.tenant_id "
        "AND s.content_sha256 = f.content_sha256)",
        (TENANT,),
    )
    assert cur.rowcount == 0


async def test_archive_hash_must_match_its_bytes(owner_conn: AsyncConnection):
    await scope_tenant(owner_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        await owner_conn.execute(
            "INSERT INTO skill_files (tenant_id, content_sha256, size_bytes, content) "
            "VALUES (%s, %s, %s, %s)",
            (TENANT, sha256(b"something else"), len(ZIP), ZIP),
        )


async def test_archive_hash_must_be_lowercase_hex(owner_conn: AsyncConnection):
    await scope_tenant(owner_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        await owner_conn.execute(
            "INSERT INTO skill_files (tenant_id, content_sha256, size_bytes, content) "
            "VALUES (%s, %s, %s, %s)",
            (TENANT, sha256(ZIP).upper(), len(ZIP), ZIP),
        )


async def test_archive_size_bytes_must_match_its_bytes(owner_conn: AsyncConnection):
    await scope_tenant(owner_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        await owner_conn.execute(
            "INSERT INTO skill_files (tenant_id, content_sha256, size_bytes, content) "
            "VALUES (%s, %s, %s, %s)",
            (TENANT, sha256(ZIP), len(ZIP) + 1, ZIP),
        )


@pytest.mark.parametrize("size", [0, 1048577])
async def test_archive_size_bounds(owner_conn: AsyncConnection, size: int):
    await scope_tenant(owner_conn)
    content = b"\x00" * size
    with pytest.raises(psycopg.errors.CheckViolation):
        await owner_conn.execute(
            "INSERT INTO skill_files (tenant_id, content_sha256, size_bytes, content) "
            "VALUES (%s, %s, %s, %s)",
            (TENANT, sha256(content), size, content),
        )


async def test_archive_content_is_stored_out_of_line_uncompressed(
    owner_conn: AsyncConnection,
):
    cur = await owner_conn.execute(
        "SELECT attstorage FROM pg_attribute "
        "WHERE attrelid = 'skill_files'::regclass AND attname = 'content'"
    )
    row = await cur.fetchone()
    assert row is not None and row[0] == "e"
