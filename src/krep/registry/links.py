from typing import Any
from uuid import UUID

from psycopg import AsyncConnection, errors
from psycopg.rows import dict_row

from krep.api.errors import ApiError
from krep.identity.resolve import Caller
from krep.registry.resources import (
    Row,
    advisory_lock,
    can_edit,
    can_read,
    fetch_row,
    not_found,
    validation_failed,
)
from krep.registry.specs import FieldError

LINK_COLUMNS = (
    "id, tenant_id, source_id, target_id, relation, pinned_version_id, auto_load, origin_id, "
    "status, created_by, created_at"
)


def _graph_lock_key(tenant_id: UUID) -> str:
    return f"links:{tenant_id}"


async def _readable(conn: AsyncConnection, caller: Caller, resource_id: UUID) -> Row:
    row = await fetch_row(conn, resource_id)
    if row is None or not await can_read(conn, caller, row):
        raise not_found()
    return row


async def _fetch_link(conn: AsyncConnection, link_id: UUID, lock: bool = False) -> Row:
    suffix = " FOR UPDATE" if lock else ""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {LINK_COLUMNS} FROM registry_links WHERE id = %s{suffix}",
            (link_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise ApiError(404, "not_found", "link not found")
    return row


async def _pinned_version_number(
    conn: AsyncConnection, version_id: UUID | None
) -> int | None:
    if version_id is None:
        return None
    cur = await conn.execute(
        "SELECT version FROM registry_versions WHERE id = %s", (version_id,)
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def _rule(
    conn: AsyncConnection, source_type: str, target_type: str, relation: str
) -> Row | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT auto_load_allowed, accept_by FROM link_rules "
            "WHERE source_type = %s AND target_type = %s AND relation = %s",
            (source_type, target_type, relation),
        )
        return await cur.fetchone()


async def _ensure_no_cycle(
    conn: AsyncConnection, source_id: UUID, target_id: UUID
) -> None:
    cur = await conn.execute(
        "WITH RECURSIVE reach(id) AS ("
        "  SELECT %(target)s::uuid "
        "  UNION "
        "  SELECT l.target_id FROM registry_links l JOIN reach r ON l.source_id = r.id "
        "  WHERE l.status = 'accepted'"
        ") SELECT EXISTS (SELECT 1 FROM reach WHERE id = %(source)s::uuid)",
        {"source": source_id, "target": target_id},
    )
    row = await cur.fetchone()
    if row and row[0]:
        raise ApiError(
            422,
            "link_cycle",
            "this link would create a dependency cycle through accepted links",
        )


def _view(link: Row, accept_by: str | None, pinned_version: int | None) -> Row:
    return {
        "id": link["id"],
        "source_id": link["source_id"],
        "target_id": link["target_id"],
        "relation": link["relation"],
        "pinned_version": pinned_version,
        "auto_load": link["auto_load"],
        "status": link["status"],
        "origin_id": link["origin_id"],
        "created_by": link["created_by"],
        "created_at": link["created_at"],
        **({"accept_by": accept_by} if accept_by else {}),
    }


async def create_link(
    conn: AsyncConnection,
    caller: Caller,
    resource_id: UUID,
    other_id: UUID,
    relation: str,
    direction: str,
    pinned_version: int | None,
    auto_load: bool,
) -> Row:
    if direction not in ("out", "in"):
        raise validation_failed([FieldError("direction", "must be out or in")])
    if other_id == resource_id:
        raise validation_failed(
            [FieldError("other_id", "a resource cannot link to itself")]
        )
    origin = await _readable(conn, caller, resource_id)
    other = await _readable(conn, caller, other_id)
    if not await can_edit(caller, origin):
        raise ApiError(
            403, "forbidden", "only the owner or an admin can link from this resource"
        )
    if "archived" in (origin["status"], other["status"]):
        raise ApiError(409, "resource_archived", "archived resources cannot be linked")
    source, target = (origin, other) if direction == "out" else (other, origin)
    rule = await _rule(conn, source["type"], target["type"], relation)
    if rule is None:
        raise ApiError(
            422,
            "link_not_allowed",
            f"{source['type']} -[{relation}]-> {target['type']} is not an allowed link",
        )
    if auto_load and not rule["auto_load_allowed"]:
        raise ApiError(
            422,
            "link_not_allowed",
            f"auto_load is not allowed for {source['type']} {relation} {target['type']}",
        )
    pinned_id: UUID | None = None
    if pinned_version is not None:
        cur = await conn.execute(
            "SELECT id FROM registry_versions WHERE registry_id = %s AND version = %s "
            "AND status = 'published'",
            (target["id"], pinned_version),
        )
        found = await cur.fetchone()
        if found is None:
            raise validation_failed(
                [
                    FieldError(
                        "pinned_version",
                        f"v{pinned_version} is not a published version of the target",
                    )
                ]
            )
        pinned_id = found[0]
    await advisory_lock(conn, _graph_lock_key(caller.tenant_id))
    await _ensure_no_cycle(conn, source["id"], target["id"])
    accept_side = source if rule["accept_by"] == "source" else target
    status = "accepted" if await can_edit(caller, accept_side) else "pending"
    try:
        async with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"INSERT INTO registry_links (tenant_id, source_id, target_id, relation, "
                f"pinned_version_id, auto_load, origin_id, status, created_by) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {LINK_COLUMNS}",
                (
                    caller.tenant_id,
                    source["id"],
                    target["id"],
                    relation,
                    pinned_id,
                    auto_load,
                    resource_id,
                    status,
                    caller.user_id,
                ),
            )
            inserted = await cur.fetchone()
    except errors.UniqueViolation:
        raise ApiError(
            409, "link_exists", "these resources are already linked with this relation"
        ) from None
    assert inserted is not None
    view = _view(inserted, rule["accept_by"], pinned_version)
    if status == "pending":
        view["waiting_on"] = f"owner of {accept_side['slug']}"
    return view


