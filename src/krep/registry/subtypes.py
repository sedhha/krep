from typing import Any
from uuid import UUID

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from krep.api.errors import ApiError

FIXED_COLUMNS = ("version_id", "registry_id", "tenant_id", "type")


async def _table_name(conn: AsyncConnection, resource_type: str) -> str:
    cur = await conn.execute(
        "SELECT subtype_table FROM registry_types WHERE type = %s", (resource_type,)
    )
    row = await cur.fetchone()
    assert row is not None
    return str(row[0])


async def _columns(conn: AsyncConnection, name: str) -> dict[str, str]:
    cur = await conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (name,),
    )
    return {r[0]: r[1] for r in await cur.fetchall() if r[0] not in FIXED_COLUMNS}


async def insert_generic_spec(
    conn: AsyncConnection,
    resource_type: str,
    tenant_id: UUID,
    registry_id: UUID,
    version_id: UUID,
    spec: dict[str, Any],
) -> None:
    name = await _table_name(conn, resource_type)
    columns = await _columns(conn, name)
    unknown = sorted(set(spec) - set(columns))
    if unknown:
        raise ApiError(
            422,
            "validation_failed",
            "request validation failed",
            errors=[
                {"field": f"spec.{key}", "message": "unknown field"} for key in unknown
            ],
        )
    keys = list(spec)
    values = [
        Jsonb(spec[k]) if columns[k] in ("jsonb", "json") else spec[k] for k in keys
    ]
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(name),
        sql.SQL(", ").join(
            [sql.Identifier(c) for c in FIXED_COLUMNS[:3]]
            + [sql.Identifier(k) for k in keys]
        ),
        sql.SQL(", ").join(sql.Placeholder() * (3 + len(keys))),
    )
    await conn.execute(query, [version_id, registry_id, tenant_id, *values])


async def load_generic_spec(
    conn: AsyncConnection, resource_type: str, version_id: UUID
) -> dict[str, Any]:
    name = await _table_name(conn, resource_type)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql.SQL("SELECT * FROM {} WHERE version_id = %s").format(
                sql.Identifier(name)
            ),
            (version_id,),
        )
        row = await cur.fetchone()
    assert row is not None
    return {k: v for k, v in row.items() if k not in FIXED_COLUMNS}


async def copy_generic_spec(
    conn: AsyncConnection,
    resource_type: str,
    source_version_id: UUID,
    new_version_id: UUID,
) -> None:
    name = await _table_name(conn, resource_type)
    table = sql.Identifier(name)
    columns = sql.SQL(", ").join(sql.Identifier(c) for c in await _columns(conn, name))
    await conn.execute(
        sql.SQL(
            "INSERT INTO {t} (version_id, registry_id, tenant_id, {c}) "
            "SELECT %s, registry_id, tenant_id, {c} FROM {t} WHERE version_id = %s"
        ).format(t=table, c=columns),
        (new_version_id, source_version_id),
    )


async def delete_generic_spec(
    conn: AsyncConnection, resource_type: str, version_id: UUID
) -> None:
    name = await _table_name(conn, resource_type)
    await conn.execute(
        sql.SQL("DELETE FROM {} WHERE version_id = %s").format(sql.Identifier(name)),
        (version_id,),
    )
