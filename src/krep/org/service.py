from collections.abc import Mapping
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection, errors

from krep.api.errors import ApiError
from krep.auth.store import save_config
from krep.org import audit
from krep.policy.compile import COMPILER_VERSION
from krep.policy.parser import parse
from krep.policy.store import write_policy

ADMIN_GROUP = "org-admin"
OPEN_POLICY = "open-to-all"
CAPABILITY_NAMES = ("registry-admins", "registry-writers", "registry-readers")
DEFAULT_CAPABILITY_RULES = {
    "registry-admins": '"org-admin" in token.groups',
    "registry-writers": '"org-admin" in token.groups || "writer" in token.groups',
    "registry-readers": '"org-admin" in token.groups || "writer" in token.groups || "reader" in token.groups',
}
ORGANIZATION_COLUMNS = "id, slug, name, status, is_platform, legal_hold, delete_after, created_by, created_at"
PRODUCT_COLUMNS = "id, slug, name, status, created_by, created_at"
AUTH_COLUMNS = (
    "id, product_id, adapter, config, key_id, rev, enabled, updated_by, updated_at"
)


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


async def scope(conn: AsyncConnection, tenant_id: UUID) -> None:
    await conn.execute(
        "SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),)
    )


def organization_view(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = (
        "id",
        "slug",
        "name",
        "status",
        "is_platform",
        "legal_hold",
        "delete_after",
        "created_by",
        "created_at",
    )
    return dict(zip(keys, row, strict=True))


async def find_user(conn: AsyncConnection, identifier: str) -> str | None:
    cur = await conn.execute(
        "SELECT id FROM auth_users WHERE username = %s OR email = %s "
        "ORDER BY (username = %s) DESC LIMIT 1",
        (identifier, identifier, identifier),
    )
    row = await cur.fetchone()
    return None if row is None else row[0]


async def lock_user(conn: AsyncConnection, user_id: str) -> None:
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (user_id,)
    )


async def user_exists(conn: AsyncConnection, user_id: str) -> bool:
    cur = await conn.execute("SELECT 1 FROM auth_users WHERE id = %s", (user_id,))
    return await cur.fetchone() is not None


async def init_capabilities(
    conn: AsyncConnection,
    tenant_id: UUID,
    asts: Mapping[str, dict[str, Any]],
    actor: str,
) -> None:
    await scope(conn, tenant_id)
    for name, ast in asts.items():
        cur = await conn.execute(
            "SELECT 1 FROM access_policies WHERE tenant_id = %s AND name = %s",
            (tenant_id, name),
        )
        if await cur.fetchone() is None:
            await write_policy(conn, tenant_id, name, ast, actor, reserved=True)


async def create_organization(
    conn: AsyncConnection,
    actor: str,
    slug: str,
    name: str,
    admin_user: str,
    capabilities: Mapping[str, dict[str, Any]] | None,
    auth: Mapping[str, Any] | None,
) -> dict[str, Any]:
    admin_id = await find_user(conn, admin_user)
    if admin_id is not None:
        await lock_user(conn, admin_id)
        if not await user_exists(conn, admin_id):
            admin_id = None
    if admin_id is None:
        raise ApiError(
            422, "admin_user_not_found", "admin_user must be an existing username"
        )
    try:
        cur = await conn.execute(
            f"INSERT INTO organizations (slug, name, created_by) VALUES (%s, %s, %s) "
            f"RETURNING {ORGANIZATION_COLUMNS}",
            (slug, name, actor),
        )
    except errors.UniqueViolation:
        raise ApiError(
            409, "slug_taken", "organisation slug is already in use"
        ) from None
    row = await cur.fetchone()
    assert row
    tenant_id: UUID = row[0]
    asts = {
        **{n: parse(rule) for n, rule in DEFAULT_CAPABILITY_RULES.items()},
        **(capabilities or {}),
    }
    await init_capabilities(conn, tenant_id, asts, actor)
    await conn.execute(
        "INSERT INTO access_policies (tenant_id, name, ast, source, compiled_path, "
        "compiler_version, reserved, kind, created_by, updated_by) "
        "VALUES (%s, %s, '{}'::jsonb, 'true', 'true'::jsonpath, %s, true, 'open', %s, %s)",
        (tenant_id, OPEN_POLICY, COMPILER_VERSION, actor, actor),
    )
    await conn.execute(
        "INSERT INTO memberships (user_id, tenant_id, groups, created_by) VALUES (%s, %s, %s, %s)",
        (admin_id, tenant_id, [ADMIN_GROUP], actor),
    )
    if auth is not None:
        await save_config(
            conn,
            tenant_id,
            None,
            auth["adapter"],
            auth.get("config") or {},
            auth.get("secret"),
            actor,
        )
    await audit.record(
        conn,
        actor,
        "org.create",
        tenant_id,
        slug,
        {
            "admin_user_id": admin_id,
            "auth_adapter": None if auth is None else auth["adapter"],
        },
    )
    return organization_view(row)


