from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from psycopg import AsyncConnection
from pydantic import BaseModel

from krep.api.deps import db, require_write
from krep.identity.resolve import Caller
from krep.registry import links

router = APIRouter(prefix="/v1")

Conn = Annotated[AsyncConnection, Depends(db)]
Writer = Annotated[Caller, Depends(require_write)]


class LinkIn(BaseModel):
    other_id: UUID
    relation: str
    direction: Literal["out", "in"]
    pinned_version: int | None = None
    auto_load: bool = False


@router.post("/registry/{resource_id}/links", status_code=201)
async def create_link(
    resource_id: UUID, body: LinkIn, caller: Writer, conn: Conn
) -> dict[str, Any]:
    return await links.create_link(
        conn,
        caller,
        resource_id,
        body.other_id,
        body.relation,
        body.direction,
        body.pinned_version,
        body.auto_load,
    )


@router.get("/registry/{resource_id}/links")
async def list_links(
    resource_id: UUID,
    caller: Writer,
    conn: Conn,
    direction: Annotated[Literal["out", "in", "both"], Query()] = "both",
    status: Annotated[
        Literal["pending", "accepted", "rejected"] | None, Query()
    ] = None,
) -> dict[str, Any]:
    return {
        "items": await links.list_links(conn, caller, resource_id, direction, status)
    }


@router.post("/links/{link_id}/accept")
async def accept_link(link_id: UUID, caller: Writer, conn: Conn) -> dict[str, Any]:
    return await links.accept_link(conn, caller, link_id)


@router.post("/links/{link_id}/reject")
async def reject_link(link_id: UUID, caller: Writer, conn: Conn) -> dict[str, Any]:
    return await links.reject_link(conn, caller, link_id)


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(link_id: UUID, caller: Writer, conn: Conn) -> Response:
    await links.delete_link(conn, caller, link_id)
    return Response(status_code=204)
