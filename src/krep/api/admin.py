from collections.abc import AsyncGenerator
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from krep.api.errors import ApiError
from krep.api.groups import Groups
from krep.api.policies import rule_ast
from krep.auth.adapters import list_adapters
from krep.config import get_settings
from krep.db.tenant import tenant_transaction
from krep.identity.login import PanelIdentity, authenticate_panel
from krep.identity.resolve import Caller
from krep.org import audit, service
from krep.registry.scope import set_scope

router = APIRouter(prefix="/v1/admin")

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}$"


class AuthIn(BaseModel):
    adapter: str
    config: dict[str, Any] = Field(default_factory=dict)
    secret: str | None = None


class OrganizationIn(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    admin_user: str = Field(min_length=1, max_length=320)
    capabilities: dict[str, str] | None = None
    auth: AuthIn | None = None


class MembershipIn(BaseModel):
    groups: Groups = Field(default_factory=list)


class ScopeIn(BaseModel):
    organization_id: UUID
    scope: Literal["org", "product", "global"]
    product: str | None = None


class DisableIn(BaseModel):
    reason: str = Field("", max_length=500)


async def platform_actor(request: Request) -> PanelIdentity:
    settings = get_settings()
    if getattr(request.app.state, "platform_pool", None) is None or not (
        settings.platform_admin_key or settings.login_issuer
    ):
        raise ApiError(404, "not_found", "not found")
    headers = {name.lower(): value for name, value in request.headers.items()}
    identity = await authenticate_panel(request.app.state.pool, headers)
    if identity is None:
        raise ApiError(401, "unauthenticated", "invalid or missing credentials")
    if not identity.is_platform_admin:
        raise ApiError(403, "forbidden", "platform admin required")
    return identity


Actor = Annotated[PanelIdentity, Depends(platform_actor)]


async def platform_conn(request: Request, _: Actor) -> AsyncGenerator[AsyncConnection]:
    async with (
        request.app.state.platform_pool.connection() as conn,
        conn.transaction(),
    ):
        yield conn


Conn = Annotated[AsyncConnection, Depends(platform_conn)]


@router.get("/auth-adapters")
async def auth_adapters(_: Actor) -> dict[str, Any]:
    return {"items": list_adapters()}


@router.post("/organizations", status_code=201)
async def create_organization(
    actor: Actor, conn: Conn, body: OrganizationIn
) -> dict[str, Any]:
    asts: dict[str, dict[str, Any]] | None = None
    if body.capabilities is not None:
        unknown = sorted(set(body.capabilities) - set(service.CAPABILITY_NAMES))
        if unknown:
            raise ApiError(
                422, "capability_unknown", "unknown capability policy", names=unknown
            )
        asts = {n: rule_ast(src, None) for n, src in body.capabilities.items()}
    return await service.create_organization(
        conn,
        actor.user_id,
        body.slug,
        body.name,
        body.admin_user,
        asts,
        None if body.auth is None else body.auth.model_dump(),
    )


@router.get("/organizations")
async def list_organizations(_: Actor, conn: Conn) -> dict[str, Any]:
    return {"items": await service.list_organizations(conn)}


@router.get("/organizations/{org_id}")
async def get_organization(org_id: UUID, _: Actor, conn: Conn) -> dict[str, Any]:
    return await service.get_organization(conn, org_id)


@router.put("/organizations/{org_id}/members/{user_id}")
async def attach_member(
    org_id: UUID, user_id: str, actor: Actor, conn: Conn, body: MembershipIn
) -> dict[str, Any]:
    await service.get_organization(conn, org_id)
    if not await service.user_exists(conn, user_id):
        raise service.not_found("user")
    await service.scope(conn, org_id)
    member = await service.upsert_member(
        conn, org_id, user_id, body.groups, actor.user_id
    )
    await audit.record(
        conn,
        actor.user_id,
        "org.member.attach",
        org_id,
        user_id,
        {"groups": body.groups},
    )
    return member


@router.delete("/organizations/{org_id}/members/{user_id}", status_code=204)
async def detach_member(
    org_id: UUID, user_id: str, actor: Actor, conn: Conn
) -> Response:
    await service.get_organization(conn, org_id)
    await service.scope(conn, org_id)
    await service.remove_member(conn, org_id, user_id, bypass_last_admin=True)
    await audit.record(conn, actor.user_id, "org.member.detach", org_id, user_id)
    return Response(status_code=204)


@router.put("/platform-admins/{user_id}")
async def grant_platform_admin(
    user_id: str, actor: Actor, conn: Conn
) -> dict[str, Any]:
    if not await service.user_exists(conn, user_id):
        raise service.not_found("user")
    await conn.execute(
        "INSERT INTO platform_admins (user_id, granted_by) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO NOTHING",
        (user_id, actor.user_id),
    )
    await audit.record(conn, actor.user_id, "platform_admin.grant", None, user_id)
    return {"user_id": user_id, "platform_admin": True}


@router.delete("/platform-admins/{user_id}", status_code=204)
async def revoke_platform_admin(user_id: str, actor: Actor, conn: Conn) -> Response:
    cur = await conn.execute(
        "DELETE FROM platform_admins WHERE user_id = %s", (user_id,)
    )
    if cur.rowcount == 0:
        raise service.not_found("platform admin")
    await audit.record(conn, actor.user_id, "platform_admin.revoke", None, user_id)
    return Response(status_code=204)


@router.post("/users/{user_id}/disable")
async def disable_user(
    user_id: str, actor: Actor, conn: Conn, body: DisableIn | None = None
) -> dict[str, Any]:
    if not await service.user_exists(conn, user_id):
        raise service.not_found("user")
    reason = body.reason if body else ""
    await conn.execute(
        "INSERT INTO disabled_users (user_id, reason, disabled_by) VALUES (%s, %s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET reason = EXCLUDED.reason, "
        "disabled_by = EXCLUDED.disabled_by, disabled_at = now()",
        (user_id, reason, actor.user_id),
    )
    await audit.record(
        conn, actor.user_id, "user.disable", None, user_id, {"reason": reason}
    )
    return {"user_id": user_id, "disabled": True}


@router.post("/users/{user_id}/enable")
async def enable_user(user_id: str, actor: Actor, conn: Conn) -> dict[str, Any]:
    await conn.execute("DELETE FROM disabled_users WHERE user_id = %s", (user_id,))
    await audit.record(conn, actor.user_id, "user.enable", None, user_id)
    return {"user_id": user_id, "disabled": False}


@router.get("/audit")
async def audit_log(
    _: Actor,
    conn: Conn,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    before: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    cur = await conn.execute(
        "SELECT id, actor, action, tenant_id, target, detail, at FROM admin_audit_log "
        "WHERE (%s::bigint IS NULL OR id < %s) ORDER BY id DESC LIMIT %s",
        (before, before, limit),
    )
    keys = ("id", "actor", "action", "tenant_id", "target", "detail", "at")
    return {
        "items": [dict(zip(keys, row, strict=True)) for row in await cur.fetchall()]
    }


@router.put("/registry/{resource_id}/scope")
async def set_registry_scope(
    resource_id: UUID, actor: Actor, request: Request, body: ScopeIn
) -> dict[str, Any]:
    async with tenant_transaction(request.app.state.pool, body.organization_id) as conn:
        await conn.execute("SELECT set_config('app.platform_admin', 'on', true)")
        caller = Caller(
            body.organization_id,
            actor.user_id,
            {"token": {}, "principal": {}},
            True,
            True,
            is_platform_admin=True,
        )
        return await set_scope(conn, caller, resource_id, body.scope, body.product)
