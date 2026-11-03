from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb


async def record(
    conn: AsyncConnection,
    actor: str,
    action: str,
    tenant: UUID | None,
    target: str | None,
    detail: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        "INSERT INTO admin_audit_log (actor, action, tenant_id, target, detail) "
        "VALUES (%s, %s, %s, %s, %s)",
        (actor, action, tenant, target, None if detail is None else Jsonb(detail)),
    )
