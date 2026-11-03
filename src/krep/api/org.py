from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from psycopg import AsyncConnection
from pydantic import BaseModel, Field, model_validator

from krep.api.admin import SLUG_PATTERN, AuthIn
from krep.api.deps import db, require_admin
from krep.api.errors import ApiError
from krep.api.groups import Groups
from krep.api.policies import rule_ast
from krep.auth.store import load_effective
from krep.identity.resolve import Caller
from krep.org import audit, service
from krep.policy.compile import compile_ast
from krep.policy.evaluate import evaluate

router = APIRouter(prefix="/v1/org")

Admin = Annotated[Caller, Depends(require_admin)]
Conn = Annotated[AsyncConnection, Depends(db)]


class Auditor:
    def __init__(self, conn: AsyncConnection, caller: Caller) -> None:
        self.conn = conn
        self.caller = caller

    async def __call__(
        self, action: str, target: str | None, detail: dict[str, Any] | None = None
    ) -> None:
        await audit.record(
            self.conn,
            self.caller.user_id,
            action,
            self.caller.tenant_id,
            target,
            detail,
        )


async def get_auditor(caller: Admin, conn: Conn) -> Auditor:
    return Auditor(conn, caller)


Audited = Annotated[Auditor, Depends(get_auditor)]


class ProductIn(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=120)


class ProductPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    status: Literal["active", "archived"] | None = None

    @model_validator(mode="after")
    def _something(self) -> "ProductPatch":
        if self.name is None and self.status is None:
            raise ValueError("provide name or status")
        return self


class TokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=8192)


