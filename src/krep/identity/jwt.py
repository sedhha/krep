import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from krep.api.errors import ApiError

ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"]
JWKS_TTL_SECONDS = 600.0
MIN_REFETCH_SECONDS = 15.0
FETCH_TIMEOUT_SECONDS = 5.0


@dataclass
class _Entry:
    keys: dict[str | None, jwt.PyJWK]
    fetched_at: float


_cache: dict[str, _Entry] = {}


def clear_cache() -> None:
    _cache.clear()


def _unauthenticated() -> ApiError:
    return ApiError(401, "unauthenticated", "invalid or missing credentials")


async def fetch_jwks(uri: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = await client.get(uri)
        response.raise_for_status()
        return response.json()["keys"]


async def _refresh(uri: str) -> _Entry:
    keys: dict[str | None, jwt.PyJWK] = {}
    for jwk in await fetch_jwks(uri):
        try:
            keys[jwk.get("kid")] = jwt.PyJWK.from_dict(jwk)
        except jwt.PyJWTError:
            continue
    entry = _Entry(keys, time.monotonic())
    _cache[uri] = entry
    return entry


async def _signing_key(uri: str, kid: str | None) -> jwt.PyJWK:
    entry = _cache.get(uri)
    if entry is None or time.monotonic() - entry.fetched_at > JWKS_TTL_SECONDS:
        entry = await _refresh(uri)
    key = _lookup(entry, kid)
    if key is None and time.monotonic() - entry.fetched_at >= MIN_REFETCH_SECONDS:
        key = _lookup(await _refresh(uri), kid)
    if key is None:
        raise _unauthenticated()
    return key


def _lookup(entry: _Entry, kid: str | None) -> jwt.PyJWK | None:
    if kid is None:
        return next(iter(entry.keys.values())) if len(entry.keys) == 1 else None
    return entry.keys.get(kid)


async def verify_token(token: str, issuer_row: Mapping[str, Any]) -> dict[str, Any]:
    uri: str = issuer_row["jwks_uri"]
    if not issuer_row["enabled"] or not uri.startswith("https://"):
        raise _unauthenticated()
    try:
        header = jwt.get_unverified_header(token)
        key = await _signing_key(uri, header.get("kid"))
        return jwt.decode(
            token,
            key.key,
            algorithms=ALGORITHMS,
            audience=issuer_row["audience"],
            issuer=issuer_row["issuer"],
            options={"require": ["exp", "iss", "aud"]},
        )
    except (jwt.PyJWTError, httpx.HTTPError, OSError, ValueError, KeyError):
        raise _unauthenticated() from None