async def _decidable(conn: AsyncConnection, caller: Caller, link: Row) -> Row:
    source = await fetch_row(conn, link["source_id"])
    target = await fetch_row(conn, link["target_id"])
    if source is None or target is None:
        raise ApiError(404, "not_found", "link not found")
    rule = await _rule(conn, source["type"], target["type"], link["relation"])
    accept_side = source if rule is None or rule["accept_by"] == "source" else target
    if await can_edit(caller, accept_side):
        return {"source": source, "target": target}
    if await can_read(conn, caller, source) or await can_read(conn, caller, target):
        raise ApiError(
            403,
            "forbidden",
            "only the owner or an admin of the accepting side can decide",
        )
    raise ApiError(404, "not_found", "link not found")


async def _decide(
    conn: AsyncConnection, caller: Caller, link_id: UUID, accept: bool
) -> Row:
    await advisory_lock(conn, _graph_lock_key(caller.tenant_id))
    link = await _fetch_link(conn, link_id, lock=True)
    sides = await _decidable(conn, caller, link)
    if link["status"] != "pending":
        raise ApiError(409, "invalid_state", f"link is already {link['status']}")
    if accept:
        if "archived" in (sides["source"]["status"], sides["target"]["status"]):
            raise ApiError(
                409, "resource_archived", "archived resources cannot be linked"
            )
        await _ensure_no_cycle(conn, link["source_id"], link["target_id"])
    status = "accepted" if accept else "rejected"
    await conn.execute(
        "UPDATE registry_links SET status = %s WHERE id = %s", (status, link_id)
    )
    link["status"] = status
    return _view(
        link, None, await _pinned_version_number(conn, link["pinned_version_id"])
    )


async def accept_link(conn: AsyncConnection, caller: Caller, link_id: UUID) -> Row:
    return await _decide(conn, caller, link_id, True)


