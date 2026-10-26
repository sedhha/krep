import base64
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, LiteralString

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.config import Settings
from krep.db.pool import open_pool
from krep.db.tenant import tenant_transaction
from krep.identity import jwt as krep_jwt
from krep.policy.ast import to_source
from krep.policy.compile import COMPILER_VERSION, compile_ast
from krep.policy.parser import parse
from tests.conftest import role_url

ISSUER = "https://idp.example.com/"
AUDIENCE = "krep-api"
JWKS_URI = "https://idp.example.com/.well-known/jwks.json"


class Keys:
    def __init__(self, kid: str) -> None:
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(self.private.public_key()))
        self.jwk: dict[str, Any] = {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}

    def sign(self, claims: dict[str, Any], alg: str = "RS256", kid: str | None = None) -> str:
        return jwt.encode(
            claims, self.private, algorithm=alg, headers={"kid": kid or self.kid}
        )


@pytest.fixture(scope="session")
def keys() -> Keys:
    return Keys("k1")


@pytest.fixture
def jwks(monkeypatch: pytest.MonkeyPatch, keys: Keys) -> dict[str, Any]:
    state: dict[str, Any] = {"keys": [keys.jwk], "fetches": 0}

    async def fake_fetch(uri: str) -> list[dict[str, Any]]:
        state["fetches"] += 1
        return state["keys"]

    krep_jwt.clear_cache()
    monkeypatch.setattr(krep_jwt, "fetch_jwks", fake_fetch)
    monkeypatch.setattr(krep_jwt, "MIN_REFETCH_SECONDS", 0)
    return state


def issuer_row(**overrides: Any) -> dict[str, Any]:
    return {
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "jwks_uri": JWKS_URI,
        "tenant_id": uuid.uuid4(),
        "tenant_claim_path": None,
        "user_claim_path": ["sub"],
        "allow_principal": False,
        "enabled": True,
        **overrides,
    }


def claims(**overrides: Any) -> dict[str, Any]:
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "u42",
        "exp": int(time.time()) + 600,
        **overrides,
    }


def b64url(value: Any) -> str:
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest_asyncio.fixture
async def pool(migrated_db: str) -> AsyncIterator[AsyncConnectionPool[AsyncConnection]]:
    settings = Settings(database_url=role_url("krep_app", migrated_db), migration_database_url="")
    async with await open_pool(settings, min_size=1, max_size=2) as pool:
        yield pool


@pytest_asyncio.fixture
async def owner_exec(migrated_db: str) -> AsyncIterator[Callable[..., Awaitable[None]]]:
    async with await AsyncConnection.connect(
        role_url("krep_owner", migrated_db), autocommit=True
    ) as conn:

        async def run(query: LiteralString, params: tuple[Any, ...] = ()) -> None:
            await conn.execute(query, params)

        yield run


@pytest.fixture
def add_issuer(
    owner_exec: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def add(**overrides: Any) -> dict[str, Any]:
        row = issuer_row(issuer=f"https://{uuid.uuid4().hex}.example.com/", **overrides)
        await owner_exec(
            "INSERT INTO token_issuers (issuer, audience, jwks_uri, tenant_id, tenant_claim_path, "
            "user_claim_path, allow_principal, enabled) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                row["issuer"], row["audience"], row["jwks_uri"], row["tenant_id"],
                row["tenant_claim_path"], row["user_claim_path"], row["allow_principal"],
                row["enabled"],
            ),
        )
        return row

    return add


@pytest.fixture
def add_api_key(
    owner_exec: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[tuple[str, uuid.UUID, uuid.UUID]]]:
    import hashlib

    async def add(
        tenant_id: uuid.UUID | None = None, allow_principal: bool = False, revoked: bool = False
    ) -> tuple[str, uuid.UUID, uuid.UUID]:
        tenant = tenant_id or uuid.uuid4()
        key_id = uuid.uuid4()
        key = uuid.uuid4().hex + uuid.uuid4().hex
        await owner_exec(
            "INSERT INTO api_keys (id, tenant_id, name, key_hash, allow_principal, revoked_at) "
            "VALUES (%s, %s, 'k', %s, %s, CASE WHEN %s THEN now() END)",
            (key_id, tenant, hashlib.sha256(key.encode()).digest(), allow_principal, revoked),
        )
        return key, key_id, tenant

    return add


@pytest.fixture
def add_policy(pool: AsyncConnectionPool[AsyncConnection]) -> Callable[..., Awaitable[None]]:
    async def add(tenant_id: uuid.UUID, name: str, rule: str) -> None:
        ast = parse(rule)
        from psycopg.types.json import Jsonb

        async with tenant_transaction(pool, tenant_id) as conn:
            await conn.execute(
                "INSERT INTO access_policies (tenant_id, name, ast, source, compiled_path, "
                "compiler_version, reserved, created_by, updated_by) "
                "VALUES (%s, %s, %s, %s, %s::jsonpath, %s, true, 'ops', 'ops')",
                (tenant_id, name, Jsonb(ast), to_source(ast), compile_ast(ast), COMPILER_VERSION),
            )

    return add
