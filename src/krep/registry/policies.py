from typing import Any, cast
from uuid import UUID

from psycopg import AsyncConnection

from krep.api.errors import ApiError
from krep.identity.resolve import Caller
from krep.registry.limits import get_limit
from krep.registry.specs import FieldError

ACTIONS = ("read", "manage")
LIMIT_KEY = "max_policies_per_resource_action"


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        422,
        "validation_failed",
        "request validation failed",
        errors=[{"field": field, "message": message}],
    )


def validate_policy_map(policies: Any) -> list[FieldError]:
    if not isinstance(policies, dict):
        return [FieldError("policies", "must be an object")]
    errors: list[FieldError] = []
    for action, ids in cast("dict[Any, Any]", policies).items():
        if action not in ACTIONS:
            errors.append(FieldError(f"policies.{action}", "unknown action"))
        elif not isinstance(ids, list):
            errors.append(FieldError(f"policies.{action}", "must be a list"))
    return errors


async def replace_policies(
    conn: AsyncConnection,
    tenant_id: UUID,
    resource_id: UUID,
    action: str,
    policy_ids: list[UUID],
) -> None:
    if action not in ACTIONS:
        raise _invalid("action", f"must be one of {', '.join(ACTIONS)}")
    unique = list(dict.fromkeys(policy_ids))
    field = f"policies.{action}"
    limit = await get_limit(conn, tenant_id=tenant_id, key=LIMIT_KEY)
    if len(unique) > limit:
        raise ApiError(
            409,
            "policy_slot_limit_reached",
            f"at most {limit} policies per resource and action",
            limit=limit,
            current=len(unique),
        )
    if unique:
        cur = await conn.execute(
            "SELECT id FROM access_policies WHERE tenant_id = %s AND id = ANY(%s)",
            (tenant_id, unique),
        )
        found = {row[0] for row in await cur.fetchall()}
        if missing := [str(i) for i in unique if i not in found]:
            raise _invalid(field, f"unknown policy: {', '.join(missing)}")
    await conn.execute(
        "DELETE FROM registry_policies WHERE registry_id = %s AND action = %s",
        (resource_id, action),
    )
    if unique:
        await conn.execute(
            "INSERT INTO registry_policies (registry_id, tenant_id, action, policy_id) "
            "SELECT %s, %s, %s, unnest(%s::uuid[])",
            (resource_id, tenant_id, action, unique),
        )


async def set_policies(
    conn: AsyncConnection,
    caller: Caller,
    resource_id: UUID,
    action: str,
    policy_ids: list[UUID],
) -> None:
    from krep.registry.resources import lock_for_edit

    row = await lock_for_edit(conn, caller, resource_id)
    await replace_policies(conn, row["tenant_id"], resource_id, action, policy_ids)


async def list_policies(
    conn: AsyncConnection, resource_id: UUID
) -> dict[str, list[UUID]]:
    cur = await conn.execute(
        "SELECT action, policy_id FROM registry_policies WHERE registry_id = %s "
        "ORDER BY action, policy_id",
        (resource_id,),
    )
    out: dict[str, list[UUID]] = {action: [] for action in ACTIONS}
    for action, policy_id in await cur.fetchall():
        out[action].append(policy_id)
    return out
