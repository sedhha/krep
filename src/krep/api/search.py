import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from psycopg import AsyncConnection
from pydantic import BaseModel

from krep.api.deps import db, get_caller, require_admin
from krep.config import get_settings
from krep.identity.resolve import Caller
from krep.metrics import SEARCH_ZERO_RESULTS
from krep.search import synonyms
from krep.search.engine import MAX_LIMIT, MAX_OFFSET, registry_search
from krep.search.query import normalise

router = APIRouter(prefix="/v1")

logger = logging.getLogger("krep.search")

Conn = Annotated[AsyncConnection, Depends(db)]
Authenticated = Annotated[Caller, Depends(get_caller)]
Admin = Annotated[Caller, Depends(require_admin)]


class SynonymIn(BaseModel):
    terms: list[str]


@router.get("/registry/search")
async def search(
    caller: Authenticated,
    conn: Conn,
    q: str = "",
    type: str | None = None,
    tags: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 10,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> dict[str, Any]:
    tag_list = [t for t in (part.strip() for part in (tags or "").split(",")) if t]
    groups = await synonyms.groups_for(conn, caller.tenant_id)
    hits = await registry_search(
        conn,
        caller,
        q=q,
        type=type,
        tags=tag_list,
        limit=limit,
        offset=offset,
        groups=groups,
    )
    if not hits and offset == 0 and q.strip():
        SEARCH_ZERO_RESULTS.labels(tenant=str(caller.tenant_id)).inc()
        if get_settings().search_log_zero_results:
            logger.info("search_zero_results", extra={"query": normalise(q)})
    return {
        "items": [
            {
                "id": str(h.id),
                "type": h.type,
                "slug": h.slug,
                "name": h.name,
                "description": h.description,
                "tags": h.tags,
                "current_version": h.current_version,
                "score": h.score,
            }
            for h in hits
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/search/synonyms")
async def list_synonyms(caller: Admin, conn: Conn) -> dict[str, Any]:
    return {"items": await synonyms.list_groups(conn, caller.tenant_id)}


@router.post("/search/synonyms", status_code=201)
async def create_synonym(body: SynonymIn, caller: Admin, conn: Conn) -> dict[str, Any]:
    return await synonyms.create_group(conn, caller, body.terms)


@router.put("/search/synonyms/{group_id}")
async def update_synonym(
    group_id: UUID, body: SynonymIn, caller: Admin, conn: Conn
) -> dict[str, Any]:
    return await synonyms.update_group(conn, caller.tenant_id, group_id, body.terms)


@router.delete("/search/synonyms/{group_id}", status_code=204)
async def delete_synonym(group_id: UUID, caller: Admin, conn: Conn) -> Response:
    await synonyms.delete_group(conn, caller.tenant_id, group_id)
    return Response(status_code=204)