class MemberIn(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    groups: Groups = Field(default_factory=list)


class MemberPatch(BaseModel):
    groups: Groups


class CapabilitiesIn(BaseModel):
    rules: dict[str, str] = Field(min_length=1)


def _detail_for(auth: AuthIn) -> dict[str, Any]:
    return {"adapter": auth.adapter, "secret_rotated": auth.secret is not None}


@router.get("/products")
async def list_products(caller: Admin, conn: Conn) -> dict[str, Any]:
    return {"items": await service.list_products(conn, caller.tenant_id)}


@router.post("/products", status_code=201)
async def create_product(
    caller: Admin, conn: Conn, audited: Audited, body: ProductIn
) -> dict[str, Any]:
    product = await service.create_product(
        conn, caller.tenant_id, body.slug, body.name, caller.user_id
    )
    await audited("product.create", body.slug)
    return product


@router.patch("/products/{product_id}")
async def update_product(
    product_id: UUID, caller: Admin, conn: Conn, audited: Audited, body: ProductPatch
) -> dict[str, Any]:
    product = await service.update_product(
        conn, caller.tenant_id, product_id, body.name, body.status
    )
    await audited("product.update", product["slug"], body.model_dump(exclude_none=True))
    return product


@router.get("/auth")
async def get_auth(caller: Admin, conn: Conn) -> dict[str, Any]:
    return await service.get_auth(conn, caller.tenant_id, None)


@router.put("/auth")
async def put_auth(
    caller: Admin, conn: Conn, audited: Audited, body: AuthIn
) -> dict[str, Any]:
    view = await service.put_auth(
        conn,
        caller.tenant_id,
        None,
        body.adapter,
        body.config,
        body.secret,
        caller.user_id,
    )
    await audited("auth.set", None, _detail_for(body))
    return view


@router.delete("/auth", status_code=204)
async def delete_auth(caller: Admin, conn: Conn, audited: Audited) -> Response:
    await service.delete_auth(conn, caller.tenant_id, None)
    await audited("auth.delete", None)
    return Response(status_code=204)


@router.get("/products/{product_id}/auth")
async def get_product_auth(
    product_id: UUID, caller: Admin, conn: Conn
) -> dict[str, Any]:
    await service.require_product(conn, caller.tenant_id, product_id)
    return await service.get_auth(conn, caller.tenant_id, product_id)


@router.put("/products/{product_id}/auth")
async def put_product_auth(
    product_id: UUID, caller: Admin, conn: Conn, audited: Audited, body: AuthIn
) -> dict[str, Any]:
    product = await service.require_product(conn, caller.tenant_id, product_id)
    view = await service.put_auth(
        conn,
        caller.tenant_id,
        product_id,
        body.adapter,
        body.config,
        body.secret,
        caller.user_id,
    )
    await audited("product.auth.set", product["slug"], _detail_for(body))
    return view


@router.delete("/products/{product_id}/auth", status_code=204)
async def delete_product_auth(
    product_id: UUID, caller: Admin, conn: Conn, audited: Audited
) -> Response:
    product = await service.require_product(conn, caller.tenant_id, product_id)
    await service.delete_auth(conn, caller.tenant_id, product_id)
    await audited("product.auth.delete", product["slug"])
    return Response(status_code=204)


@router.get("/products/{product_id}/effective-auth")
async def effective_auth(product_id: UUID, caller: Admin, conn: Conn) -> dict[str, Any]:
    await service.require_product(conn, caller.tenant_id, product_id)
    return await service.get_effective_auth(conn, caller.tenant_id, product_id)


@router.post("/auth/test")
async def test_auth(caller: Admin, conn: Conn, body: TokenIn) -> dict[str, Any]:
    resolved = await load_effective(conn, caller.tenant_id, caller.product_id)
    if resolved is None:
        return {"valid": False, "reason": "no_auth_config"}
    try:
        claims = dict(resolved.verify(body.token))
    except ApiError:
        return {"valid": False, "reason": "invalid_token"}
    return {"valid": True, "claims": claims}


@router.get("/members")
async def list_members(caller: Admin, conn: Conn) -> dict[str, Any]:
    return {"items": await service.list_members(conn, caller.tenant_id)}


@router.post("/members", status_code=201)
async def add_member(
    caller: Admin, conn: Conn, audited: Audited, body: MemberIn
) -> dict[str, Any]:
    user_id = await service.find_user(conn, body.identifier)
    if user_id is None:
        raise service.not_found("user")
    member = await service.add_member(
        conn, caller.tenant_id, user_id, body.groups, caller.user_id
    )
    await audited("member.add", user_id, {"groups": body.groups})
    return member


@router.patch("/members/{user_id}")
async def update_member(
    user_id: str, caller: Admin, conn: Conn, audited: Audited, body: MemberPatch
) -> dict[str, Any]:
    member = await service.update_member(
        conn, caller.tenant_id, user_id, body.groups, caller.is_platform_admin
    )
    await audited("member.update", user_id, {"groups": body.groups})
    return member


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    user_id: str, caller: Admin, conn: Conn, audited: Audited
) -> Response:
    await service.remove_member(
        conn, caller.tenant_id, user_id, caller.is_platform_admin
    )
    await audited("member.remove", user_id)
    return Response(status_code=204)


@router.put("/capabilities")
async def put_capabilities(
    caller: Admin, conn: Conn, audited: Audited, body: CapabilitiesIn
) -> dict[str, Any]:
    unknown = sorted(set(body.rules) - set(service.CAPABILITY_NAMES))
    if unknown:
        raise ApiError(
            422, "capability_unknown", "unknown capability policy", names=unknown
        )
    asts = {name: rule_ast(src, None) for name, src in body.rules.items()}
    admins = asts.get("registry-admins")
    if admins is not None and not caller.is_platform_admin:
        if not await evaluate(conn, compile_ast(admins), caller.doc, caller.tenant_id):
            raise ApiError(
                409,
                "capability_lockout",
                "the new registry-admins rule would exclude you",
            )
    items = await service.write_capabilities(
        conn, caller.tenant_id, asts, caller.user_id
    )
    await audited("capabilities.update", None, {"names": sorted(asts)})
    return {"items": items}
