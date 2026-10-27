import json
from typing import Annotated, Any, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from psycopg import AsyncConnection
from pydantic import BaseModel, ValidationError, model_validator
from starlette.datastructures import UploadFile

from krep.api.deps import db, get_caller, require_write
from krep.api.errors import ApiError
from krep.identity.resolve import Caller
from krep.registry import resources
from krep.registry.skill_archive import MAX_ZIP_BYTES

router = APIRouter(prefix="/v1/registry")

Conn = Annotated[AsyncConnection, Depends(db)]
Writer = Annotated[Caller, Depends(require_write)]
Authenticated = Annotated[Caller, Depends(get_caller)]


class CreateIn(BaseModel):
    type: str
    slug: str
    name: str
    description: str | None = None
    tags: list[str] = []
    visibility: str = "private"
    policy_id: UUID | None = None
    meta: dict[str, Any] = {}
    spec: dict[str, Any] | None = None


class PatchIn(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    visibility: str | None = None
    policy_id: UUID | None = None
    meta: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _only_policy_id_is_nullable(self) -> Self:
        for key in self.model_fields_set - {"policy_id"}:
            if getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        422,
        "validation_failed",
        "request validation failed",
        errors=[{"field": field, "message": message}],
    )


def _from_validation_error(exc: ValidationError) -> ApiError:
    return ApiError(
        422,
        "validation_failed",
        "request validation failed",
        errors=[
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
            for e in exc.errors()
        ],
    )


async def _create_payload(request: Request) -> tuple[Any, bytes | None]:
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        metadata = form.get("metadata")
        if not isinstance(metadata, str):
            raise _invalid("metadata", "required")
        archive = form.get("archive")
        data = await archive.read(MAX_ZIP_BYTES + 1) if isinstance(archive, UploadFile) else None
        raw = metadata
    else:
        data = None
        raw = await request.body()
    try:
        return json.loads(raw), data
    except ValueError:
        raise _invalid("body", "must be valid JSON") from None


@router.post("", status_code=201)
async def create_resource(request: Request, caller: Writer, conn: Conn) -> dict[str, Any]:
    payload, archive = await _create_payload(request)
    try:
        body = CreateIn.model_validate(payload)
    except ValidationError as exc:
        raise _from_validation_error(exc) from None
    return await resources.create_resource(
        conn, caller, {**body.model_dump(), "archive": archive}
    )


@router.get("")
async def list_resources(
    caller: Writer,
    conn: Conn,
    type: str | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = resources.DEFAULT_LIST_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    items = await resources.list_resources(
        conn, caller, type=type, status=status, limit=limit, offset=offset
    )
    return {"items": items}


@router.get("/{resource_id}")
async def get_resource(resource_id: UUID, caller: Authenticated, conn: Conn) -> dict[str, Any]:
    view = await resources.get_visible(conn, caller, resource_id)
    if view is None:
        raise ApiError(404, "not_found", "resource not found")
    return view


@router.patch("/{resource_id}")
async def patch_resource(
    resource_id: UUID, body: PatchIn, caller: Writer, conn: Conn
) -> dict[str, Any]:
    return await resources.update_resource(
        conn, caller, resource_id, body.model_dump(exclude_unset=True)
    )


@router.post("/{resource_id}/archive")
async def archive_resource(resource_id: UUID, caller: Writer, conn: Conn) -> dict[str, Any]:
    return await resources.set_archived(conn, caller, resource_id, True)


@router.post("/{resource_id}/unarchive")
async def unarchive_resource(resource_id: UUID, caller: Writer, conn: Conn) -> dict[str, Any]:
    return await resources.set_archived(conn, caller, resource_id, False)


@router.delete("/{resource_id}", status_code=204)
async def delete_resource(resource_id: UUID, caller: Writer, conn: Conn) -> Response:
    await resources.delete_resource(conn, caller, resource_id)
    return Response(status_code=204)
