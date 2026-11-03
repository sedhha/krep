from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection, errors

BLOCKERS = """
SELECT r.slug, f.organization, f.kind, f.referrers
FROM registry r CROSS JOIN LATERAL foreign_referrers(r.id) f
WHERE r.tenant_id = %s AND r.scope = 'global'
ORDER BY r.slug, f.organization, f.kind
"""


@dataclass(frozen=True)
class PurgeResult:
    organization_id: UUID
    slug: str
    purged: bool
    blockers: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


async def _blockers(conn: AsyncConnection, org_id: UUID) -> list[dict[str, Any]]:
    await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(org_id),))
    await conn.execute("SELECT set_config('app.platform_admin', 'on', true)")
    cur = await conn.execute(BLOCKERS, (org_id,))
    return [
        {"resource": slug, "organization": organization, "kind": kind, "referrers": n}
        for slug, organization, kind, n in await cur.fetchall()
    ]


async def purge_due(conn: AsyncConnection) -> list[PurgeResult]:
    async with conn.transaction():
        cur = await conn.execute(
            "SELECT id, slug FROM organizations WHERE status = 'pending_delete' "
            "AND delete_after <= now() AND NOT legal_hold AND NOT is_platform "
            "ORDER BY delete_after"
        )
        due: list[tuple[UUID, str]] = list(await cur.fetchall())
    results: list[PurgeResult] = []
    for org_id, slug in due:
        try:
            async with conn.transaction():
                blockers = await _blockers(conn, org_id)
                if not blockers:
                    await conn.execute("SELECT purge_organization(%s)", (org_id,))
        except errors.ForeignKeyViolation:
            async with conn.transaction():
                blockers = await _blockers(conn, org_id)
        results.append(PurgeResult(org_id, slug, not blockers, blockers))
    return results
