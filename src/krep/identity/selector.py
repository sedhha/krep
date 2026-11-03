from collections.abc import Mapping
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.auth.store import load_effective
from krep.db.tenant import tenant_transaction
from krep.identity.login import (
    PanelIdentity,
    authenticate_panel,
    bearer_token,
    evaluation_token,
    load_groups,
    unauthenticated,
)
from krep.identity.principal import decode_principal
from krep.identity.resolve import Caller, capabilities, dig

Pool = AsyncConnectionPool[AsyncConnection]


async def _organisation(pool: Pool, slug: str) -> UUID:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id FROM organizations WHERE slug = %s AND status = 'active'",
            (slug,),
        )
        row = await cur.fetchone()
    if row is None:
        raise unauthenticated()
    return row[0]


async def _product(conn: AsyncConnection, tenant_id: UUID, slug: str) -> UUID:
    cur = await conn.execute(
        "SELECT id FROM products WHERE tenant_id = %s AND slug = %s AND status = 'active'",
        (tenant_id, slug),
    )
    row = await cur.fetchone()
    if row is None:
        raise unauthenticated()
    return row[0]


async def _panel_caller(
    pool: Pool,
    identity: PanelIdentity,
    tenant_id: UUID,
    product_id: UUID | None,
    slug: str,
) -> Caller:
    groups = None
    if not identity.via_key:
        async with tenant_transaction(pool, tenant_id) as conn:
            groups = await load_groups(conn, tenant_id, identity.user_id)
    if groups is None and not identity.is_platform_admin:
        raise unauthenticated()
    doc = {"token": evaluation_token(identity, groups or []), "principal": {}}
    if identity.is_platform_admin:
        can_read = can_write = can_admin = True
    else:
        can_read, can_write, can_admin = await capabilities(pool, tenant_id, doc)
    return Caller(
        tenant_id,
        identity.user_id,
        doc,
        can_write,
        can_admin,
        product_id,
        can_read,
        identity.is_platform_admin,
        slug,
        "platform_key" if identity.via_key else "login",
    )


async def _org_token_caller(
    pool: Pool,
    token: str,
    principal_header: str | None,
    tenant_id: UUID,
    product_id: UUID | None,
    slug: str,
) -> Caller:
    try:
        async with tenant_transaction(pool, tenant_id) as conn:
            resolved = await load_effective(conn, tenant_id, product_id)
        if resolved is None:
            raise unauthenticated()
        claims = dict(resolved.verify(token))
    except Exception:
        raise unauthenticated() from None
    machine = bool(getattr(resolved.config, "allow_principal", False))
    principal = decode_principal(principal_header) if machine else None
    if principal:
        user_id = principal["id"]
    else:
        path = (
            ["sub"] if machine else getattr(resolved.config, "user_claim_path", ["sub"])
        )
        subject = dig(claims, list(path))
        if not isinstance(subject, str) or not subject:
            raise unauthenticated()
        user_id = f"client:{subject}" if machine else subject
    doc = {"token": claims, "principal": principal or {}}
    can_read, can_write, can_admin = await capabilities(pool, tenant_id, doc)
    return Caller(
        tenant_id,
        user_id,
        doc,
        can_write,
        can_admin,
        product_id,
        can_read,
        False,
        slug,
        "org_token",
    )


async def resolve_selector(pool: Pool, headers: Mapping[str, str]) -> Caller:
    slug = headers.get("x-org", "").strip()
    if not slug:
        raise unauthenticated()
    tenant_id = await _organisation(pool, slug)
    product_slug = headers.get("x-product", "").strip()
    product_id = None
    if product_slug:
        async with tenant_transaction(pool, tenant_id) as conn:
            product_id = await _product(conn, tenant_id, product_slug)
    identity = await authenticate_panel(pool, headers)
    if identity is not None:
        return await _panel_caller(pool, identity, tenant_id, product_id, slug)
    token = bearer_token(headers)
    if token is None:
        raise unauthenticated()
    return await _org_token_caller(
        pool, token, headers.get("x-principal"), tenant_id, product_id, slug
    )


async def _memberships(pool: Pool, user_id: str) -> list[dict[str, Any]]:
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.user_id', %s, true)", (user_id,))
        cur = await conn.execute(
            "SELECT o.slug, m.groups FROM memberships m "
            "JOIN organizations o ON o.id = m.tenant_id "
            "WHERE m.user_id = %s AND o.status = 'active' ORDER BY o.slug",
            (user_id,),
        )
        return [
            {"organization": slug, "groups": list(groups)}
            for slug, groups in await cur.fetchall()
        ]


async def describe_me(pool: Pool, headers: Mapping[str, str]) -> dict[str, Any]:
    headers = {name.lower(): value for name, value in headers.items()}
    caller: Caller | None = None
    if "x-org" in headers:
        caller = await resolve_selector(pool, headers)
        panel = caller.source in ("login", "platform_key")
        user_id = caller.user_id
        username = str(caller.doc["token"].get("username", "")) if panel else ""
        is_admin = caller.is_platform_admin
        listed = panel and caller.source == "login"
    else:
        identity = await authenticate_panel(pool, headers)
        if identity is None:
            raise unauthenticated()
        user_id, username, is_admin = (
            identity.user_id,
            identity.username,
            identity.is_platform_admin,
        )
        listed = not identity.via_key
    resolved = None
    if caller is not None:
        resolved = {
            "organization": caller.org_slug,
            "product": headers.get("x-product", "").strip() or None,
            "can_read": caller.can_read,
            "can_write": caller.can_write,
            "can_admin": caller.can_admin,
        }
    return {
        "user_id": user_id,
        "username": username,
        "is_platform_admin": is_admin,
        "memberships": await _memberships(pool, user_id) if listed else [],
        "resolved": resolved,
    }