async def reject_link(conn: AsyncConnection, caller: Caller, link_id: UUID) -> Row:
    return await _decide(conn, caller, link_id, False)


async def delete_link(conn: AsyncConnection, caller: Caller, link_id: UUID) -> None:
    link = await _fetch_link(conn, link_id)
    source = await fetch_row(conn, link["source_id"])
    target = await fetch_row(conn, link["target_id"])
    sides = [row for row in (source, target) if row is not None]
    if any([await can_edit(caller, row) for row in sides]):
        await conn.execute("DELETE FROM registry_links WHERE id = %s", (link_id,))
        return
    if any([await can_read(conn, caller, row) for row in sides]):
        raise ApiError(
            403, "forbidden", "only an owner or admin of either side can delete a link"
        )
    raise ApiError(404, "not_found", "link not found")


async def list_links(
    conn: AsyncConnection,
    caller: Caller,
    resource_id: UUID,
    direction: str,
    status: str | None,
) -> list[Row]:
    resource = await _readable(conn, caller, resource_id)
    if direction not in ("out", "in", "both"):
        raise validation_failed([FieldError("direction", "must be out, in or both")])
    if status is not None and status not in ("pending", "accepted", "rejected"):
        raise validation_failed(
            [FieldError("status", "must be pending, accepted or rejected")]
        )
    editable = await can_edit(caller, resource)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {LINK_COLUMNS}, "
            "(SELECT version FROM registry_versions WHERE id = pinned_version_id) AS pinned_version "
            "FROM registry_links "
            "WHERE ((%(out)s AND source_id = %(id)s) OR (%(in)s AND target_id = %(id)s)) "
            "AND (%(status)s::text IS NULL OR status = %(status)s) "
            "AND (%(editable)s OR status = 'accepted') "
            "ORDER BY created_at, id",
            {
                "id": resource_id,
                "out": direction in ("out", "both"),
                "in": direction in ("in", "both"),
                "status": status,
                "editable": editable,
            },
        )
        rows = await cur.fetchall()
    items: list[Row] = []
    for row in rows:
        outgoing = row["source_id"] == resource_id
        other_id: UUID = row["target_id"] if outgoing else row["source_id"]
        other = await fetch_row(conn, other_id)
        if other is None or not await can_read(conn, caller, other):
            continue
        item = _view(row, None, row["pinned_version"])
        item["direction"] = "out" if outgoing else "in"
        item["other"] = {
            "id": other["id"],
            "type": other["type"],
            "slug": other["slug"],
            "name": other["name"],
        }
        items.append(item)
    return items


async def freeze_dependencies(conn: AsyncConnection, version_id: UUID) -> None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT l.relation, l.auto_load, t.slug, "
            "COALESCE(l.pinned_version_id, t.current_version_id) AS depends_on "
            "FROM registry_versions v "
            "JOIN registry_links l ON l.source_id = v.registry_id AND l.status = 'accepted' "
            "JOIN registry t ON t.id = l.target_id "
            "WHERE v.id = %s ORDER BY t.slug, l.relation",
            (version_id,),
        )
        deps: list[dict[str, Any]] = await cur.fetchall()
    unpublished = [d["slug"] for d in deps if d["depends_on"] is None]
    if unpublished:
        raise ApiError(
            422,
            "dependency_unpublished",
            f"linked resource has no published version: {', '.join(unpublished)}",
            dependencies=unpublished,
        )
    for dep in deps:
        await conn.execute(
            "INSERT INTO registry_version_deps (version_id, depends_on_version_id, tenant_id, "
            "relation, auto_load) SELECT %s, %s, tenant_id, %s, %s FROM registry_versions "
            "WHERE id = %s",
            (
                version_id,
                dep["depends_on"],
                dep["relation"],
                dep["auto_load"],
                version_id,
            ),
        )
