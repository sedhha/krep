from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

GET_LIMIT = """
SELECT value FROM resource_limits
WHERE limit_key = %(key)s
  AND (resource_type IS NULL OR resource_type = %(type)s)
  AND ( (scope_type = 'product' AND scope_id = %(product)s)
     OR (scope_type = 'org'     AND scope_id = %(org)s)
     OR (scope_type = 'tenant'  AND scope_id = %(tenant)s)
     OR  scope_type = 'global')
ORDER BY CASE scope_type WHEN 'product' THEN 1 WHEN 'org' THEN 2 WHEN 'tenant' THEN 3 ELSE 4 END,
         (resource_type IS NULL)
LIMIT 1
"""


async def get_limit(
    conn: AsyncConnection,
    *,
    tenant_id: UUID,
    key: str,
    resource_type: str | None = None,
    product: str | None = None,
    org: str | None = None,
) -> int:
    cur = await conn.execute(
        GET_LIMIT,
        {
            "key": key,
            "type": resource_type,
            "product": product,
            "org": org,
            "tenant": str(tenant_id),
        },
    )
    row = await cur.fetchone()
    if row is None:
        raise LookupError(f"no limit configured for {key}")
    return int(row[0])


async def effective_limits(conn: AsyncConnection, tenant_id: UUID) -> dict[str, Any]:
    keys = [
        r[0]
        for r in await (
            await conn.execute("SELECT DISTINCT limit_key FROM resource_limits ORDER BY 1")
        ).fetchall()
    ]
    types = [
        r[0]
        for r in await (await conn.execute("SELECT type FROM registry_types ORDER BY 1")).fetchall()
    ]
    limits = {key: await get_limit(conn, tenant_id=tenant_id, key=key) for key in keys}
    by_type: dict[str, dict[str, int]] = {}
    for resource_type in types:
        for key in keys:
            value = await get_limit(conn, tenant_id=tenant_id, key=key, resource_type=resource_type)
            if value != limits[key]:
                by_type.setdefault(resource_type, {})[key] = value
    return {"limits": limits, "types": by_type}
