from typing import Annotated, Any

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from krep.api.deps import db, get_caller
from krep.identity.resolve import Caller
from krep.registry.limits import effective_limits

router = APIRouter(prefix="/v1")

Conn = Annotated[AsyncConnection, Depends(db)]
Authenticated = Annotated[Caller, Depends(get_caller)]


@router.get("/limits")
async def get_limits(caller: Authenticated, conn: Conn) -> dict[str, Any]:
    return await effective_limits(conn, caller.tenant_id)


@router.get("/registry/types")
async def list_types(_: Authenticated, conn: Conn) -> dict[str, Any]:
    cur = await conn.execute("SELECT type, description FROM registry_types ORDER BY type")
    return {"types": [{"type": t, "description": d} for t, d in await cur.fetchall()]}
