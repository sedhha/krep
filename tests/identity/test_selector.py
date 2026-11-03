import time
import uuid
from typing import Any

import jwt
import pytest
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.api.errors import ApiError
from krep.identity.resolve import Caller, resolve_caller
from krep.registry.resources import can_read
from tests.identity.conftest import Keys, Seed, b64url, login_headers

Pool = AsyncConnectionPool[AsyncConnection]
SECRET = "o" * 40
OTHER_SECRET = "p" * 40


def org_token(secret: str = SECRET, alg: str = "HS256", **overrides: Any) -> str:
    return jwt.encode(
        {"sub": "svc", "exp": int(time.time()) + 60, **overrides}, secret, algorithm=alg
    )


def bearer(token: str, org: str, product: str | None = None) -> dict[str, str]:
    headers = {"authorization": f"Bearer {token}", "x-org": org}
    if product is not None:
        headers["x-product"] = product
    return headers


async def failure(pool: Pool, headers: dict[str, str]) -> ApiError:
    with pytest.raises(ApiError) as exc:
        await resolve_caller(pool, headers)
    assert exc.value.status == 401
    return exc.value


async def test_v2ac2_user_in_two_orgs_selects_either(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    a, b = await seed.org(), await seed.org()
    await seed.member(a, "u-1", ["org-admin"])
    await seed.member(b, "u-1", ["reader"])
    in_a = await resolve_caller(pool, login_headers(keys, "u-1", a.slug))
    in_b = await resolve_caller(pool, login_headers(keys, "u-1", b.slug))
    assert (in_a.tenant_id, in_a.can_admin) == (a.id, True)
    assert (in_b.tenant_id, in_b.can_admin, in_b.can_read) == (b.id, False, True)


async def test_v2ac2_no_membership_is_401(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    a, b = await seed.org(), await seed.org()
    await seed.member(a, "u-1", ["org-admin"])
    await failure(pool, login_headers(keys, "u-1", b.slug))


async def test_v2ac2_group_change_and_membership_removal_apply_next_request(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    headers = login_headers(keys, "u-1", org.slug)
    await seed.member(org, "u-1", ["reader"])
    assert (await resolve_caller(pool, headers)).can_write is False
    await seed.member(org, "u-1", ["writer"])
    assert (await resolve_caller(pool, headers)).can_write is True
    await seed.unmember(org, "u-1")
    await failure(pool, headers)


async def test_v2ac2_disabled_user_is_blocked_despite_valid_jwt(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.member(org, "u-1", ["org-admin"])
    headers = login_headers(keys, "u-1", org.slug)
    assert (await resolve_caller(pool, headers)).user_id == "u-1"
    await seed.disable("u-1")
    await failure(pool, headers)


async def test_v2ac3_org_hmac_token_works(pool: Pool, seed: Seed) -> None:
    org = await seed.org()
    await seed.hmac(org, SECRET, audience="krep", issuer="https://acme.example.com")
    token = org_token(
        aud="krep", iss="https://acme.example.com", groups=["org-admin"], sub="svc-1"
    )
    caller = await resolve_caller(pool, bearer(token, org.slug))
    assert caller.tenant_id == org.id
    assert caller.user_id == "svc-1"
    assert caller.doc["token"]["groups"] == ["org-admin"]
    assert (caller.can_admin, caller.is_platform_admin, caller.source) == (
        True,
        False,
        "org_token",
    )


async def test_v2ac3_hmac_failures_are_identical_401s(pool: Pool, seed: Seed) -> None:
    org = await seed.org()
    suspended = await seed.org(status="suspended")
    await seed.hmac(
        org,
        SECRET,
        audience="krep",
        issuer="https://acme.example.com",
        algorithms=["HS256"],
    )
    await seed.hmac(suspended, SECRET)
    good: dict[str, Any] = {"aud": "krep", "iss": "https://acme.example.com"}
    none_token = f"{b64url({'alg': 'none'})}.{b64url({**good, 'sub': 'x', 'exp': int(time.time()) + 60})}."
    cases = [
        bearer(org_token(OTHER_SECRET, **good), org.slug),
        bearer(org_token(**{**good, "exp": int(time.time()) - 3600}), org.slug),
        bearer(none_token, org.slug),
        bearer(org_token(alg="HS512", **good), org.slug),
        bearer(org_token(**{**good, "aud": "other"}), org.slug),
        bearer(org_token(**{**good, "iss": "https://evil.example.com"}), org.slug),
        bearer(org_token(**good), "no-such-org"),
        bearer(org_token(), suspended.slug),
        bearer(org_token(**good), org.slug, "no-such-product"),
    ]
    bodies = set()
    for headers in cases:
        exc = await failure(pool, headers)
        bodies.add((exc.error, exc.message, tuple(exc.extra)))
    assert bodies == {("unauthenticated", "invalid or missing credentials", ())}


async def test_v2ac3_pending_delete_org_is_401(pool: Pool, seed: Seed) -> None:
    org = await seed.org(status="pending_delete")
    await seed.hmac(org, SECRET)
    await failure(pool, bearer(org_token(), org.slug))


async def test_org_without_auth_config_rejects_org_tokens(
    pool: Pool, seed: Seed
) -> None:
    org = await seed.org()
    await failure(pool, bearer(org_token(), org.slug))


async def test_v2ac4_no_product_header_is_organisation_level(
    pool: Pool, seed: Seed
) -> None:
    org = await seed.org()
    product = await seed.product(org)
    await seed.hmac(org, SECRET)
    org_level = await resolve_caller(pool, bearer(org_token(), org.slug))
    in_product = await resolve_caller(pool, bearer(org_token(), org.slug, "prod-one"))
    assert org_level.product_id is None
    assert in_product.product_id == product


async def test_v2ac4_blank_product_header_is_organisation_level(
    pool: Pool, seed: Seed
) -> None:
    org = await seed.org()
    await seed.hmac(org, SECRET)
    caller = await resolve_caller(pool, bearer(org_token(), org.slug, "  "))
    assert caller.product_id is None


async def test_v2ac4_product_override_uses_only_the_product_secret(
    pool: Pool, seed: Seed
) -> None:
    org = await seed.org()
    overridden = await seed.product(org, "overridden")
    await seed.product(org, "plain")
    await seed.hmac(org, SECRET)
    await seed.hmac(org, OTHER_SECRET, product=overridden)
    assert (
        await resolve_caller(
            pool, bearer(org_token(OTHER_SECRET), org.slug, "overridden")
        )
    ).product_id == overridden
    await failure(pool, bearer(org_token(SECRET), org.slug, "overridden"))
    assert (
        await resolve_caller(pool, bearer(org_token(SECRET), org.slug, "plain"))
    ).tenant_id == org.id
    await failure(pool, bearer(org_token(OTHER_SECRET), org.slug, "plain"))
    await failure(pool, bearer(org_token(OTHER_SECRET), org.slug))


async def test_archived_product_is_unknown(pool: Pool, seed: Seed) -> None:
    org = await seed.org()
    await seed.product(org, "old", status="archived")
    await seed.hmac(org, SECRET)
    await failure(pool, bearer(org_token(), org.slug, "old"))


async def test_login_user_selects_a_product(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    product = await seed.product(org)
    await seed.member(org, "u-1", ["reader"])
    caller = await resolve_caller(
        pool, login_headers(keys, "u-1", org.slug, "prod-one")
    )
    assert caller.product_id == product
    await failure(pool, login_headers(keys, "u-1", org.slug, "missing"))


async def test_header_names_are_case_insensitive(pool: Pool, seed: Seed) -> None:
    org = await seed.org()
    await seed.hmac(org, SECRET)
    headers = {"Authorization": f"Bearer {org_token()}", "X-Org": org.slug}
    assert (await resolve_caller(pool, headers)).tenant_id == org.id


async def test_selector_mode_requires_a_credential_and_ignores_api_keys(
    pool: Pool, seed: Seed, add_api_key: Any
) -> None:
    org = await seed.org()
    await failure(pool, {"x-org": org.slug})
    await failure(pool, {"x-org": ""})
    key, _, _ = await add_api_key(tenant_id=org.id)
    await failure(pool, {"x-org": org.slug, "x-api-key": key})


async def test_org_slug_is_matched_exactly(pool: Pool, seed: Seed) -> None:
    org = await seed.org()
    await seed.hmac(org, SECRET)
    await failure(pool, bearer(org_token(), org.slug.upper()))
    await failure(pool, bearer(org_token(), f"{org.slug}%"))


async def test_tenant_comes_from_the_organisation_not_the_token(
    pool: Pool, seed: Seed
) -> None:
    org, other = await seed.org(), await seed.org()
    await seed.hmac(org, SECRET)
    token = org_token(tenant_id=str(other.id), tid=str(other.id))
    assert (await resolve_caller(pool, bearer(token, org.slug))).tenant_id == org.id


async def test_capabilities_readers_writers_admins(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    for user, groups in {
        "r": ["reader"],
        "w": ["writer"],
        "a": ["org-admin"],
        "none": ["other"],
    }.items():
        await seed.member(org, user, groups)

    async def flags(user: str) -> tuple[bool, bool, bool]:
        c = await resolve_caller(pool, login_headers(keys, user, org.slug))
        return c.can_read, c.can_write, c.can_admin

    assert await flags("r") == (True, False, False)
    assert await flags("w") == (True, True, False)
    assert await flags("a") == (True, True, True)
    assert await flags("none") == (False, False, False)


async def test_missing_capability_policies_fail_closed(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org(rules={})
    await seed.member(org, "u-1", ["org-admin", "writer", "reader"])
    caller = await resolve_caller(pool, login_headers(keys, "u-1", org.slug))
    assert (caller.can_read, caller.can_write, caller.can_admin) == (
        False,
        False,
        False,
    )


async def test_writers_without_readers_policy_still_read(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org(rules={"registry-writers": '"writer" in token.groups'})
    await seed.member(org, "u-1", ["writer"])
    caller = await resolve_caller(pool, login_headers(keys, "u-1", org.slug))
    assert (caller.can_read, caller.can_write) == (True, True)


async def test_v1_callers_keep_working_without_selector_headers(
    pool: Pool, add_api_key: Any, add_policy: Any
) -> None:
    key, _, tenant = await add_api_key()
    caller = await resolve_caller(pool, {"x-api-key": key})
    assert (caller.can_read, caller.is_platform_admin, caller.org_slug) == (
        True,
        False,
        None,
    )
    assert caller.source == "v1"


async def test_can_read_denies_a_caller_without_the_read_capability(
    pool: Pool,
) -> None:
    tenant = uuid.uuid4()
    caller = Caller(tenant, "u", {}, True, True, can_read=False)
    row = {
        "tenant_id": tenant,
        "scope": "org",
        "product_id": None,
        "status": "published",
        "created_by": "u",
        "id": uuid.uuid4(),
    }
    async with pool.connection() as conn:
        assert await can_read(conn, caller, row) is False
