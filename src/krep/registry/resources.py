from typing import Any
from uuid import UUID

from psycopg import AsyncConnection, AsyncCursor, errors, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from krep.api.errors import ApiError
from krep.identity.resolve import Caller
from krep.policy.evaluate import evaluate
from krep.registry.limits import get_limit
from krep.registry.skill_archive import SkillArchive, validate_skill_archive
from krep.registry.specs import FieldError, validate_resource_fields, validate_spec

COLUMNS = (
    "id, tenant_id, type, slug, name, description, tags, visibility, policy_id, status, "
    "current_version_id, next_version, meta, created_at, created_by, updated_at, updated_by"
)
PATCHABLE = ("name", "description", "tags", "visibility", "policy_id", "meta")
SKILL = "skill"
DEFAULT_LIST_LIMIT = 50

Row = dict[str, Any]


def _validation_failed(errors: list[FieldError]) -> ApiError:
    return ApiError(
        422,
        "validation_failed",
        "request validation failed",
        errors=[{"field": e.field, "message": e.message} for e in errors],
    )


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "resource not found")


async def _fetch_row(conn: AsyncConnection, resource_id: UUID, lock: bool = False) -> Row | None:
    suffix = " FOR UPDATE" if lock else ""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT {COLUMNS} FROM registry WHERE id = %s{suffix}", (resource_id,))
        return await cur.fetchone()


async def lock_resource(conn: AsyncConnection, resource_id: UUID) -> Row:
    row = await _fetch_row(conn, resource_id, lock=True)
    if row is None:
        raise _not_found()
    return row


async def can_edit(caller: Caller, row: Row) -> bool:
    return caller.can_admin or (caller.can_write and row["created_by"] == caller.user_id)


async def _policy_satisfied(conn: AsyncConnection, caller: Caller, policy_id: UUID | None) -> bool:
    if policy_id is None:
        return False
    cur = await conn.execute(
        "SELECT compiled_path::text FROM access_policies WHERE id = %s", (policy_id,)
    )
    row = await cur.fetchone()
    return row is not None and await evaluate(conn, row[0], caller.doc, caller.tenant_id)


async def _discoverable(conn: AsyncConnection, caller: Caller, row: Row) -> bool:
    if row["visibility"] == "private":
        return row["created_by"] == caller.user_id
    if row["visibility"] == "tenant":
        return True
    return await _policy_satisfied(conn, caller, row["policy_id"])


async def _can_read(conn: AsyncConnection, caller: Caller, row: Row) -> bool:
    if row["status"] != "published":
        return await can_edit(caller, row)
    return await _discoverable(conn, caller, row)


async def _current_version(conn: AsyncConnection, version_id: UUID | None) -> Row | None:
    if version_id is None:
        return None
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT version, status, content_hash, published_at FROM registry_versions WHERE id = %s",
            (version_id,),
        )
        return await cur.fetchone()


async def _view(conn: AsyncConnection, caller: Caller, row: Row) -> Row:
    editable = await can_edit(caller, row)
    view: Row = {
        key: row[key]
        for key in (
            "id",
            "type",
            "slug",
            "name",
            "description",
            "tags",
            "visibility",
            "status",
            "meta",
            "created_at",
            "created_by",
            "updated_at",
            "updated_by",
        )
    }
    view["current_version"] = await _current_version(conn, row["current_version_id"])
    if editable:
        view["policy_id"] = row["policy_id"]
    return view


async def get_visible(conn: AsyncConnection, caller: Caller, resource_id: UUID) -> Row | None:
    row = await _fetch_row(conn, resource_id)
    if row is None or not await _can_read(conn, caller, row):
        return None
    return await _view(conn, caller, row)


async def _lock_for_edit(conn: AsyncConnection, caller: Caller, resource_id: UUID) -> Row:
    row = await lock_resource(conn, resource_id)
    if await can_edit(caller, row):
        return row
    if await _can_read(conn, caller, row):
        raise ApiError(403, "forbidden", "only the owner or an admin can modify this resource")
    raise _not_found()


async def _advisory_lock(conn: AsyncConnection, key: str) -> None:
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))


async def enforce_draft_cap(conn: AsyncConnection, tenant_id: UUID, resource_type: str) -> None:
    await _advisory_lock(conn, f"{tenant_id}:{resource_type}")
    cur = await conn.execute(
        "SELECT count(*) FROM registry_versions v JOIN registry r ON r.id = v.registry_id "
        "WHERE v.tenant_id = %s AND r.type = %s AND v.status = 'draft'",
        (tenant_id, resource_type),
    )
    current = (await cur.fetchone() or (0,))[0]
    limit = await get_limit(
        conn, tenant_id=tenant_id, key="max_drafts", resource_type=resource_type
    )
    if current >= limit:
        raise ApiError(
            409, "draft_limit_reached", "draft limit reached", limit=limit, current=current
        )


async def store_skill_file(
    conn: AsyncConnection, tenant_id: UUID, archive: SkillArchive, data: bytes
) -> None:
    await _advisory_lock(conn, f"{tenant_id}:{archive.content_sha256}")
    await conn.execute(
        "INSERT INTO skill_files (tenant_id, content_sha256, size_bytes, content) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (tenant_id, archive.content_sha256, archive.size_bytes, data),
    )


