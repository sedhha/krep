from typing import Annotated, Any, Self, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from psycopg import AsyncConnection, errors
from pydantic import BaseModel, Field, model_validator

from krep.api.deps import db, require_admin
from krep.api.errors import ApiError
from krep.identity.resolve import ADMINS_POLICY, WRITERS_POLICY, Caller
from krep.policy.ast import (
    PolicyInvalid,
    PolicyParseError,
    PolicyTooLarge,
    to_source,
    validate_ast,
)
from krep.policy.compile import compile_ast
from krep.policy.evaluate import evaluate, evaluate_leaves, warnings_for
from krep.policy.parser import parse
from krep.policy.store import PolicyRow, write_policy
from krep.policy.summary import summarize

router = APIRouter(prefix="/v1/access-policies")

Admin = Annotated[Caller, Depends(require_admin)]
Conn = Annotated[AsyncConnection, Depends(db)]

RESERVED_NAMES = (ADMINS_POLICY, WRITERS_POLICY)
DEFAULT_MAX_POLICIES = 500
COLUMNS = (
    "id, tenant_id, name, description, ast, source, compiled_path::text, compiler_version, "
    "reserved, rev, created_by, created_at, updated_by, updated_at"
)


class RuleIn(BaseModel):
    source: str | None = None
    ast: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _exactly_one_rule(self) -> Self:
        if (self.source is None) == (self.ast is None):
            raise ValueError("provide exactly one of source or ast")
        return self


class PolicyIn(RuleIn):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=1000)


class PolicyUpdate(PolicyIn):
    rev: int


class RestoreIn(BaseModel):
    rev: int


class SampleIn(BaseModel):
    token: dict[str, Any] | None = None
    principal: dict[str, Any] | None = None

    @property
    def doc(self) -> dict[str, Any]:
        return {"token": self.token or {}, "principal": self.principal or {}}


class PreviewIn(RuleIn, SampleIn):
    pass


def _rule_ast(source: str | None, ast: dict[str, Any] | None) -> dict[str, Any]:
    try:
        if source is not None:
            return parse(source)
        checked = cast("dict[str, Any]", ast)
        validate_ast(checked)
        return checked
    except PolicyParseError as exc:
        raise ApiError(
            422, "policy_parse_error", exc.message, line=exc.line, column=exc.column
        ) from None
    except PolicyTooLarge as exc:
        raise ApiError(422, "policy_too_large", str(exc), nodes=exc.nodes, max=exc.max) from None
    except PolicyInvalid as exc:
        raise ApiError(422, "policy_invalid", exc.message) from None


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "access policy not found")


def _reserved() -> ApiError:
    return ApiError(409, "policy_reserved", "reserved policies cannot be renamed or deleted")


def _name_taken() -> ApiError:
    return ApiError(409, "policy_name_taken", "a policy with this name already exists")


def _view(row: PolicyRow, usage_count: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "reserved": row.reserved,
        "rev": row.rev,
        "ast": row.ast,
        "source": row.source,
        "compiled_path": row.compiled_path,
        "summary": summarize(row.ast),
        "usage_count": usage_count,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
        **extra,
    }


async def _usage_count(conn: AsyncConnection, policy_id: UUID) -> int:
    cur = await conn.execute("SELECT count(*) FROM registry WHERE policy_id = %s", (policy_id,))
    row = await cur.fetchone()
    return row[0] if row else 0


