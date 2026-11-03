from typing import Any
from uuid import UUID

from psycopg import AsyncConnection, AsyncCursor, errors, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from krep.api.errors import ApiError
from krep.identity.resolve import Caller
from krep.registry.limits import get_limit
from krep.registry.policies import (
    list_policies,
    replace_policies,
    validate_policy_map,
)
from krep.registry.skill_archive import SkillArchive, validate_skill_archive
from krep.registry.specs import (
    SCOPES,
    FieldError,
    validate_resource_fields,
    validate_spec,
)
from krep.registry.subtypes import insert_generic_spec

COLUMNS = (
    "id, tenant_id, type, slug, name, description, tags, scope, product_id, status, "
    "current_version_id, next_version, meta, created_at, created_by, updated_at, updated_by"
)
PATCHABLE = ("name", "description", "tags", "meta")
SKILL = "skill"
AGENT = "agent"
DEFAULT_LIST_LIMIT = 50

Row = dict[str, Any]


def validation_failed(errors: list[FieldError]) -> ApiError:
    return ApiError(
        422,
        "validation_failed",
        "request validation failed",
        errors=[{"field": e.field, "message": e.message} for e in errors],
    )


def not_found() -> ApiError:
    return ApiError(404, "not_found", "resource not found")


async def fetch_row(
    conn: AsyncConnection, resource_id: UUID, lock: bool = False
) -> Row | None:
    suffix = " FOR UPDATE" if lock else ""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {COLUMNS} FROM registry WHERE id = %s{suffix}", (resource_id,)
        )
        return await cur.fetchone()


async def lock_resource(conn: AsyncConnection, resource_id: UUID) -> Row:
    row = await fetch_row(conn, resource_id, lock=True) or await fetch_row(
        conn, resource_id
    )
    if row is None:
        raise not_found()
    return row


async def platform_admin_on(conn: AsyncConnection) -> bool:
    cur = await conn.execute("SELECT current_setting('app.platform_admin', true)")
    row = await cur.fetchone()
    return bool(row and row[0] == "on")


async def _satisfies(
    conn: AsyncConnection, caller: Caller, resource_id: UUID, action: str
) -> bool:
    cur = await conn.execute(
        "SELECT p.kind = 'open' OR coalesce(jsonb_path_match(%s, p.compiled_path, %s, true), false) "
        "FROM registry_policies rp JOIN access_policies p ON p.id = rp.policy_id "
        "WHERE rp.registry_id = %s AND rp.action = %s",
        (
            Jsonb(caller.doc),
            Jsonb(
                {
                    "tenant_id": str(caller.tenant_id),
                    "product_id": str(caller.product_id) if caller.product_id else None,
                }
            ),
            resource_id,
            action,
        ),
    )
    return any([bool(r[0]) for r in await cur.fetchall()])


async def can_edit(conn: AsyncConnection, caller: Caller, row: Row) -> bool:
    if row["tenant_id"] != caller.tenant_id:
        return False
    if caller.can_admin:
        return True
    if not caller.can_write:
        return False
    return row["created_by"] == caller.user_id or await _satisfies(
        conn, caller, row["id"], "manage"
    )


def _in_reach(caller: Caller, row: Row) -> bool:
    if row["scope"] != "global" and row["tenant_id"] != caller.tenant_id:
        return False
    return row["scope"] != "product" or row["product_id"] == caller.product_id


async def can_read(conn: AsyncConnection, caller: Caller, row: Row) -> bool:
    if not _in_reach(caller, row):
        return False
    if row["status"] != "published":
        return await can_edit(conn, caller, row)
    if row["tenant_id"] == caller.tenant_id and (
        caller.can_admin or row["created_by"] == caller.user_id
    ):
        return True
    return await _satisfies(conn, caller, row["id"], "read")


async def _current_version(
    conn: AsyncConnection, version_id: UUID | None
) -> Row | None:
    if version_id is None:
        return None
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT version, status, content_hash, published_at FROM registry_versions WHERE id = %s",
            (version_id,),
        )
        return await cur.fetchone()


async def _product_slug(conn: AsyncConnection, product_id: UUID | None) -> str | None:
    if product_id is None:
        return None
    cur = await conn.execute("SELECT slug FROM products WHERE id = %s", (product_id,))
    row = await cur.fetchone()
    return row[0] if row else None


