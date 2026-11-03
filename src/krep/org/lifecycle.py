from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from krep.api.errors import ApiError
from krep.config import get_settings
from krep.org import audit, service

MAX_GRACE_DAYS = 90


async def _lock(conn: AsyncConnection, org_id: UUID) -> tuple[str, bool]:
    cur = await conn.execute(
        "SELECT status, is_platform FROM organizations WHERE id = %s FOR UPDATE",
        (org_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise service.not_found("organization")
    return row[0], row[1]


def _require(status: str, allowed: tuple[str, ...]) -> None:
    if status not in allowed:
        raise ApiError(
            409,
            "invalid_state",
            f"organization is {status}; allowed from: {', '.join(allowed)}",
            current=status,
        )


def _unprotected(is_platform: bool) -> None:
    if is_platform:
        raise ApiError(
            409,
            "platform_organization_protected",
            "the platform organization cannot be suspended or deleted",
        )


async def suspend(conn: AsyncConnection, actor: str, org_id: UUID) -> dict[str, Any]:
    status, is_platform = await _lock(conn, org_id)
    _unprotected(is_platform)
    _require(status, ("active",))
    await conn.execute(
        "UPDATE organizations SET status = 'suspended' WHERE id = %s", (org_id,)
    )
    await audit.record(conn, actor, "org.suspend", org_id, None)
    return await service.get_organization(conn, org_id)


async def activate(conn: AsyncConnection, actor: str, org_id: UUID) -> dict[str, Any]:
    status, _ = await _lock(conn, org_id)
    _require(status, ("suspended",))
    await conn.execute(
        "UPDATE organizations SET status = 'active' WHERE id = %s", (org_id,)
    )
    await audit.record(conn, actor, "org.activate", org_id, None)
    return await service.get_organization(conn, org_id)


async def schedule_delete(
    conn: AsyncConnection, actor: str, org_id: UUID, grace_days: int | None
) -> dict[str, Any]:
    days = get_settings().org_delete_grace_days if grace_days is None else grace_days
    if not 1 <= days <= MAX_GRACE_DAYS:
        raise ApiError(
            422,
            "invalid_grace_period",
            f"grace_days must be between 1 and {MAX_GRACE_DAYS}",
        )
    status, is_platform = await _lock(conn, org_id)
    _unprotected(is_platform)
    _require(status, ("active", "suspended"))
    await conn.execute(
        "UPDATE organizations SET status = 'pending_delete', "
        "delete_after = now() + make_interval(days => %s) WHERE id = %s",
        (days, org_id),
    )
    await audit.record(
        conn, actor, "org.schedule_delete", org_id, None, {"grace_days": days}
    )
    return await service.get_organization(conn, org_id)


async def cancel_delete(
    conn: AsyncConnection, actor: str, org_id: UUID
) -> dict[str, Any]:
    status, _ = await _lock(conn, org_id)
    _require(status, ("pending_delete",))
    await conn.execute(
        "UPDATE organizations SET status = 'suspended', delete_after = NULL WHERE id = %s",
        (org_id,),
    )
    await audit.record(conn, actor, "org.cancel_delete", org_id, None)
    return await service.get_organization(conn, org_id)


async def set_legal_hold(
    conn: AsyncConnection, actor: str, org_id: UUID, legal_hold: bool
) -> dict[str, Any]:
    await _lock(conn, org_id)
    await conn.execute(
        "UPDATE organizations SET legal_hold = %s WHERE id = %s", (legal_hold, org_id)
    )
    await audit.record(
        conn, actor, "org.legal_hold", org_id, None, {"legal_hold": legal_hold}
    )
    return await service.get_organization(conn, org_id)