async def release_skill_files(conn: AsyncConnection, tenant_id: UUID, hashes: list[str]) -> None:
    released = sorted(set(hashes))
    for content_sha256 in released:
        await _advisory_lock(conn, f"{tenant_id}:{content_sha256}")
    if released:
        await conn.execute(
            "DELETE FROM skill_files f WHERE f.tenant_id = %s AND f.content_sha256 = ANY(%s) "
            "AND NOT EXISTS (SELECT 1 FROM skills s WHERE s.tenant_id = f.tenant_id "
            "AND s.content_sha256 = f.content_sha256)",
            (tenant_id, released),
        )


async def insert_agent_spec(
    conn: AsyncConnection, tenant_id: UUID, registry_id: UUID, version_id: UUID, spec: Row
) -> None:
    await conn.execute(
        "INSERT INTO agents (version_id, registry_id, tenant_id, model, model_config, "
        "system_prompt, input_schema, output_schema, hitl_rules, runtime_config, tool_refs) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            version_id,
            registry_id,
            tenant_id,
            spec["model"],
            Jsonb(spec.get("model_config", {})),
            spec["system_prompt"],
            Jsonb(spec.get("input_schema", {})),
            Jsonb(spec.get("output_schema", {})),
            Jsonb(spec.get("hitl_rules", [])),
            Jsonb(spec.get("runtime_config", {})),
            Jsonb(spec.get("tool_refs", [])),
        ),
    )


def _validated_subtype(body: Row) -> tuple[SkillArchive | None, list[FieldError]]:
    resource_type: str = body["type"]
    spec: Row | None = body.get("spec")
    data: bytes | None = body.get("archive")
    if resource_type == SKILL:
        if spec is not None:
            return None, [FieldError("spec", "skills take an archive")]
        if data is None:
            return None, [FieldError("archive", "required")]
        return validate_skill_archive(data, body["slug"])
    if data is not None:
        return None, [FieldError("archive", "only skills take an archive")]
    if spec is None:
        return None, [FieldError("spec", "required")]
    return None, validate_spec(resource_type, spec)


async def _known_types(conn: AsyncConnection) -> set[str]:
    cur = await conn.execute("SELECT type FROM registry_types")
    return {r[0] for r in await cur.fetchall()}


async def create_resource(conn: AsyncConnection, caller: Caller, body: Row) -> Row:
    resource_type: str = body["type"]
    if resource_type not in await _known_types(conn):
        raise _validation_failed([FieldError("type", "unknown resource type")])
    archive, errors_ = _validated_subtype(body)
    description: str | None = body.get("description")
    if description is None:
        description = archive.description if archive else ""
    errors_ += validate_resource_fields(
        body["name"],
        body["slug"],
        description,
        body.get("tags", []),
        body.get("visibility", "private"),
        body.get("policy_id"),
        body.get("meta", {}),
    )
    if errors_:
        raise _validation_failed(errors_)
    async with conn.transaction():
        await enforce_draft_cap(conn, caller.tenant_id, resource_type)
        try:
            registry_id = await _insert_resource(
                conn, caller, body, description, archive
            )
        except errors.UniqueViolation:
            raise ApiError(409, "slug_taken", "slug already in use for this type") from None
        except errors.ForeignKeyViolation:
            raise _validation_failed(
                [FieldError("policy_id", "policy does not exist")]
            ) from None
    return {
        "id": registry_id,
        "type": resource_type,
        "slug": body["slug"],
        "status": "draft",
        "visibility": body.get("visibility", "private"),
        "current_version": None,
        "version": {"version": 1, "status": "draft"},
        **({"warnings": archive.warnings} if archive else {}),
    }


async def _returned_id(cur: AsyncCursor[Any]) -> UUID:
    row = await cur.fetchone()
    assert row is not None
    return row[0]


async def _insert_resource(
    conn: AsyncConnection,
    caller: Caller,
    body: Row,
    description: str,
    archive: SkillArchive | None,
) -> UUID:
    cur = await conn.execute(
        "INSERT INTO registry (tenant_id, type, slug, name, description, tags, visibility, "
        "policy_id, next_version, meta, created_by, updated_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 2, %s, %s, %s) RETURNING id",
        (
            caller.tenant_id,
            body["type"],
            body["slug"],
            body["name"],
            description,
            body.get("tags", []),
            body.get("visibility", "private"),
            body.get("policy_id"),
            Jsonb(body.get("meta", {})),
            caller.user_id,
            caller.user_id,
        ),
    )
    registry_id = await _returned_id(cur)
    cur = await conn.execute(
        "INSERT INTO registry_versions (registry_id, tenant_id, version, created_by) "
        "VALUES (%s, %s, 1, %s) RETURNING id",
        (registry_id, caller.tenant_id, caller.user_id),
    )
    version_id = await _returned_id(cur)
    if archive:
        await store_skill_file(conn, caller.tenant_id, archive, body["archive"])
        await conn.execute(
            "INSERT INTO skills (version_id, registry_id, tenant_id, content_sha256) "
            "VALUES (%s, %s, %s, %s)",
            (version_id, registry_id, caller.tenant_id, archive.content_sha256),
        )
    else:
        await insert_agent_spec(conn, caller.tenant_id, registry_id, version_id, body["spec"])
    return registry_id


