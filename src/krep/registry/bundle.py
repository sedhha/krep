from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from krep.identity.resolve import Caller
from krep.registry.resources import Row, can_edit, can_read, fetch_row, not_found
from krep.registry.versions import fetch_version, spec_view, version_not_found

MAX_DEPTH = 5

FROZEN_SEED = (
    "SELECT d.depends_on_version_id AS vid, d.relation FROM registry_version_deps d "
    "WHERE d.version_id = %(root)s AND d.auto_load"
)
LIVE_SEED = (
    "SELECT COALESCE(l.pinned_version_id, t.current_version_id) AS vid, l.relation "
    "FROM registry_links l JOIN registry t ON t.id = l.target_id "
    "WHERE l.source_id = %(registry)s AND l.status = 'accepted' AND l.auto_load "
    "AND COALESCE(l.pinned_version_id, t.current_version_id) IS NOT NULL"
)

BUNDLE_QUERY = (
    "WITH RECURSIVE bundle AS ("
    "  SELECT s.vid, s.relation, 1 AS depth FROM ({seed}) s "
    "  UNION "
    "  SELECT d.depends_on_version_id, d.relation, b.depth + 1 "
    "  FROM bundle b JOIN registry_version_deps d ON d.version_id = b.vid "
    "  WHERE d.auto_load AND b.depth < %(max_depth)s"
    "), nearest AS ("
    "  SELECT DISTINCT ON (vid) vid, relation, depth FROM bundle "
    "  WHERE vid <> %(root)s ORDER BY vid, depth, relation"
    ") "
    "SELECT r.id, r.type, r.slug, v.id AS version_id, v.version, n.relation "
    "FROM nearest n JOIN registry_versions v ON v.id = n.vid "
    "JOIN registry r ON r.id = v.registry_id "
    "ORDER BY n.depth, r.slug, v.version"
)


async def _root_version(
    conn: AsyncConnection, caller: Caller, resource: Row, version: int | None
) -> Row:
    if version is None:
        if resource["current_version_id"] is None:
            raise version_not_found()
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, version, status FROM registry_versions WHERE id = %s",
                (resource["current_version_id"],),
            )
            row = await cur.fetchone()
    else:
        row = await fetch_version(conn, resource["id"], version)
    if row is None or (
        row["status"] == "draft" and not await can_edit(conn, caller, resource)
    ):
        raise version_not_found()
    return row


async def resolve_bundle(
    conn: AsyncConnection, caller: Caller, resource_id: UUID, version: int | None
) -> Row:
    resource = await fetch_row(conn, resource_id)
    if resource is None or not await can_read(conn, caller, resource):
        raise not_found()
    root = await _root_version(conn, caller, resource, version)
    seed = FROZEN_SEED if root["status"] == "published" else LIVE_SEED
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            BUNDLE_QUERY.format(seed=seed),
            {
                "root": root["id"],
                "registry": resource_id,
                "max_depth": MAX_DEPTH,
            },
        )
        rows: list[Row] = await cur.fetchall()
    dependencies: list[dict[str, Any]] = [
        {
            "id": row["id"],
            "type": row["type"],
            "slug": row["slug"],
            "version": row["version"],
            "relation": row["relation"],
            "spec": await spec_view(
                conn, row["id"], row["type"], row["version_id"], row["version"]
            ),
        }
        for row in rows
    ]
    return {
        "root": {
            "id": resource_id,
            "type": resource["type"],
            "version": root["version"],
            "spec": await spec_view(
                conn, resource_id, resource["type"], root["id"], root["version"]
            ),
        },
        "dependencies": dependencies,
    }
