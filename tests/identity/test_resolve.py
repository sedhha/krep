import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.api.errors import ApiError
from krep.identity.resolve import resolve_caller
from tests.identity.conftest import Keys, b64url, claims

Pool = AsyncConnectionPool[AsyncConnection]
AddIssuer = Callable[..., Awaitable[dict[str, Any]]]
AddKey = Callable[..., Awaitable[tuple[str, uuid.UUID, uuid.UUID]]]


def bearer(keys: Keys, row: dict[str, Any], **overrides: Any) -> dict[str, str]:
    token = keys.sign(claims(iss=row["issuer"], aud=row["audience"], **overrides))
    return {"authorization": f"Bearer {token}"}


async def assert_rejected(pool: Pool, headers: dict[str, str], status: int = 401) -> ApiError:
    with pytest.raises(ApiError) as exc:
        await resolve_caller(pool, headers)
    assert exc.value.status == status
    return exc.value


async def test_ac2_fixed_tenant_issuer(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    row = await add_issuer()
    caller = await resolve_caller(pool, bearer(keys, row, groups=["g"]))
    assert caller.tenant_id == row["tenant_id"]
    assert caller.user_id == "u42"
    assert caller.doc["token"]["groups"] == ["g"]
    assert caller.doc["principal"] == {}


async def test_ac2_tenant_claim_path_issuer(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    tenant = uuid.uuid4()
    row = await add_issuer(tenant_id=None, tenant_claim_path=["https://x.example", "tenant"])
    headers = bearer(keys, row, **{"https://x.example": {"tenant": str(tenant)}})
    caller = await resolve_caller(pool, headers)
    assert caller.tenant_id == tenant


async def test_ac2_two_issuers_resolve_to_their_own_tenants(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    a = await add_issuer()
    b = await add_issuer()
    assert (await resolve_caller(pool, bearer(keys, a))).tenant_id == a["tenant_id"]
    assert (await resolve_caller(pool, bearer(keys, b))).tenant_id == b["tenant_id"]


@pytest.mark.parametrize("claim", [None, "not-a-uuid", 7, ["x"]])
async def test_tenant_claim_missing_or_not_a_uuid(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer, claim: Any
) -> None:
    row = await add_issuer(tenant_id=None, tenant_claim_path=["tid"])
    extra = {} if claim is None else {"tid": claim}
    err = await assert_rejected(pool, bearer(keys, row, **extra))
    assert err.error == "unauthenticated"


async def test_ac2_unregistered_issuer(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    token = keys.sign(claims(iss="https://unknown.example.com/"))
    err = await assert_rejected(pool, {"authorization": f"Bearer {token}"})
    assert err.error == "unauthenticated"


async def test_ac2_wrong_audience(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    row = await add_issuer()
    token = keys.sign(claims(iss=row["issuer"], aud="other"))
    await assert_rejected(pool, {"authorization": f"Bearer {token}"})


async def test_disabled_issuer(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    row = await add_issuer(enabled=False)
    await assert_rejected(pool, bearer(keys, row))


async def test_expired_token(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    row = await add_issuer()
    await assert_rejected(pool, bearer(keys, row, exp=1))


async def test_user_id_from_custom_claim_path(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    row = await add_issuer(user_claim_path=["profile", "oid"])
    caller = await resolve_caller(pool, bearer(keys, row, profile={"oid": "abc"}))
    assert caller.user_id == "abc"


async def test_token_without_sub_is_rejected(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    row = await add_issuer()
    token = keys.sign({k: v for k, v in claims(iss=row["issuer"]).items() if k != "sub"})
    await assert_rejected(pool, {"authorization": f"Bearer {token}"})


async def test_machine_token_without_principal_gets_client_user(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    row = await add_issuer(allow_principal=True)
    caller = await resolve_caller(pool, bearer(keys, row, sub="client-abc"))
    assert caller.user_id == "client:client-abc"
    assert caller.doc["principal"] == {}


async def test_machine_token_without_sub_and_principal_is_rejected(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    row = await add_issuer(allow_principal=True)
    token = keys.sign({k: v for k, v in claims(iss=row["issuer"]).items() if k != "sub"})
    await assert_rejected(pool, {"authorization": f"Bearer {token}"})


@pytest.mark.parametrize(
    "headers",
    [{}, {"authorization": "Basic abc"}, {"authorization": "Bearer"}, {"authorization": "Bearer "}],
)
async def test_missing_or_malformed_credentials(pool: Pool, headers: dict[str, str]) -> None:
    err = await assert_rejected(pool, headers)
    assert err.error == "unauthenticated"


async def test_api_key_resolves_tenant_and_doc(pool: Pool, add_api_key: AddKey) -> None:
    key, key_id, tenant = await add_api_key()
    caller = await resolve_caller(pool, {"x-api-key": key})
    assert caller.tenant_id == tenant
    assert caller.doc == {"token": {"api_key_id": str(key_id)}, "principal": {}}
    assert caller.user_id == f"apikey:{key_id}"


async def test_revoked_api_key(pool: Pool, add_api_key: AddKey) -> None:
    key, _, _ = await add_api_key(revoked=True)
    err = await assert_rejected(pool, {"x-api-key": key})
    assert err.error == "unauthenticated"


async def test_unknown_api_key(pool: Pool) -> None:
    await assert_rejected(pool, {"x-api-key": "nope"})


async def test_ac3_principal_honored_for_machine_issuer(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    row = await add_issuer(allow_principal=True)
    principal = {"id": "user-123", "roles": ["support"]}
    headers = {**bearer(keys, row, sub="client-abc"), "x-principal": b64url(principal)}
    caller = await resolve_caller(pool, headers)
    assert caller.user_id == "user-123"
    assert caller.doc["principal"] == principal
    assert caller.doc["token"]["sub"] == "client-abc"


async def test_ac3_principal_honored_for_api_key(pool: Pool, add_api_key: AddKey) -> None:
    key, _, _ = await add_api_key(allow_principal=True)
    principal = {"id": "user-9", "department": "billing"}
    caller = await resolve_caller(pool, {"x-api-key": key, "x-principal": b64url(principal)})
    assert caller.user_id == "user-9"
    assert caller.doc["principal"] == principal


async def test_ac3_principal_ignored_for_user_token(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    row = await add_issuer()
    headers = {**bearer(keys, row), "x-principal": b64url({"id": "forged", "roles": ["admin"]})}
    caller = await resolve_caller(pool, headers)
    assert caller.user_id == "u42"
    assert caller.doc["principal"] == {}


async def test_ac3_malformed_principal_is_ignored_for_user_token(
    pool: Pool, keys: Keys, jwks: dict[str, Any], add_issuer: AddIssuer
) -> None:
    row = await add_issuer()
    caller = await resolve_caller(pool, {**bearer(keys, row), "x-principal": "%%%"})
    assert caller.user_id == "u42"


async def test_principal_ignored_for_api_key_without_allow_principal(
    pool: Pool, add_api_key: AddKey
) -> None:
    key, key_id, _ = await add_api_key(allow_principal=False)
    caller = await resolve_caller(pool, {"x-api-key": key, "x-principal": b64url({"id": "x"})})
    assert caller.user_id == f"apikey:{key_id}"
    assert caller.doc["principal"] == {}


async def test_ac3_principal_without_id_is_400(pool: Pool, add_api_key: AddKey) -> None:
    key, _, _ = await add_api_key(allow_principal=True)
    err = await assert_rejected(
        pool, {"x-api-key": key, "x-principal": b64url({"roles": ["a"]})}, status=400
    )
    assert err.error == "principal_id_required"


async def test_invalid_base64_principal_is_400(pool: Pool, add_api_key: AddKey) -> None:
    key, _, _ = await add_api_key(allow_principal=True)
    err = await assert_rejected(pool, {"x-api-key": key, "x-principal": "!!!"}, status=400)
    assert err.error == "principal_invalid"


async def test_principal_error_does_not_mask_bad_credentials(pool: Pool) -> None:
    err = await assert_rejected(pool, {"x-api-key": "nope", "x-principal": "!!!"})
    assert err.error == "unauthenticated"
