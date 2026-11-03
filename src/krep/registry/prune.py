from typing import Any
from uuid import UUID

from psycopg import AsyncConnection, errors
from psycopg.rows import dict_row

from krep.api.errors import ApiError
from krep.registry.limits import get_limit
from krep.registry.resources import Row, foreign_version_referrers, release_skill_files

Referrer = dict[str, Any]


class VersionInUse(Exception):
    def __init__(self, referrers: list[Referrer]) -> None:
        super().__init__("version is referenced")
        self.referrers = referrers


async def version_in_use(conn: AsyncConnection, version_id: UUID) -> list[Referrer]:
    referrers: list[Referrer] = []
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT l.id AS link_id, r.id AS resource_id, r.slug FROM registry_links l "
            "JOIN registry r ON r.id = l.source_id WHERE l.pinned_version_id = %s "
            "ORDER BY r.slug, l.id",
            (version_id,),
        )
        referrers.extend(
            {
                "kind": "link_pin",
                "resource": row["slug"],
                "resource_id": str(row["resource_id"]),
                "link_id": str(row["link_id"]),
            }
            for row in await cur.fetchall()
        )
        await cur.execute(
            "SELECT r.id AS resource_id, r.slug, sv.version FROM registry_version_deps d "
            "JOIN registry_versions sv ON sv.id = d.version_id "
            "JOIN registry r ON r.id = sv.registry_id WHERE d.depends_on_version_id = %s "
            "ORDER BY r.slug, sv.version",
            (version_id,),
        )
        referrers.extend(
            {
                "kind": "version_dep",
                "resource": row["slug"],
                "resource_id": str(row["resource_id"]),
                "version": row["version"],
            }
            for row in await cur.fetchall()
        )
    return referrers + await foreign_version_referrers(conn, version_id)


async def delete_version_rows(
    conn: AsyncConnection, tenant_id: UUID, version_id: UUID
) -> None:
    cur = await conn.execute(
        "SELECT content_sha256 FROM skills WHERE version_id = %s", (version_id,)
    )
    hashes = [r[0] for r in await cur.fetchall()]
    try:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM registry_versions WHERE id = %s", (version_id,)
            )
    except errors.ForeignKeyViolation:
        raise VersionInUse(await version_in_use(conn, version_id)) from None
    await release_skill_files(conn, tenant_id, hashes)


async def prune_for_publish(
    conn: AsyncConnection, resource: Row, incoming: int
) -> list[int]:
    limit = await get_limit(
        conn,
        tenant_id=resource["tenant_id"],
        key="max_published_versions",
        resource_type=resource["type"],
    )
    pruned: list[int] = []
    while True:
        cur = await conn.execute(
            "SELECT count(*) FROM registry_versions WHERE registry_id = %s AND status = 'published'",
            (resource["id"],),
        )
        count = (await cur.fetchone() or (0,))[0]
        if count < limit:
            return pruned
        cur = await conn.execute(
            "SELECT id, version FROM registry_versions WHERE registry_id = %s "
            "AND status = 'published' AND id IS DISTINCT FROM %s ORDER BY version LIMIT 1",
            (resource["id"], resource["current_version_id"]),
        )
        oldest = await cur.fetchone()
        if oldest is None:
            raise ApiError(
                409,
                "version_limit_reached",
                f"publishing v{incoming} would exceed the limit of {limit} published versions "
                "and no version can be removed",
                limit=limit,
            )
        version_id, version = oldest
        try:
            await delete_version_rows(conn, resource["tenant_id"], version_id)
        except VersionInUse as exc:
            raise ApiError(
                409,
                "version_in_use",
                f"Publishing v{incoming} requires archiving the oldest version (v{version}), "
                "but it is still referenced. De-reference it first.",
                version_to_remove=version,
                referenced_by=exc.referrers,
            ) from None
        pruned.append(version)
