from uuid import UUID

from psycopg import AsyncConnection

from krep.identity.resolve import Caller
from krep.registry.resources import Row, update_resource


async def set_scope(
    conn: AsyncConnection,
    caller: Caller,
    resource_id: UUID,
    scope: str,
    product: str | None,
) -> Row:
    changes: Row = {"scope": scope}
    if product is not None:
        changes["product"] = product
    return await update_resource(conn, caller, resource_id, changes)
