from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from krep.api.errors import ApiError
from krep.identity.resolve import Caller
from krep.registry.prune import VersionInUse, delete_version_rows
from krep.registry.resources import (
    AGENT,
    SKILL,
    Row,
    can_edit,
    can_read,
    enforce_draft_cap,
    fetch_row,
    insert_spec,
    lock_for_edit,
    not_found,
    release_skill_files,
    store_skill_file,
    validated_subtype,
    validation_failed,
)
from krep.registry.skill_archive import SkillArchive
from krep.registry.specs import FieldError
from krep.registry.subtypes import (
    copy_generic_spec,
    delete_generic_spec,
    load_generic_spec,
)

VERSION_COLUMNS = "id, registry_id, version, status, content_hash, created_by, created_at, published_at"
AGENT_SPEC_COLUMNS = (
    "model",
    "model_config",
    "system_prompt",
    "input_schema",
    "output_schema",
    "hitl_rules",
    "runtime_config",
    "tool_refs",
)


def version_not_found() -> ApiError:
    return ApiError(404, "not_found", "version not found")


async def fetch_version(conn: AsyncConnection, resource_id: UUID, n: int) -> Row | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {VERSION_COLUMNS} FROM registry_versions WHERE registry_id = %s AND version = %s",
            (resource_id, n),
        )
        return await cur.fetchone()


async def require_version(conn: AsyncConnection, resource_id: UUID, n: int) -> Row:
    row = await fetch_version(conn, resource_id, n)
    if row is None:
        raise version_not_found()
    return row


async def load_spec(conn: AsyncConnection, resource_type: str, version_id: UUID) -> Row:
    if resource_type not in (SKILL, AGENT):
        return await load_generic_spec(conn, resource_type, version_id)
    async with conn.cursor(row_factory=dict_row) as cur:
        if resource_type == SKILL:
            await cur.execute(
                "SELECT s.content_sha256, f.size_bytes FROM skills s "
                "JOIN skill_files f ON f.tenant_id = s.tenant_id AND f.content_sha256 = s.content_sha256 "
                "WHERE s.version_id = %s",
                (version_id,),
            )
        else:
            await cur.execute(
                f"SELECT {', '.join(AGENT_SPEC_COLUMNS)} FROM agents WHERE version_id = %s",
                (version_id,),
            )
        row = await cur.fetchone()
    assert row is not None
    return row


async def spec_view(
    conn: AsyncConnection,
    resource_id: UUID,
    resource_type: str,
    version_id: UUID,
    n: int,
) -> Row:
    spec = await load_spec(conn, resource_type, version_id)
    if resource_type == SKILL:
        spec["archive_path"] = f"/v1/registry/{resource_id}/versions/{n}/archive"
    return spec


async def _view(
    conn: AsyncConnection, resource: Row, version: Row, with_spec: bool
) -> Row:
    view: Row = {
        key: version[key]
        for key in (
            "version",
            "status",
            "content_hash",
            "created_by",
            "created_at",
            "published_at",
        )
    }
    if with_spec:
        view["spec"] = await spec_view(
            conn, resource["id"], resource["type"], version["id"], version["version"]
        )
    return view


async def _readable(conn: AsyncConnection, caller: Caller, resource_id: UUID) -> Row:
    row = await fetch_row(conn, resource_id)
    if row is None or not await can_read(conn, caller, row):
        raise not_found()
    return row


async def _visible_version(
    conn: AsyncConnection, caller: Caller, resource: Row, n: int
) -> Row:
    version = await fetch_version(conn, resource["id"], n)
    if version is None or (
        version["status"] == "draft" and not await can_edit(caller, resource)
    ):
        raise version_not_found()
    return version


async def list_versions(
    conn: AsyncConnection, caller: Caller, resource_id: UUID
) -> list[Row]:
    resource = await _readable(conn, caller, resource_id)
    editable = await can_edit(caller, resource)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {VERSION_COLUMNS} FROM registry_versions WHERE registry_id = %s "
            "AND (status = 'published' OR %s) ORDER BY version",
            (resource_id, editable),
        )
        rows = await cur.fetchall()
    return [await _view(conn, resource, row, False) for row in rows]


async def get_version(
    conn: AsyncConnection, caller: Caller, resource_id: UUID, n: int
) -> Row:
    resource = await _readable(conn, caller, resource_id)
    version = await _visible_version(conn, caller, resource, n)
    return await _view(conn, resource, version, True)


async def get_archive(
    conn: AsyncConnection, caller: Caller, resource_id: UUID, n: int
) -> tuple[bytes, str]:
    resource = await _readable(conn, caller, resource_id)
    version = await _visible_version(conn, caller, resource, n)
    if resource["type"] != SKILL:
        raise version_not_found()
    cur = await conn.execute(
        "SELECT f.content, f.content_sha256 FROM skills s "
        "JOIN skill_files f ON f.tenant_id = s.tenant_id AND f.content_sha256 = s.content_sha256 "
        "WHERE s.version_id = %s",
        (version["id"],),
    )
    row = await cur.fetchone()
    assert row is not None
    return bytes(row[0]), row[1]


async def _insert_skill_row(
    conn: AsyncConnection,
    tenant_id: UUID,
    resource_id: UUID,
    version_id: UUID,
    content_sha256: str,
) -> None:
    await conn.execute(
        "INSERT INTO skills (version_id, registry_id, tenant_id, content_sha256) "
        "VALUES (%s, %s, %s, %s)",
        (version_id, resource_id, tenant_id, content_sha256),
    )


