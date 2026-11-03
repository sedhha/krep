from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import jwt as pyjwt
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.api.errors import ApiError
from krep.config import get_settings
from krep.identity.jwt import verify_token
from krep.identity.platform import PLATFORM_USER, is_platform_admin, key_matches

Pool = AsyncConnectionPool[AsyncConnection]
LEEWAY_SECONDS = 30


@dataclass(frozen=True)
class PanelIdentity:
    user_id: str
    username: str
    is_platform_admin: bool
    via_key: bool = False


def unauthenticated() -> ApiError:
    return ApiError(401, "unauthenticated", "invalid or missing credentials")


def bearer_token(headers: Mapping[str, str]) -> str | None:
    scheme, _, token = headers.get("authorization", "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token else None


def is_login_token(token: str) -> bool:
    issuer = get_settings().login_issuer
    if not issuer:
        return False
    try:
        return (
            pyjwt.decode(token, options={"verify_signature": False}).get("iss")
            == issuer
        )
    except pyjwt.PyJWTError:
        return False


async def verify_login_jwt(token: str) -> dict[str, Any]:
    settings = get_settings()
    if not (
        settings.login_issuer and settings.login_jwks_url and settings.login_audience
    ):
        raise unauthenticated()
    claims = await verify_token(
        token,
        {
            "issuer": settings.login_issuer,
            "audience": settings.login_audience,
            "jwks_uri": settings.login_jwks_url,
            "enabled": True,
        },
        allow_insecure_uri=settings.env == "local",
        leeway=LEEWAY_SECONDS,
    )
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise unauthenticated()
    return claims


async def _is_disabled(pool: Pool, user_id: str) -> bool:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM disabled_users WHERE user_id = %s", (user_id,)
        )
        return await cur.fetchone() is not None


async def authenticate_panel(
    pool: Pool, headers: Mapping[str, str]
) -> PanelIdentity | None:
    if "x-platform-key" in headers:
        if not key_matches(headers["x-platform-key"]):
            raise unauthenticated()
        return PanelIdentity(PLATFORM_USER, PLATFORM_USER, True, via_key=True)
    token = bearer_token(headers)
    if token is None or not is_login_token(token):
        return None
    claims = await verify_login_jwt(token)
    user_id: str = claims["sub"]
    if await _is_disabled(pool, user_id):
        raise unauthenticated()
    username = claims.get("username")
    return PanelIdentity(
        user_id,
        username if isinstance(username, str) else "",
        await is_platform_admin(pool, user_id),
    )


def evaluation_token(identity: PanelIdentity, groups: list[str]) -> dict[str, Any]:
    return {"sub": identity.user_id, "username": identity.username, "groups": groups}


async def load_groups(
    conn: AsyncConnection, tenant_id: Any, user_id: str
) -> list[str] | None:
    cur = await conn.execute(
        "SELECT groups FROM memberships WHERE tenant_id = %s AND user_id = %s",
        (tenant_id, user_id),
    )
    row = await cur.fetchone()
    return None if row is None else list(row[0])