async def list_resources(
    conn: AsyncConnection,
    caller: Caller,
    *,
    type: str | None,
    status: str | None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> list[Row]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT r.id, r.type, r.slug, r.name, r.description, r.tags, r.visibility, "
            "r.status, r.created_by, r.updated_at, v.version AS current_version "
            "FROM registry r LEFT JOIN registry_versions v ON v.id = r.current_version_id "
            "WHERE (%(admin)s OR r.created_by = %(user)s) "
            "AND (%(type)s::text IS NULL OR r.type = %(type)s) "
            "AND (%(status)s::text IS NULL OR r.status = %(status)s) "
            "ORDER BY r.created_at DESC, r.id LIMIT %(limit)s OFFSET %(offset)s",
            {
                "admin": caller.can_admin,
                "user": caller.user_id,
                "type": type,
                "status": status,
                "limit": limit,
                "offset": offset,
            },
        )
        return await cur.fetchall()


async def update_resource(
    conn: AsyncConnection, caller: Caller, resource_id: UUID, changes: Row
) -> Row:
    row = await _lock_for_edit(conn, caller, resource_id)
    merged = {**row, **{k: v for k, v in changes.items() if k in PATCHABLE}}
    problems = validate_resource_fields(
        merged["name"],
        merged["slug"],
        merged["description"],
        merged["tags"],
        merged["visibility"],
        merged["policy_id"],
        merged["meta"],
    )
    if problems:
        raise _validation_failed(problems)
    assignments = sql.SQL(", ").join(
        [
            sql.SQL("{} = {}").format(sql.Identifier(key), sql.Placeholder(key))
            for key in PATCHABLE
            if key in changes
        ]
        + [sql.SQL("updated_by = %(by)s, updated_at = now()")]
    )
    params: Row = {k: Jsonb(v) if k == "meta" else v for k, v in changes.items() if k in PATCHABLE}
    try:
        async with conn.transaction():
            await conn.execute(
                sql.SQL("UPDATE registry SET {} WHERE id = %(id)s").format(assignments),
                {**params, "by": caller.user_id, "id": resource_id},
            )
    except errors.ForeignKeyViolation:
        raise _validation_failed([FieldError("policy_id", "policy does not exist")]) from None
    updated = await lock_resource(conn, resource_id)
    return await _view(conn, caller, updated)


async def set_archived(
    conn: AsyncConnection, caller: Caller, resource_id: UUID, archived: bool
) -> Row:
    row = await _lock_for_edit(conn, caller, resource_id)
    required, target = ("published", "archived") if archived else ("archived", "published")
    if row["status"] != required:
        raise ApiError(
            409, "invalid_state", f"only {required} resources can be {'archived' if archived else 'unarchived'}"
        )
    await conn.execute(
        "UPDATE registry SET status = %s, updated_by = %s, updated_at = now() WHERE id = %s",
        (target, caller.user_id, resource_id),
    )
    return await _view(conn, caller, await lock_resource(conn, resource_id))


async def _referrers(conn: AsyncConnection, resource_id: UUID) -> list[Row]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT r.id, r.type, r.slug, l.relation FROM registry_links l "
            "JOIN registry r ON r.id = l.source_id WHERE l.target_id = %(id)s "
            "UNION "
            "SELECT r.id, r.type, r.slug, d.relation FROM registry_version_deps d "
            "JOIN registry_versions dv ON dv.id = d.depends_on_version_id "
            "JOIN registry_versions sv ON sv.id = d.version_id "
            "JOIN registry r ON r.id = sv.registry_id "
            "WHERE dv.registry_id = %(id)s AND sv.registry_id <> %(id)s "
            "UNION "
            "SELECT r.id, r.type, r.slug, l.relation FROM registry_links l "
            "JOIN registry_versions pv ON pv.id = l.pinned_version_id "
            "JOIN registry r ON r.id = l.source_id "
            "WHERE pv.registry_id = %(id)s AND l.target_id <> %(id)s",
            {"id": resource_id},
        )
        return await cur.fetchall()


async def delete_resource(conn: AsyncConnection, caller: Caller, resource_id: UUID) -> None:
    await _lock_for_edit(conn, caller, resource_id)
    referrers = await _referrers(conn, resource_id)
    if referrers:
        raise ApiError(
            409, "resource_in_use", "resource is referenced by other resources", referrers=referrers
        )
    cur = await conn.execute(
        "SELECT DISTINCT content_sha256 FROM skills WHERE registry_id = %s", (resource_id,)
    )
    hashes = [r[0] for r in await cur.fetchall()]
    await conn.execute("DELETE FROM registry WHERE id = %s", (resource_id,))
    await release_skill_files(conn, caller.tenant_id, hashes)
