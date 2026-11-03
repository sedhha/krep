import time
from typing import Any

import jwt
import pytest
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.api.errors import ApiError
from krep.identity import jwt as krep_jwt
from krep.identity.resolve import resolve_caller
from tests.identity.conftest import (
    LOGIN_ISSUER,
    Keys,
    Seed,
    b64url,
    login_claims,
    login_headers,
)

Pool = AsyncConnectionPool[AsyncConnection]
GENERIC = ("unauthenticated", "invalid or missing credentials")


async def rejected(pool: Pool, headers: dict[str, str]) -> None:
    with pytest.raises(ApiError) as exc:
        await resolve_caller(pool, headers)
    assert exc.value.status == 401
    assert (exc.value.error, exc.value.message) == GENERIC
    assert exc.value.extra == {}


async def test_v2ac1_valid_login_jwt_is_accepted(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.member(org, "u-1", ["writer"])
    caller = await resolve_caller(pool, login_headers(keys, "u-1", org.slug))
    assert caller.tenant_id == org.id
    assert caller.user_id == "u-1"
    assert caller.doc["token"] == {
        "sub": "u-1",
        "username": "name-u-1",
        "groups": ["writer"],
    }
    assert caller.org_slug == org.slug
    assert caller.source == "login"


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://other.example.com"},
        {"aud": "someone-else"},
        {"exp": int(time.time()) - 3600},
    ],
    ids=["wrong-issuer", "wrong-audience", "expired"],
)
async def test_v2ac1_bad_claims_return_the_generic_401(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed, overrides: dict[str, Any]
) -> None:
    org = await seed.org()
    await seed.member(org, "u-1", ["org-admin"])
    await rejected(pool, login_headers(keys, "u-1", org.slug, **overrides))


async def test_v2ac1_unknown_key_returns_the_generic_401(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.member(org, "u-1")
    forged = Keys("rogue").sign(login_claims("u-1"))
    await rejected(pool, {"authorization": f"Bearer {forged}", "x-org": org.slug})


async def test_v2ac1_alg_none_returns_the_generic_401(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.member(org, "u-1")
    token = f"{b64url({'alg': 'none', 'typ': 'JWT'})}.{b64url(login_claims('u-1'))}."
    await rejected(pool, {"authorization": f"Bearer {token}", "x-org": org.slug})


async def test_v2ac1_hs256_signed_with_the_public_key_is_rejected(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.member(org, "u-1")
    token = jwt.encode(
        login_claims("u-1"), "x" * 40, algorithm="HS256", headers={"kid": keys.kid}
    )
    await rejected(pool, {"authorization": f"Bearer {token}", "x-org": org.slug})


async def test_clock_skew_within_leeway_is_tolerated(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.member(org, "u-1")
    headers = login_headers(keys, "u-1", org.slug, exp=int(time.time()) - 10)
    assert (await resolve_caller(pool, headers)).user_id == "u-1"


async def test_jwks_fetch_failure_fails_closed(
    pool: Pool,
    keys: Keys,
    jwks: dict[str, Any],
    seed: Seed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    org = await seed.org()
    await seed.member(org, "u-1", ["org-admin"])

    async def down(uri: str) -> list[dict[str, Any]]:
        raise httpx.ConnectError("down")

    krep_jwt.clear_cache()
    monkeypatch.setattr(krep_jwt, "fetch_jwks", down)
    await rejected(pool, login_headers(keys, "u-1", org.slug))


async def test_groups_claim_in_the_jwt_cannot_inject_groups(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.member(org, "u-1", ["reader"])
    headers = login_headers(keys, "u-1", org.slug, groups=["org-admin"])
    caller = await resolve_caller(pool, headers)
    assert caller.doc["token"]["groups"] == ["reader"]
    assert (caller.can_read, caller.can_write, caller.can_admin) == (True, False, False)


async def test_missing_or_blank_sub_is_rejected(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    claims_without_sub = login_claims("x")
    del claims_without_sub["sub"]
    token = keys.sign(claims_without_sub)
    await rejected(pool, {"authorization": f"Bearer {token}", "x-org": org.slug})
    await rejected(pool, login_headers(keys, "", org.slug))


async def test_v2ac3_org_auth_config_cannot_verify_the_login_issuer(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    secret = "s" * 40
    await seed.hmac(org, secret, issuer=LOGIN_ISSUER)
    token = jwt.encode(
        {"iss": LOGIN_ISSUER, "sub": "attacker", "exp": int(time.time()) + 60},
        secret,
        algorithm="HS256",
    )
    await rejected(pool, {"authorization": f"Bearer {token}", "x-org": org.slug})
