import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import jwt as pyjwt
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from krep.api.errors import ApiError
from krep.db.tenant import tenant_transaction
from krep.identity.jwt import verify_token
from krep.identity.principal import decode_principal
from krep.policy.evaluate import evaluate

Pool = AsyncConnectionPool[AsyncConnection]
Resolved = tuple[UUID, str, dict[str, Any], dict[str, Any]]

ADMINS_POLICY = "registry-admins"
WRITERS_POLICY = "registry-writers"


@dataclass
class Caller:
    tenant_id: UUID
    user_id: str
    doc: dict[str, Any]
    can_write: bool
    can_admin: bool


def _unauthenticated() -> ApiError:
    return ApiError(401, "unauthenticated", "invalid or missing credentials")


def _dig(claims: Mapping[str, Any], path: list[str]) -> Any:
    current: Any = claims
    for segment in path:
        if not isinstance(current, dict):
            return None
        node = cast("dict[str, Any]", current)
        if segment not in node:
            return None
        current = node[segment]
    return current


def _bearer(headers: Mapping[str, str]) -> str | None:
    scheme, _, token = headers.get("authorization", "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token else None


async def _permissions(
    pool: Pool, tenant_id: UUID, doc: dict[str, Any]
) -> tuple[bool, bool]:
    async with tenant_transaction(pool, tenant_id) as conn:
        cursor = await conn.execute(
            "SELECT name, compiled_path::text FROM access_policies "
            "WHERE reserved AND name = ANY(%s)",
            ([ADMINS_POLICY, WRITERS_POLICY],),
        )
        paths = {name: path for name, path in await cursor.fetchall()}
        satisfied = {
            name: await evaluate(conn, path, doc, tenant_id) for name, path in paths.items()
        }
    can_admin = satisfied.get(ADMINS_POLICY, False)
    return can_admin or satisfied.get(WRITERS_POLICY, False), can_admin


async def _from_api_key(
    pool: Pool, key: str, principal_header: str | None
) -> Resolved:
    digest = hashlib.sha256(key.encode()).digest()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, tenant_id, allow_principal FROM api_keys "
            "WHERE key_hash = %s AND revoked_at IS NULL",
            (digest,),
        )
        row = await cur.fetchone()
    if row is None:
        raise _unauthenticated()
    principal = decode_principal(principal_header) if row["allow_principal"] else None
    user_id = principal["id"] if principal else f"apikey:{row['id']}"
    return row["tenant_id"], user_id, {"api_key_id": str(row["id"])}, principal or {}


async def _from_jwt(pool: Pool, token: str, principal_header: str | None) -> Resolved:
    try:
        issuer = pyjwt.decode(token, options={"verify_signature": False}).get("iss")
    except pyjwt.PyJWTError:
        raise _unauthenticated() from None
    if not isinstance(issuer, str):
        raise _unauthenticated()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT issuer, audience, jwks_uri, tenant_id, tenant_claim_path, user_claim_path, "
            "allow_principal, enabled FROM token_issuers WHERE issuer = %s",
            (issuer,),
        )
        row = await cur.fetchone()
    if row is None:
        raise _unauthenticated()
    claims = await verify_token(token, row)
    tenant_id = row["tenant_id"] or _tenant_from_claims(claims, row["tenant_claim_path"])
    machine = row["allow_principal"]
    principal = decode_principal(principal_header) if machine else None
    if principal:
        user_id = principal["id"]
    else:
        subject = _dig(claims, ["sub"] if machine else row["user_claim_path"])
        if not isinstance(subject, str) or not subject:
            raise _unauthenticated()
        user_id = f"client:{subject}" if machine else subject
    return tenant_id, user_id, claims, principal or {}


def _tenant_from_claims(claims: Mapping[str, Any], path: list[str]) -> UUID:
    value = _dig(claims, path)
    if not isinstance(value, str):
        raise _unauthenticated()
    try:
        return UUID(value)
    except ValueError:
        raise _unauthenticated() from None


async def resolve_caller(pool: Pool, headers: Mapping[str, str]) -> Caller:
    principal_header = headers.get("x-principal")
    api_key = headers.get("x-api-key")
    if api_key:
        tenant_id, user_id, token, principal = await _from_api_key(pool, api_key, principal_header)
    else:
        bearer = _bearer(headers)
        if bearer is None:
            raise _unauthenticated()
        tenant_id, user_id, token, principal = await _from_jwt(pool, bearer, principal_header)
    doc = {"token": token, "principal": principal}
    can_write, can_admin = await _permissions(pool, tenant_id, doc)
    return Caller(tenant_id, user_id, doc, can_write, can_admin)