async def _view(conn: AsyncConnection, caller: Caller, row: Row) -> Row:
    view: Row = {
        key: row[key]
        for key in (
            "id",
            "type",
            "slug",
            "name",
            "description",
            "tags",
            "scope",
            "status",
            "meta",
            "created_at",
            "created_by",
            "updated_at",
            "updated_by",
        )
    }
    view["product"] = await _product_slug(conn, row["product_id"])
    view["current_version"] = await _current_version(conn, row["current_version_id"])
    if await can_edit(conn, caller, row):
        view["policies"] = await list_policies(conn, row["id"])
    return view


async def get_visible(
    conn: AsyncConnection, caller: Caller, resource_id: UUID
) -> Row | None:
    row = await fetch_row(conn, resource_id)
    if row is None or not await can_read(conn, caller, row):
        return None
    return await _view(conn, caller, row)


async def lock_for_edit(
    conn: AsyncConnection, caller: Caller, resource_id: UUID
) -> Row:
    row = await lock_resource(conn, resource_id)
    if await can_edit(conn, caller, row):
        return row
    if await can_read(conn, caller, row):
        raise ApiError(
            403, "forbidden", "only the owner or an admin can modify this resource"
        )
    raise not_found()


async def advisory_lock(conn: AsyncConnection, key: str) -> None:
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))


async def enforce_draft_cap(
    conn: AsyncConnection, tenant_id: UUID, resource_type: str
) -> None:
    await advisory_lock(conn, f"{tenant_id}:{resource_type}")
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
            409,
            "draft_limit_reached",
            "draft limit reached",
            limit=limit,
            current=current,
        )


async def store_skill_file(
    conn: AsyncConnection, tenant_id: UUID, archive: SkillArchive, data: bytes
) -> None:
    await advisory_lock(conn, f"{tenant_id}:{archive.content_sha256}")
    await conn.execute(
        "INSERT INTO skill_files (tenant_id, content_sha256, size_bytes, content) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (tenant_id, archive.content_sha256, archive.size_bytes, data),
    )


async def release_skill_files(
    conn: AsyncConnection, tenant_id: UUID, hashes: list[str]
) -> None:
    released = sorted(set(hashes))
    for content_sha256 in released:
        await advisory_lock(conn, f"{tenant_id}:{content_sha256}")
    if released:
        await conn.execute(
            "DELETE FROM skill_files f WHERE f.tenant_id = %s AND f.content_sha256 = ANY(%s) "
            "AND NOT EXISTS (SELECT 1 FROM skills s WHERE s.tenant_id = f.tenant_id "
            "AND s.content_sha256 = f.content_sha256)",
            (tenant_id, released),
        )