async def _copy_subtype(
    conn: AsyncConnection, resource: Row, source_version_id: UUID, new_version_id: UUID
) -> None:
    if resource["type"] == SKILL:
        await conn.execute(
            "INSERT INTO skills (version_id, registry_id, tenant_id, content_sha256) "
            "SELECT %s, registry_id, tenant_id, content_sha256 FROM skills WHERE version_id = %s",
            (new_version_id, source_version_id),
        )
    elif resource["type"] == AGENT:
        columns = ", ".join(AGENT_SPEC_COLUMNS)
        await conn.execute(
            f"INSERT INTO agents (version_id, registry_id, tenant_id, {columns}) "
            f"SELECT %s, registry_id, tenant_id, {columns} FROM agents WHERE version_id = %s",
            (new_version_id, source_version_id),
        )
    else:
        await copy_generic_spec(
            conn, resource["type"], source_version_id, new_version_id
        )


async def _source_version(
    conn: AsyncConnection, resource: Row, from_version: int | None
) -> Row:
    if from_version is not None:
        return await require_version(conn, resource["id"], from_version)
    if resource["current_version_id"] is not None:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {VERSION_COLUMNS} FROM registry_versions WHERE id = %s",
                (resource["current_version_id"],),
            )
            current = await cur.fetchone()
        assert current is not None
        return current
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {VERSION_COLUMNS} FROM registry_versions WHERE registry_id = %s "
            "ORDER BY version DESC LIMIT 1",
            (resource["id"],),
        )
        latest = await cur.fetchone()
    if latest is None:
        raise ApiError(409, "no_source_version", "resource has no version to copy")
    return latest


def _checked_archive(resource: Row, data: bytes) -> SkillArchive:
    archive, problems = validated_subtype(
        {
            "type": resource["type"],
            "slug": resource["slug"],
            "spec": None,
            "archive": data,
        }
    )
    if problems or archive is None:
        raise validation_failed(problems)
    return archive


async def create_draft(
    conn: AsyncConnection,
    caller: Caller,
    resource_id: UUID,
    from_version: int | None = None,
    archive: bytes | None = None,
) -> Row:
    resource = await lock_for_edit(conn, caller, resource_id)
    checked: SkillArchive | None = None
    source: Row | None = None
    if archive is not None:
        if from_version is not None:
            raise validation_failed(
                [
                    FieldError(
                        "from_version", "cannot be combined with an archive upload"
                    )
                ]
            )
        checked = _checked_archive(resource, archive)
    else:
        source = await _source_version(conn, resource, from_version)
    await enforce_draft_cap(conn, caller.tenant_id, resource["type"])
    cur = await conn.execute(
        "UPDATE registry SET next_version = next_version + 1 WHERE id = %s RETURNING next_version - 1",
        (resource_id,),
    )
    number = (await cur.fetchone() or (0,))[0]
    cur = await conn.execute(
        "INSERT INTO registry_versions (registry_id, tenant_id, version, created_by) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (resource_id, caller.tenant_id, number, caller.user_id),
    )
    inserted = await cur.fetchone()
    assert inserted is not None
    version_id: UUID = inserted[0]
    if checked is not None and archive is not None:
        await store_skill_file(conn, caller.tenant_id, checked, archive)
        await _insert_skill_row(
            conn, caller.tenant_id, resource_id, version_id, checked.content_sha256
        )
    else:
        assert source is not None
        await _copy_subtype(conn, resource, source["id"], version_id)
    out: Row = {"id": resource_id, "version": {"version": number, "status": "draft"}}
    if checked is not None:
        out["warnings"] = checked.warnings
    return out


async def replace_draft(
    conn: AsyncConnection,
    caller: Caller,
    resource_id: UUID,
    n: int,
    spec: dict[str, Any] | None = None,
    archive: bytes | None = None,
) -> Row:
    resource = await lock_for_edit(conn, caller, resource_id)
    version = await require_version(conn, resource_id, n)
    if version["status"] != "draft":
        raise ApiError(409, "version_immutable", "published versions cannot be edited")
    checked, problems = validated_subtype(
        {
            "type": resource["type"],
            "slug": resource["slug"],
            "spec": spec,
            "archive": archive,
        }
    )
    if problems:
        raise validation_failed(problems)
    if checked is not None and archive is not None:
        cur = await conn.execute(
            "SELECT content_sha256 FROM skills WHERE version_id = %s", (version["id"],)
        )
        old = [r[0] for r in await cur.fetchall()]
        await store_skill_file(conn, caller.tenant_id, checked, archive)
        await conn.execute(
            "UPDATE skills SET content_sha256 = %s WHERE version_id = %s",
            (checked.content_sha256, version["id"]),
        )
        await release_skill_files(conn, caller.tenant_id, old)
    else:
        assert spec is not None
        if resource["type"] == AGENT:
            await conn.execute(
                "DELETE FROM agents WHERE version_id = %s", (version["id"],)
            )
        else:
            await delete_generic_spec(conn, resource["type"], version["id"])
        await insert_spec(
            conn, resource["type"], caller.tenant_id, resource_id, version["id"], spec
        )
    return await _view(conn, resource, version, True)


async def delete_version(
    conn: AsyncConnection, caller: Caller, resource_id: UUID, n: int
) -> None:
    resource = await lock_for_edit(conn, caller, resource_id)
    version = await require_version(conn, resource_id, n)
    if version["id"] == resource["current_version_id"]:
        raise ApiError(
            409,
            "version_is_current",
            f"v{n} is the current version; repoint current first",
        )
    try:
        await delete_version_rows(conn, caller.tenant_id, version["id"])
    except VersionInUse as exc:
        raise ApiError(
            409,
            "version_in_use",
            f"v{n} is still referenced. De-reference it first.",
            version_to_remove=n,
            referenced_by=exc.referrers,
        ) from None