async def get_organization(conn: AsyncConnection, org_id: UUID) -> dict[str, Any]:
    cur = await conn.execute(
        f"SELECT {ORGANIZATION_COLUMNS} FROM organizations WHERE id = %s", (org_id,)
    )
    row = await cur.fetchone()
    if row is None:
        raise not_found("organization")
    return organization_view(row)


async def list_organizations(conn: AsyncConnection) -> list[dict[str, Any]]:
    cur = await conn.execute(
        f"SELECT {ORGANIZATION_COLUMNS} FROM organizations ORDER BY slug"
    )
    return [organization_view(row) for row in await cur.fetchall()]


async def list_products(conn: AsyncConnection, tenant_id: UUID) -> list[dict[str, Any]]:
    cur = await conn.execute(
        f"SELECT {PRODUCT_COLUMNS} FROM products WHERE tenant_id = %s ORDER BY slug",
        (tenant_id,),
    )
    return [_product(row) for row in await cur.fetchall()]


def _product(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = ("id", "slug", "name", "status", "created_by", "created_at")
    return dict(zip(keys, row, strict=True))


async def require_product(
    conn: AsyncConnection, tenant_id: UUID, product_id: UUID
) -> dict[str, Any]:
    cur = await conn.execute(
        f"SELECT {PRODUCT_COLUMNS} FROM products WHERE tenant_id = %s AND id = %s FOR UPDATE",
        (tenant_id, product_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise not_found("product")
    return _product(row)


async def create_product(
    conn: AsyncConnection, tenant_id: UUID, slug: str, name: str, actor: str
) -> dict[str, Any]:
    try:
        cur = await conn.execute(
            f"INSERT INTO products (tenant_id, slug, name, created_by) VALUES (%s, %s, %s, %s) "
            f"RETURNING {PRODUCT_COLUMNS}",
            (tenant_id, slug, name, actor),
        )
    except errors.UniqueViolation:
        raise ApiError(409, "slug_taken", "product slug is already in use") from None
    row = await cur.fetchone()
    assert row
    return _product(row)


async def update_product(
    conn: AsyncConnection,
    tenant_id: UUID,
    product_id: UUID,
    name: str | None,
    status: str | None,
) -> dict[str, Any]:
    current = await require_product(conn, tenant_id, product_id)
    if status == "archived" and current["status"] != "archived":
        cur = await conn.execute(
            "SELECT 1 FROM registry WHERE tenant_id = %s AND product_id = %s LIMIT 1",
            (tenant_id, product_id),
        )
        if await cur.fetchone() is not None:
            raise ApiError(409, "product_not_empty", "product still has resources")
    cur = await conn.execute(
        f"UPDATE products SET name = coalesce(%s, name), status = coalesce(%s, status) "
        f"WHERE tenant_id = %s AND id = %s RETURNING {PRODUCT_COLUMNS}",
        (name, status, tenant_id, product_id),
    )
    row = await cur.fetchone()
    assert row
    return _product(row)


def _auth_view(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = (
        "id",
        "product_id",
        "adapter",
        "config",
        "key_id",
        "rev",
        "enabled",
        "updated_by",
        "updated_at",
    )
    view: dict[str, Any] = dict(zip(keys, row, strict=True))
    view["secret_set"] = view["key_id"] is not None
    return view


async def get_auth(
    conn: AsyncConnection, tenant_id: UUID, product_id: UUID | None
) -> dict[str, Any]:
    cur = await conn.execute(
        f"SELECT {AUTH_COLUMNS} FROM auth_configs "
        "WHERE tenant_id = %s AND product_id IS NOT DISTINCT FROM %s",
        (tenant_id, product_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise not_found("auth config")
    return _auth_view(row)


async def get_effective_auth(
    conn: AsyncConnection, tenant_id: UUID, product_id: UUID
) -> dict[str, Any]:
    cur = await conn.execute(
        f"SELECT {AUTH_COLUMNS} FROM auth_configs WHERE tenant_id = %s "
        "AND (product_id IS NULL OR product_id = %s) ORDER BY product_id NULLS LAST LIMIT 1",
        (tenant_id, product_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise not_found("auth config")
    view = _auth_view(row)
    view["source"] = "organization" if view["product_id"] is None else "product"
    return view


async def put_auth(
    conn: AsyncConnection,
    tenant_id: UUID,
    product_id: UUID | None,
    adapter: str,
    config: Mapping[str, Any],
    secret: str | None,
    actor: str,
) -> dict[str, Any]:
    await save_config(conn, tenant_id, product_id, adapter, config, secret, actor)
    return await get_auth(conn, tenant_id, product_id)


async def delete_auth(
    conn: AsyncConnection, tenant_id: UUID, product_id: UUID | None
) -> None:
    cur = await conn.execute(
        "DELETE FROM auth_configs WHERE tenant_id = %s AND product_id IS NOT DISTINCT FROM %s",
        (tenant_id, product_id),
    )
    if cur.rowcount == 0:
        raise not_found("auth config")


async def list_members(conn: AsyncConnection, tenant_id: UUID) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "SELECT m.user_id, m.groups, m.created_at, u.username, u.email "
        "FROM memberships m LEFT JOIN auth_users u ON u.id = m.user_id "
        "WHERE m.tenant_id = %s ORDER BY u.username, m.user_id",
        (tenant_id,),
    )
    return [
        {
            "user_id": user_id,
            "groups": list(groups),
            "created_at": created_at,
            "username": username,
            "email": email,
        }
        for user_id, groups, created_at, username, email in await cur.fetchall()
    ]


async def add_member(
    conn: AsyncConnection,
    tenant_id: UUID,
    user_id: str,
    groups: list[str],
    actor: str,
) -> dict[str, Any]:
    await lock_user(conn, user_id)
    if not await user_exists(conn, user_id):
        raise not_found("user")
    try:
        await conn.execute(
            "INSERT INTO memberships (user_id, tenant_id, groups, created_by) VALUES (%s, %s, %s, %s)",
            (user_id, tenant_id, groups, actor),
        )
    except errors.UniqueViolation:
        raise ApiError(409, "already_member", "user is already a member") from None
    return {"user_id": user_id, "groups": groups}


async def upsert_member(
    conn: AsyncConnection,
    tenant_id: UUID,
    user_id: str,
    groups: list[str],
    actor: str,
) -> dict[str, Any]:
    await lock_user(conn, user_id)
    if not await user_exists(conn, user_id):
        raise not_found("user")
    await conn.execute(
        "INSERT INTO memberships (user_id, tenant_id, groups, created_by) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (user_id, tenant_id) DO UPDATE SET groups = EXCLUDED.groups",
        (user_id, tenant_id, groups, actor),
    )
    return {"user_id": user_id, "groups": groups}


async def _guard_last_admin(
    conn: AsyncConnection,
    tenant_id: UUID,
    user_id: str,
    new_groups: list[str],
    bypass: bool,
) -> list[str]:
    cur = await conn.execute(
        "SELECT user_id, groups FROM memberships WHERE tenant_id = %s "
        "AND (user_id = %s OR %s = ANY(groups)) FOR UPDATE",
        (tenant_id, user_id, ADMIN_GROUP),
    )
    rows = {uid: list(groups) for uid, groups in await cur.fetchall()}
    if user_id not in rows:
        raise not_found("member")
    others = [
        uid for uid, groups in rows.items() if uid != user_id and ADMIN_GROUP in groups
    ]
    if (
        not bypass
        and ADMIN_GROUP in rows[user_id]
        and ADMIN_GROUP not in new_groups
        and not others
    ):
        raise ApiError(
            409, "last_admin", "the last organisation admin cannot be removed"
        )
    return rows[user_id]


async def update_member(
    conn: AsyncConnection,
    tenant_id: UUID,
    user_id: str,
    groups: list[str],
    bypass_last_admin: bool,
) -> dict[str, Any]:
    await _guard_last_admin(conn, tenant_id, user_id, groups, bypass_last_admin)
    await conn.execute(
        "UPDATE memberships SET groups = %s WHERE tenant_id = %s AND user_id = %s",
        (groups, tenant_id, user_id),
    )
    return {"user_id": user_id, "groups": groups}


async def remove_member(
    conn: AsyncConnection, tenant_id: UUID, user_id: str, bypass_last_admin: bool
) -> None:
    await _guard_last_admin(conn, tenant_id, user_id, [], bypass_last_admin)
    await conn.execute(
        "DELETE FROM memberships WHERE tenant_id = %s AND user_id = %s",
        (tenant_id, user_id),
    )


async def write_capabilities(
    conn: AsyncConnection,
    tenant_id: UUID,
    asts: Mapping[str, dict[str, Any]],
    actor: str,
) -> list[dict[str, Any]]:
    await scope(conn, tenant_id)
    written: list[dict[str, Any]] = []
    for name, ast in asts.items():
        row = await write_policy(conn, tenant_id, name, ast, actor, reserved=True)
        written.append({"name": name, "rev": row.rev, "source": row.source})
    return written
