import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from psycopg import AsyncConnection
from pydantic import BaseModel, ValidationError

from krep.api.deps import db, get_caller, require_write
from krep.api.errors import ApiError
from krep.api.skill_archive import is_multipart, read_archive_part
from krep.identity.resolve import Caller
from krep.registry import publish, versions

router = APIRouter(prefix="/v1/registry/{resource_id}")

Conn = Annotated[AsyncConnection, Depends(db)]
Writer = Annotated[Caller, Depends(require_write)]
Authenticated = Annotated[Caller, Depends(get_caller)]


class DraftIn(BaseModel):
    from_version: int | None = None


class ReplaceIn(BaseModel):
    spec: dict[str, Any] | None = None


class PublishIn(BaseModel):
    make_current: bool = True


class CurrentIn(BaseModel):
    version: int


def _invalid(errors: list[dict[str, str]]) -> ApiError:
    return ApiError(422, "validation_failed", "request validation failed", errors=errors)


def _from_validation_error(exc: ValidationError) -> ApiError:
    return _invalid(
        [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
    )


async def _json_body(request: Request) -> Any:
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise _invalid([{"field": "body", "message": "must be valid JSON"}]) from None


@router.get("/versions")
async def list_versions(resource_id: UUID, caller: Authenticated, conn: Conn) -> dict[str, Any]:
    return {"items": await versions.list_versions(conn, caller, resource_id)}


@router.post("/versions", status_code=201)
async def create_draft(
    resource_id: UUID, request: Request, caller: Writer, conn: Conn
) -> dict[str, Any]:
    if is_multipart(request):
        return await versions.create_draft(
            conn, caller, resource_id, archive=await read_archive_part(request)
        )
    try:
        body = DraftIn.model_validate(await _json_body(request))
    except ValidationError as exc:
        raise _from_validation_error(exc) from None
    return await versions.create_draft(conn, caller, resource_id, from_version=body.from_version)


@router.get("/versions/{n}")
async def get_version(resource_id: UUID, n: int, caller: Authenticated, conn: Conn) -> dict[str, Any]:
    return await versions.get_version(conn, caller, resource_id, n)


@router.get("/versions/{n}/archive")
async def get_archive(resource_id: UUID, n: int, caller: Authenticated, conn: Conn) -> Response:
    data, sha = await versions.get_archive(conn, caller, resource_id, n)
    return Response(
        data,
        media_type="application/zip",
        headers={"ETag": f'"{sha}"', "Cache-Control": "private, no-store"},
    )


@router.put("/versions/{n}")
async def replace_draft(
    resource_id: UUID, n: int, request: Request, caller: Writer, conn: Conn
) -> dict[str, Any]:
    if is_multipart(request):
        return await versions.replace_draft(
            conn, caller, resource_id, n, archive=await read_archive_part(request)
        )
    try:
        body = ReplaceIn.model_validate(await _json_body(request))
    except ValidationError as exc:
        raise _from_validation_error(exc) from None
    return await versions.replace_draft(conn, caller, resource_id, n, spec=body.spec)


@router.delete("/versions/{n}", status_code=204)
async def delete_version(resource_id: UUID, n: int, caller: Writer, conn: Conn) -> Response:
    await versions.delete_version(conn, caller, resource_id, n)
    return Response(status_code=204)


@router.post("/versions/{n}/publish")
async def publish_version(
    resource_id: UUID, n: int, caller: Writer, conn: Conn, body: PublishIn | None = None
) -> dict[str, Any]:
    make_current = body.make_current if body else True
    return await publish.publish(conn, caller, resource_id, n, make_current=make_current)


@router.post("/current")
async def set_current(
    resource_id: UUID, body: CurrentIn, caller: Writer, conn: Conn
) -> dict[str, Any]:
    return await publish.set_current(conn, caller, resource_id, body.version)
