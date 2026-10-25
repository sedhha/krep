import uuid
from typing import Literal, LiteralString

import psycopg
import pytest
from psycopg import AsyncConnection

from tests.db.test_schema import (
    TENANT,
    ZIP,
    insert_registry,
    insert_skill,
    put_file,
    scope_tenant,
    skill_version,
)

Kind = Literal["agent", "skill"]


async def _draft(conn: AsyncConnection, kind: Kind) -> tuple[uuid.UUID, uuid.UUID]:
    if kind == "agent":
        await scope_tenant(conn)
        await insert_registry(conn, type="agent", slug="imm-agent")
        cur = await conn.execute("SELECT id FROM registry WHERE slug = 'imm-agent'")
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
        version_id: uuid.UUID = row[0]
        await conn.execute(
            "INSERT INTO agents (version_id, registry_id, tenant_id, model, system_prompt) "
            "VALUES (%s, %s, %s, 'm', 'p')",
            (version_id, registry_id, TENANT),
        )
        return registry_id, version_id
    ids = await skill_version(conn, "imm-skill")
    await insert_skill(conn, ids, await put_file(conn, ZIP))
    return ids


async def _publish(conn: AsyncConnection, version_id: uuid.UUID) -> None:
    await conn.execute(
        "UPDATE registry_versions SET status = 'published', published_at = now(), "
        "content_hash = 'h' WHERE id = %s",
        (version_id,),
    )


UPDATES: dict[str, LiteralString] = {
    "registry_versions": "UPDATE registry_versions SET created_by = 'x' WHERE id = %s",
    "agents": "UPDATE agents SET model = 'x' WHERE version_id = %s",
    "skills": "UPDATE skills SET content_sha256 = content_sha256 WHERE version_id = %s",
}
TABLE_KIND: dict[str, Kind] = {
    "registry_versions": "agent",
    "agents": "agent",
    "skills": "skill",
}


@pytest.mark.parametrize("table", list(UPDATES))
async def test_ac14_published_version_and_subtype_rows_immutable(
    owner_conn: AsyncConnection, table: str
) -> None:
    _, version_id = await _draft(owner_conn, TABLE_KIND[table])
    await _publish(owner_conn, version_id)
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        async with owner_conn.transaction():
            await owner_conn.execute(UPDATES[table], (version_id,))
    assert exc.value.sqlstate == "23514"
    assert str(version_id) in str(exc.value)


@pytest.mark.parametrize("table", list(UPDATES))
async def test_ac14_draft_rows_stay_updatable_and_publish_succeeds(
    owner_conn: AsyncConnection, table: str
) -> None:
    _, version_id = await _draft(owner_conn, TABLE_KIND[table])
    cur = await owner_conn.execute(UPDATES[table], (version_id,))
    assert cur.rowcount == 1
    await _publish(owner_conn, version_id)
    cur = await owner_conn.execute(
        "SELECT status FROM registry_versions WHERE id = %s", (version_id,)
    )
    assert await cur.fetchone() == ("published",)


async def test_ac14_published_version_can_still_be_deleted(
    owner_conn: AsyncConnection,
) -> None:
    _, version_id = await _draft(owner_conn, "agent")
    await _publish(owner_conn, version_id)
    cur = await owner_conn.execute(
        "DELETE FROM registry_versions WHERE id = %s", (version_id,)
    )
    assert cur.rowcount == 1


async def test_skill_files_rows_are_never_updated(owner_conn: AsyncConnection) -> None:
    await scope_tenant(owner_conn)
    digest = await put_file(owner_conn, ZIP)
    with pytest.raises(psycopg.errors.CheckViolation):
        async with owner_conn.transaction():
            await owner_conn.execute(
                "UPDATE skill_files SET size_bytes = size_bytes "
                "WHERE tenant_id = %s AND content_sha256 = %s",
                (TENANT, digest),
            )
    cur = await owner_conn.execute(
        "DELETE FROM skill_files WHERE tenant_id = %s AND content_sha256 = %s",
        (TENANT, digest),
    )
    assert cur.rowcount == 1
