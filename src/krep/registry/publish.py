from uuid import UUID

from psycopg import AsyncConnection

from krep.api.errors import ApiError
from krep.identity.resolve import Caller
from krep.registry.links import freeze_dependencies
from krep.registry.prune import prune_for_publish
from krep.registry.resources import SKILL, Row, lock_for_edit, validation_failed
from krep.registry.specs import VALIDATORS, content_hash, validate_spec
from krep.registry.versions import load_spec, require_version


def _hashable(resource_type: str, spec: Row) -> Row:
    if resource_type == SKILL:
        return {"content_sha256": spec["content_sha256"]}
    return spec


async def publish(
    conn: AsyncConnection,
    caller: Caller,
    resource_id: UUID,
    n: int,
    make_current: bool = True,
) -> Row:
    resource = await lock_for_edit(conn, caller, resource_id)
    if resource["status"] == "archived":
        raise ApiError(
            409, "resource_archived", "unarchive the resource before publishing"
        )
    version = await require_version(conn, resource_id, n)
    if version["status"] != "draft":
        raise ApiError(409, "version_immutable", f"v{n} is already published")
    resource_type: str = resource["type"]
    spec = await load_spec(conn, resource_type, version["id"])
    if resource_type in VALIDATORS:
        problems = validate_spec(resource_type, spec)
        if problems:
            raise validation_failed(problems)
    digest = content_hash(resource_type, _hashable(resource_type, spec))
    pruned = await prune_for_publish(conn, resource, n)
    cur = await conn.execute(
        "SELECT version FROM registry_versions WHERE registry_id = %s AND status = 'published' "
        "AND content_hash = %s AND version = (SELECT max(version) FROM registry_versions "
        "WHERE registry_id = %s AND status = 'published')",
        (resource_id, digest, resource_id),
    )
    unchanged = await cur.fetchone()
    await freeze_dependencies(conn, version["id"])
    cur = await conn.execute(
        "UPDATE registry_versions SET status = 'published', published_at = now(), content_hash = %s "
        "WHERE id = %s RETURNING published_at",
        (digest, version["id"]),
    )
    published_at = (await cur.fetchone() or (None,))[0]
    current = n
    if make_current or resource["current_version_id"] is None:
        await conn.execute(
            "UPDATE registry SET current_version_id = %s, status = 'published', "
            "updated_by = %s, updated_at = now() WHERE id = %s",
            (version["id"], caller.user_id, resource_id),
        )
    else:
        cur = await conn.execute(
            "SELECT version FROM registry_versions WHERE id = %s",
            (resource["current_version_id"],),
        )
        current = (await cur.fetchone() or (n,))[0]
    return {
        "id": resource_id,
        "status": "published",
        "current_version": current,
        "version": {
            "version": n,
            "status": "published",
            "content_hash": digest,
            "published_at": published_at,
        },
        "pruned_versions": pruned,
        "warnings": [f"no changes since v{unchanged[0]}"] if unchanged else [],
    }


async def set_current(
    conn: AsyncConnection, caller: Caller, resource_id: UUID, n: int
) -> Row:
    resource = await lock_for_edit(conn, caller, resource_id)
    version = await require_version(conn, resource_id, n)
    if version["status"] != "published":
        raise ApiError(409, "version_not_published", f"v{n} is not published")
    await conn.execute(
        "UPDATE registry SET current_version_id = %s, updated_by = %s, updated_at = now() "
        "WHERE id = %s",
        (version["id"], caller.user_id, resource_id),
    )
    return {
        "id": resource_id,
        "status": resource["status"],
        "current_version": n,
    }
