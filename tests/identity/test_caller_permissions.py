import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.api.deps import db, get_caller, require_admin, require_write
from krep.api.errors import install_error_handlers
from krep.identity.resolve import Caller, resolve_caller
from tests.identity.conftest import Keys, claims

Pool = AsyncConnectionPool[AsyncConnection]
AddIssuer = Callable[..., Awaitable[dict[str, Any]]]
AddPolicy = Callable[..., Awaitable[None]]

ADMIN_RULE = 'token.groups == "grc-admins"'
WRITER_RULE = 'token.groups == "grc-editors"'


def build_app(pool: Pool) -> FastAPI:
    app = FastAPI()
    app.state.pool = pool
    install_error_handlers(app)

    @app.get("/me")
    async def me(caller: Annotated[Caller, Depends(get_caller)]) -> dict[str, Any]:
        return {
            "tenant_id": str(caller.tenant_id),
            "user_id": caller.user_id,
            "can_write": caller.can_write,
            "can_admin": caller.can_admin,
        }

    @app.get("/write", dependencies=[Depends(require_write)])
    async def write() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/admin", dependencies=[Depends(require_admin)])
    async def admin() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/db")
    async def tenant_setting(conn: Annotated[AsyncConnection, Depends(db)]) -> dict[str, str]:
        cur = await conn.execute("SELECT current_setting('app.tenant_id')")
        row = await cur.fetchone()
        assert row is not None
        return {"tenant": row[0]}

    return app


@pytest_asyncio.fixture
async def client(pool: Pool) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(pool)), base_url="http://t"
    ) as c:
        yield c


class Tenant:
    def __init__(self, keys: Keys, issuer: dict[str, Any]) -> None:
        self.keys = keys
        self.issuer = issuer
        self.id: uuid.UUID = issuer["tenant_id"]

    def headers(self, **extra: Any) -> dict[str, str]:
        token = self.keys.sign(
            claims(iss=self.issuer["issuer"], aud=self.issuer["audience"], **extra)
        )
        return {"authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def tenant(keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer) -> Tenant:
    return Tenant(keys, await add_issuer())


async def test_ac4_without_reserved_policies_nobody_writes_or_administers(
    client: httpx.AsyncClient, tenant: Tenant
) -> None:
    headers = tenant.headers(groups="grc-admins")
    me = (await client.get("/me", headers=headers)).json()
    assert (me["can_write"], me["can_admin"]) == (False, False)
    assert (await client.get("/write", headers=headers)).status_code == 403
    assert (await client.get("/admin", headers=headers)).status_code == 403


async def test_ac4_rules_grant_exactly_the_described_callers(
    client: httpx.AsyncClient, tenant: Tenant, add_policy: AddPolicy
) -> None:
    await add_policy(tenant.id, "registry-admins", ADMIN_RULE)
    await add_policy(tenant.id, "registry-writers", WRITER_RULE)

    async def flags(**claims_: Any) -> tuple[bool, bool]:
        me = (await client.get("/me", headers=tenant.headers(**claims_))).json()
        return me["can_write"], me["can_admin"]

    assert await flags(groups="grc-admins") == (True, True)
    assert await flags(groups="grc-editors") == (True, False)
    assert await flags(groups="viewers") == (False, False)
    assert await flags() == (False, False)


async def test_ac4_admin_can_write_without_matching_writers_rule(
    client: httpx.AsyncClient, tenant: Tenant, add_policy: AddPolicy
) -> None:
    await add_policy(tenant.id, "registry-admins", ADMIN_RULE)
    headers = tenant.headers(groups="grc-admins")
    assert (await client.get("/write", headers=headers)).status_code == 200
    assert (await client.get("/admin", headers=headers)).status_code == 200


async def test_writer_is_forbidden_on_admin_with_error_shape(
    client: httpx.AsyncClient, tenant: Tenant, add_policy: AddPolicy
) -> None:
    await add_policy(tenant.id, "registry-writers", WRITER_RULE)
    headers = tenant.headers(groups="grc-editors")
    assert (await client.get("/write", headers=headers)).status_code == 200
    denied = await client.get("/admin", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"] == "forbidden"


async def test_policy_of_another_tenant_grants_nothing(
    client: httpx.AsyncClient, tenant: Tenant, add_policy: AddPolicy
) -> None:
    await add_policy(uuid.uuid4(), "registry-admins", 'token.sub == "u42"')
    me = (await client.get("/me", headers=tenant.headers())).json()
    assert (me["can_write"], me["can_admin"]) == (False, False)


async def test_non_reserved_policy_with_reserved_name_is_not_trusted(
    pool: Pool, tenant: Tenant, jwks: dict[str, Any]
) -> None:
    from psycopg.types.json import Jsonb

    from krep.db.tenant import tenant_transaction
    from krep.policy.compile import COMPILER_VERSION, compile_ast
    from krep.policy.parser import parse

    ast = parse('token.sub == "u42"')
    async with tenant_transaction(pool, tenant.id) as conn:
        await conn.execute(
            "INSERT INTO access_policies (tenant_id, name, ast, source, compiled_path, "
            "compiler_version, reserved, created_by, updated_by) "
            "VALUES (%s, 'registry-admins', %s, 'x', %s::jsonpath, %s, false, 'u', 'u')",
            (tenant.id, Jsonb(ast), compile_ast(ast), COMPILER_VERSION),
        )
    caller = await resolve_caller(pool, tenant.headers())
    assert (caller.can_write, caller.can_admin) == (False, False)


async def test_api_key_caller_is_evaluated_against_principal(
    pool: Pool,
    client: httpx.AsyncClient,
    add_api_key: Callable[..., Awaitable[tuple[str, uuid.UUID, uuid.UUID]]],
    add_policy: AddPolicy,
) -> None:
    from tests.identity.conftest import b64url

    key, _, tenant_id = await add_api_key(allow_principal=True)
    await add_policy(tenant_id, "registry-writers", '"support" in principal.roles')
    allowed = {"x-api-key": key, "x-principal": b64url({"id": "u1", "roles": ["support"]})}
    denied = {"x-api-key": key, "x-principal": b64url({"id": "u2", "roles": ["other"]})}
    assert (await client.get("/write", headers=allowed)).status_code == 200
    assert (await client.get("/write", headers=denied)).status_code == 403


async def test_unauthenticated_request_is_401(client: httpx.AsyncClient) -> None:
    r = await client.get("/me")
    assert r.status_code == 401
    assert r.json()["error"] == "unauthenticated"


async def test_db_dependency_opens_tenant_transaction_for_caller(
    client: httpx.AsyncClient, tenant: Tenant
) -> None:
    r = await client.get("/db", headers=tenant.headers())
    assert r.json() == {"tenant": str(tenant.id)}


@pytest.mark.parametrize("path", ["/write", "/admin", "/db"])
async def test_guarded_routes_require_authentication(
    client: httpx.AsyncClient, path: str
) -> None:
    assert (await client.get(path)).status_code == 401