async def insert_agent_spec(
    conn: AsyncConnection,
    tenant_id: UUID,
    registry_id: UUID,
    version_id: UUID,
    spec: Row,
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


async def insert_spec(
    conn: AsyncConnection,
    resource_type: str,
    tenant_id: UUID,
    registry_id: UUID,
    version_id: UUID,
    spec: Row,
) -> None:
    if resource_type == AGENT:
        await insert_agent_spec(conn, tenant_id, registry_id, version_id, spec)
    else:
        await insert_generic_spec(
            conn, resource_type, tenant_id, registry_id, version_id, spec
        )


def validated_subtype(body: Row) -> tuple[SkillArchive | None, list[FieldError]]:
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


async def _resolve_scope(conn: AsyncConnection, body: Row) -> tuple[str, UUID | None]:
    scope: str = body.get("scope", "org")
    if scope not in SCOPES:
        raise validation_failed(
            [FieldError("scope", f"must be one of {', '.join(SCOPES)}")]
        )
    if scope == "global" and not await platform_admin_on(conn):
        raise scope_not_allowed()
    slug = body.get("product")
    if scope != "product":
        if slug is not None:
            raise validation_failed(
                [FieldError("product", "only product-scoped resources take a product")]
            )
        return scope, None
    if slug is None:
        raise validation_failed([FieldError("product", "required for product scope")])
    return scope, await _product_id(conn, slug)


async def _product_id(conn: AsyncConnection, slug: str) -> UUID:
    cur = await conn.execute(
        "SELECT id FROM products WHERE slug = %s AND status = 'active'", (slug,)
    )
    row = await cur.fetchone()
    if row is None:
        raise validation_failed([FieldError("product", "product does not exist")])
    return row[0]


def scope_not_allowed() -> ApiError:
    return ApiError(403, "scope_not_allowed", "global scope requires a platform admin")


async def create_resource(conn: AsyncConnection, caller: Caller, body: Row) -> Row:
    resource_type: str = body["type"]
    if resource_type not in await _known_types(conn):
        raise validation_failed([FieldError("type", "unknown resource type")])
    archive, errors_ = validated_subtype(body)
    description: str | None = body.get("description")
    if description is None:
        description = archive.description if archive else ""
    errors_ += validate_resource_fields(
        body["name"],
        body["slug"],
        description,
        body.get("tags", []),
        body.get("meta", {}),
    )
    policies: dict[str, list[UUID]] = body.get("policies") or {}
    errors_ += validate_policy_map(policies)
    if errors_:
        raise validation_failed(errors_)
    async with conn.transaction():
        scope, product_id = await _resolve_scope(conn, body)
        await enforce_draft_cap(conn, caller.tenant_id, resource_type)
        try:
            registry_id = await _insert_resource(
                conn, caller, body, description, archive, scope, product_id
            )
        except errors.UniqueViolation:
            raise ApiError(
                409, "slug_taken", "slug already in use for this type"
            ) from None
        for action, ids in policies.items():
            await replace_policies(conn, caller.tenant_id, registry_id, action, ids)
    return {
        "id": registry_id,
        "type": resource_type,
        "slug": body["slug"],
        "status": "draft",
        "scope": scope,
        "product": body.get("product"),
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
    scope: str,
    product_id: UUID | None,
) -> UUID:
    cur = await conn.execute(
        "INSERT INTO registry (tenant_id, type, slug, name, description, tags, scope, "
        "product_id, next_version, meta, created_by, updated_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 2, %s, %s, %s) RETURNING id",
        (
            caller.tenant_id,
            body["type"],
            body["slug"],
            body["name"],
            description,
            body.get("tags", []),
            scope,
            product_id,
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
        await insert_spec(
            conn, body["type"], caller.tenant_id, registry_id, version_id, body["spec"]
        )
    return registry_id


async def list_resources(
    conn: AsyncConnection,
    caller: Caller,
    *,
    type: str | None,
    status: str | None,
    scope: str | None = None,
    product: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> list[Row]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT r.id, r.type, r.slug, r.name, r.description, r.tags, r.scope, "
            "pr.slug AS product, r.status, r.created_by, r.updated_at, "
            "v.version AS current_version "
            "FROM registry r LEFT JOIN registry_versions v ON v.id = r.current_version_id "
            "LEFT JOIN products pr ON pr.id = r.product_id "
            "WHERE r.tenant_id = %(tenant)s AND (%(admin)s OR r.created_by = %(user)s) "
            "AND (%(scope)s::text IS NULL OR r.scope = %(scope)s) "
            "AND (%(product)s::text IS NULL OR pr.slug = %(product)s) "
            "AND (%(type)s::text IS NULL OR r.type = %(type)s) "
            "AND (%(status)s::text IS NULL OR r.status = %(status)s) "
            "ORDER BY r.created_at DESC, r.id LIMIT %(limit)s OFFSET %(offset)s",
            {
                "tenant": caller.tenant_id,
                "admin": caller.can_admin,
                "user": caller.user_id,
                "scope": scope,
                "product": product,
                "type": type,
                "status": status,
                "limit": limit,
                "offset": offset,
            },
        )
        return await cur.fetchall()


async def foreign_referrers(conn: AsyncConnection, resource_id: UUID) -> list[Row]:
    return []


async def _scope_change(
    conn: AsyncConnection, row: Row, changes: Row
) -> tuple[str, UUID | None] | None:
    if "scope" not in changes and "product" not in changes:
        return None
    scope: str = changes.get("scope", row["scope"])
    if scope not in SCOPES:
        raise validation_failed(
            [FieldError("scope", f"must be one of {', '.join(SCOPES)}")]
        )
    slug = changes.get("product")
    if scope == "product":
        if slug is None and "scope" in changes and row["scope"] != "product":
            raise validation_failed(
                [FieldError("product", "required for product scope")]
            )
        product_id = await _product_id(conn, slug) if slug else row["product_id"]
    else:
        if slug is not None:
            raise validation_failed(
                [FieldError("product", "only product-scoped resources take a product")]
            )
        product_id = None
    if scope == row["scope"] and product_id == row["product_id"]:
        return None
    return scope, product_id


async def _authorise_scope_change(
    conn: AsyncConnection, caller: Caller, row: Row, scope: str
) -> None:
    platform = await platform_admin_on(conn)
    if scope == "global":
        if not platform:
            raise scope_not_allowed()
        if row["status"] != "published":
            raise ApiError(
                409, "invalid_state", "only published resources can become global"
            )
    elif row["scope"] == "global":
        if not (platform or caller.can_admin):
            raise ApiError(
                403, "forbidden", "only an org admin can demote a global resource"
            )
        if referrers := await foreign_referrers(conn, row["id"]):
            raise ApiError(
                409,
                "resource_in_use",
                "resource is used by other organisations",
                referrers=referrers,
            )


async def update_resource(
    conn: AsyncConnection, caller: Caller, resource_id: UUID, changes: Row
) -> Row:
    row = await lock_for_edit(conn, caller, resource_id)
    merged = {**row, **{k: v for k, v in changes.items() if k in PATCHABLE}}
    problems = validate_resource_fields(
        merged["name"],
        merged["slug"],
        merged["description"],
        merged["tags"],
        merged["meta"],
    )
    policies: dict[str, list[UUID]] = changes.get("policies") or {}
    if "policies" in changes:
        problems += validate_policy_map(policies)
    if problems:
        raise validation_failed(problems)
    assignments = [
        sql.SQL("{} = {}").format(sql.Identifier(key), sql.Placeholder(key))
        for key in PATCHABLE
        if key in changes
    ]
    params: Row = {
        k: Jsonb(v) if k == "meta" else v for k, v in changes.items() if k in PATCHABLE
    }
    async with conn.transaction():
        if moved := await _scope_change(conn, row, changes):
            await _authorise_scope_change(conn, caller, row, moved[0])
            assignments += [sql.SQL("scope = %(scope)s, product_id = %(product_id)s")]
            params |= {"scope": moved[0], "product_id": moved[1]}
        try:
            await conn.execute(
                sql.SQL("UPDATE registry SET {} WHERE id = %(id)s").format(
                    sql.SQL(", ").join(
                        assignments
                        + [sql.SQL("updated_by = %(by)s, updated_at = now()")]
                    )
                ),
                {**params, "by": caller.user_id, "id": resource_id},
            )
        except errors.UniqueViolation:
            raise ApiError(
                409, "slug_taken", "slug already in use for this type"
            ) from None
        for action, ids in policies.items():
            await replace_policies(conn, row["tenant_id"], resource_id, action, ids)
    updated = await lock_resource(conn, resource_id)
    return await _view(conn, caller, updated)


async def set_archived(
    conn: AsyncConnection, caller: Caller, resource_id: UUID, archived: bool
) -> Row:
    row = await lock_for_edit(conn, caller, resource_id)
    required, target = (
        ("published", "archived") if archived else ("archived", "published")
    )
    if row["status"] != required:
        raise ApiError(
            409,
            "invalid_state",
            f"only {required} resources can be {'archived' if archived else 'unarchived'}",
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


async def delete_resource(
    conn: AsyncConnection, caller: Caller, resource_id: UUID
) -> None:
    await lock_for_edit(conn, caller, resource_id)
    referrers = await _referrers(conn, resource_id)
    if referrers:
        raise ApiError(
            409,
            "resource_in_use",
            "resource is referenced by other resources",
            referrers=referrers,
        )
    cur = await conn.execute(
        "SELECT DISTINCT content_sha256 FROM skills WHERE registry_id = %s",
        (resource_id,),
    )
    hashes = [r[0] for r in await cur.fetchall()]
    await conn.execute("DELETE FROM registry WHERE id = %s", (resource_id,))
    await release_skill_files(conn, caller.tenant_id, hashes)
