from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from krep.policy.ast import to_source
from krep.policy.compile import COMPILER_VERSION, compile_ast

DEFAULT_MAX_HISTORY = 20


class RevConflict(Exception):
    def __init__(self, current_rev: int):
        super().__init__(f"rev_conflict: current_rev={current_rev}")
        self.current_rev = current_rev


@dataclass(frozen=True)
class PolicyRow:
    id: UUID
    tenant_id: UUID
    name: str
    description: str
    ast: dict[str, Any]
    source: str
    compiled_path: str
    compiler_version: int
    reserved: bool
    rev: int
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


_COLUMNS = (
    "id, tenant_id, name, description, ast, source, compiled_path::text, compiler_version, "
    "reserved, rev, created_by, created_at, updated_by, updated_at"
)


async def _max_history(conn: AsyncConnection, tenant_id: UUID) -> int:
    cur = await conn.execute(
        "SELECT value FROM resource_limits WHERE limit_key = 'max_policy_history' "
        "AND resource_type IS NULL AND (scope_type = 'global' "
        "OR (scope_type = 'tenant' AND scope_id = %s)) "
        "ORDER BY (scope_type = 'tenant') DESC LIMIT 1",
        (str(tenant_id),),
    )
    row = await cur.fetchone()
    return row[0] if row else DEFAULT_MAX_HISTORY


async def write_policy(
    conn: AsyncConnection,
    tenant_id: UUID,
    name: str,
    ast: dict[str, Any],
    user: str,
    *,
    reserved: bool = False,
    expected_rev: int | None = None,
    description: str | None = None,
) -> PolicyRow:
    source = to_source(ast)
    compiled = compile_ast(ast)
    cur = await conn.execute(
        "SELECT id, rev FROM access_policies WHERE tenant_id = %s AND name = %s FOR UPDATE",
        (tenant_id, name),
    )
    existing = await cur.fetchone()
    if existing is None:
        cur = await conn.execute(
            "INSERT INTO access_policies (tenant_id, name, description, ast, source, "
            "compiled_path, compiler_version, reserved, created_by, updated_by) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonpath, %s, %s, %s, %s) "
            f"RETURNING {_COLUMNS}",
            (
                tenant_id, name, description or "", Jsonb(ast), source, compiled,
                COMPILER_VERSION, reserved, user, user,
            ),
        )
    else:
        policy_id, current_rev = existing
        if expected_rev is not None and expected_rev != current_rev:
            raise RevConflict(current_rev)
        cur = await conn.execute(
            "UPDATE access_policies SET ast = %s, source = %s, compiled_path = %s::jsonpath, "
            "compiler_version = %s, rev = rev + 1, updated_by = %s, updated_at = now(), "
            "description = coalesce(%s, description) "
            f"WHERE id = %s RETURNING {_COLUMNS}",
            (Jsonb(ast), source, compiled, COMPILER_VERSION, user, description, policy_id),
        )
    row = PolicyRow(*await cur.fetchone())  # type: ignore[misc]
    await conn.execute(
        "INSERT INTO access_policy_history (policy_id, tenant_id, rev, ast, source, changed_by) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (row.id, tenant_id, row.rev, Jsonb(ast), source, user),
    )
    await conn.execute(
        "DELETE FROM access_policy_history WHERE policy_id = %s AND rev <= %s",
        (row.id, row.rev - await _max_history(conn, tenant_id)),
    )
    return row