async def _fetch(conn: AsyncConnection, tenant_id: UUID, policy_id: UUID) -> PolicyRow:
    cur = await conn.execute(
        f"SELECT {COLUMNS} FROM access_policies WHERE tenant_id = %s AND id = %s",
        (tenant_id, policy_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise _not_found()
    return PolicyRow(*row)


async def _lock(conn: AsyncConnection, tenant_id: UUID, policy_id: UUID) -> tuple[str, bool, int]:
    cur = await conn.execute(
        "SELECT name, reserved, rev FROM access_policies "
        "WHERE tenant_id = %s AND id = %s FOR UPDATE",
        (tenant_id, policy_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise _not_found()
    return row


async def _max_policies(conn: AsyncConnection, tenant_id: UUID) -> int:
    cur = await conn.execute(
        "SELECT value FROM resource_limits WHERE limit_key = 'max_policies' "
        "AND resource_type IS NULL AND (scope_type = 'global' "
        "OR (scope_type = 'tenant' AND scope_id = %s)) "
        "ORDER BY (scope_type = 'tenant') DESC LIMIT 1",
        (str(tenant_id),),
    )
    row = await cur.fetchone()
    return row[0] if row else DEFAULT_MAX_POLICIES


@router.post("", status_code=201)
async def create_policy(caller: Admin, conn: Conn, body: PolicyIn) -> dict[str, Any]:
    ast = _rule_ast(body.source, body.ast)
    if body.name in RESERVED_NAMES:
        raise _reserved()
    cur = await conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE name = %s) FROM access_policies "
        "WHERE tenant_id = %s",
        (body.name, caller.tenant_id),
    )
    total, same_name = (await cur.fetchone()) or (0, 0)
    if same_name:
        raise _name_taken()
    limit = await _max_policies(conn, caller.tenant_id)
    if total >= limit:
        raise ApiError(
            409, "policy_limit_reached", "policy limit reached", max=limit, current=total
        )
    try:
        row = await write_policy(
            conn, caller.tenant_id, body.name, ast, caller.user_id, description=body.description
        )
    except errors.UniqueViolation:
        raise _name_taken() from None
    return _view(row, 0, warnings=[])


@router.get("")
async def list_policies(caller: Admin, conn: Conn) -> dict[str, Any]:
    cur = await conn.execute(
        f"SELECT {COLUMNS}, (SELECT count(*) FROM registry r WHERE r.policy_id = p.id) "
        "FROM access_policies p WHERE tenant_id = %s ORDER BY name",
        (caller.tenant_id,),
    )
    items: list[dict[str, Any]] = []
    for *columns, usage_count in await cur.fetchall():
        row = PolicyRow(*columns)
        items.append(
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "reserved": row.reserved,
                "rev": row.rev,
                "summary": summarize(row.ast),
                "usage_count": usage_count,
                "updated_at": row.updated_at,
            }
        )
    return {"items": items}


@router.post("/preview")
async def preview_policy(caller: Admin, body: PreviewIn) -> dict[str, Any]:
    ast = _rule_ast(body.source, body.ast)
    sampled = body.token is not None or body.principal is not None
    return {
        "ast": ast,
        "source": to_source(ast),
        "compiled_path": compile_ast(ast),
        "summary": summarize(ast),
        "warnings": warnings_for(ast, body.doc) if sampled else [],
    }


@router.get("/{policy_id}")
async def get_policy(policy_id: UUID, caller: Admin, conn: Conn) -> dict[str, Any]:
    row = await _fetch(conn, caller.tenant_id, policy_id)
    return _view(row, await _usage_count(conn, policy_id))


@router.put("/{policy_id}")
async def replace_policy(
    policy_id: UUID, caller: Admin, conn: Conn, body: PolicyUpdate
) -> dict[str, Any]:
    name, reserved, rev = await _lock(conn, caller.tenant_id, policy_id)
    if body.rev != rev:
        raise ApiError(409, "rev_conflict", "policy was modified", current_rev=rev)
    ast = _rule_ast(body.source, body.ast)
    if body.name != name:
        if reserved or body.name in RESERVED_NAMES:
            raise _reserved()
        try:
            await conn.execute(
                "UPDATE access_policies SET name = %s WHERE id = %s", (body.name, policy_id)
            )
        except errors.UniqueViolation:
            raise _name_taken() from None
    row = await write_policy(
        conn, caller.tenant_id, body.name, ast, caller.user_id, description=body.description
    )
    return _view(row, await _usage_count(conn, policy_id), warnings=[])


@router.delete("/{policy_id}", status_code=204)
async def delete_policy(policy_id: UUID, caller: Admin, conn: Conn) -> Response:
    _, reserved, _ = await _lock(conn, caller.tenant_id, policy_id)
    if reserved:
        raise _reserved()
    usage_count = await _usage_count(conn, policy_id)
    if usage_count:
        raise ApiError(
            409,
            "policy_in_use",
            "policy is referenced by resources",
            usage_count=usage_count,
        )
    await conn.execute("DELETE FROM access_policies WHERE id = %s", (policy_id,))
    return Response(status_code=204)


@router.get("/{policy_id}/resources")
async def policy_resources(
    policy_id: UUID, caller: Admin, conn: Conn, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> dict[str, Any]:
    await _fetch(conn, caller.tenant_id, policy_id)
    cur = await conn.execute(
        "SELECT id, type, slug, name, status, visibility FROM registry "
        "WHERE tenant_id = %s AND policy_id = %s ORDER BY name, id LIMIT %s",
        (caller.tenant_id, policy_id, limit),
    )
    items = [
        {"id": r[0], "type": r[1], "slug": r[2], "name": r[3], "status": r[4], "visibility": r[5]}
        for r in await cur.fetchall()
    ]
    return {"usage_count": await _usage_count(conn, policy_id), "items": items}


@router.get("/{policy_id}/history")
async def policy_history(policy_id: UUID, caller: Admin, conn: Conn) -> dict[str, Any]:
    await _fetch(conn, caller.tenant_id, policy_id)
    cur = await conn.execute(
        "SELECT rev, ast, source, changed_by, changed_at FROM access_policy_history "
        "WHERE policy_id = %s ORDER BY rev DESC LIMIT 20",
        (policy_id,),
    )
    items = [
        {"rev": r[0], "ast": r[1], "source": r[2], "changed_by": r[3], "changed_at": r[4]}
        for r in await cur.fetchall()
    ]
    return {"items": items}


@router.post("/{policy_id}/restore")
async def restore_policy(
    policy_id: UUID, caller: Admin, conn: Conn, body: RestoreIn
) -> dict[str, Any]:
    name, _, _ = await _lock(conn, caller.tenant_id, policy_id)
    cur = await conn.execute(
        "SELECT ast FROM access_policy_history WHERE policy_id = %s AND rev = %s",
        (policy_id, body.rev),
    )
    old = await cur.fetchone()
    if old is None:
        raise ApiError(404, "not_found", "revision not found")
    ast = _rule_ast(None, old[0])
    row = await write_policy(conn, caller.tenant_id, name, ast, caller.user_id)
    return _view(row, await _usage_count(conn, policy_id), warnings=[])


@router.post("/{policy_id}/test")
async def test_policy(
    policy_id: UUID, caller: Admin, conn: Conn, body: SampleIn
) -> dict[str, Any]:
    row = await _fetch(conn, caller.tenant_id, policy_id)
    leaves = await evaluate_leaves(conn, row.ast, body.doc, caller.tenant_id)
    return {
        "visible": await evaluate(conn, row.compiled_path, body.doc, caller.tenant_id),
        "leaves": [
            {"text": leaf.text, "result": leaf.result, **({"note": leaf.note} if leaf.note else {})}
            for leaf in leaves
        ],
        "warnings": warnings_for(row.ast, body.doc),
    }
