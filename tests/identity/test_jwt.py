from typing import Any

import pytest

from krep.api.errors import ApiError
from krep.identity.jwt import verify_token
from tests.identity.conftest import Keys, claims, issuer_row


async def assert_unauthenticated(token: str, row: dict[str, Any]) -> None:
    with pytest.raises(ApiError) as exc:
        await verify_token(token, row)
    assert exc.value.status == 401
    assert exc.value.error == "unauthenticated"


async def test_valid_token_returns_claims(keys: Keys, jwks: dict[str, Any]) -> None:
    result = await verify_token(keys.sign(claims(groups=["a"])), issuer_row())
    assert result["sub"] == "u42"
    assert result["groups"] == ["a"]


async def test_wrong_audience(keys: Keys, jwks: dict[str, Any]) -> None:
    await assert_unauthenticated(keys.sign(claims(aud="someone-else")), issuer_row())


async def test_expired(keys: Keys, jwks: dict[str, Any]) -> None:
    await assert_unauthenticated(keys.sign(claims(exp=1)), issuer_row())


async def test_missing_exp(keys: Keys, jwks: dict[str, Any]) -> None:
    payload = claims()
    del payload["exp"]
    await assert_unauthenticated(keys.sign(payload), issuer_row())


async def test_issuer_claim_must_match_row(keys: Keys, jwks: dict[str, Any]) -> None:
    await assert_unauthenticated(keys.sign(claims(iss="https://evil.example.com/")), issuer_row())


async def test_disabled_issuer(keys: Keys, jwks: dict[str, Any]) -> None:
    await assert_unauthenticated(keys.sign(claims()), issuer_row(enabled=False))


async def test_alg_none(keys: Keys, jwks: dict[str, Any]) -> None:
    import jwt

    token = jwt.encode(claims(), None, algorithm="none", headers={"kid": keys.kid})
    await assert_unauthenticated(token, issuer_row())


async def test_hs256_signed_with_public_material_is_rejected(
    keys: Keys, jwks: dict[str, Any]
) -> None:
    import jwt

    token = jwt.encode(claims(), "x" * 64, algorithm="HS256", headers={"kid": keys.kid})
    await assert_unauthenticated(token, issuer_row())


async def test_non_https_jwks_uri(keys: Keys, jwks: dict[str, Any]) -> None:
    await assert_unauthenticated(
        keys.sign(claims()), issuer_row(jwks_uri="http://idp.example.com/jwks.json")
    )
    assert jwks["fetches"] == 0


async def test_signature_from_other_key(jwks: dict[str, Any]) -> None:
    await assert_unauthenticated(Keys("k1").sign(claims()), issuer_row())


async def test_garbage_token(jwks: dict[str, Any]) -> None:
    await assert_unauthenticated("not-a-jwt", issuer_row())


async def test_jwks_is_cached_between_calls(keys: Keys, jwks: dict[str, Any]) -> None:
    await verify_token(keys.sign(claims()), issuer_row())
    await verify_token(keys.sign(claims()), issuer_row())
    assert jwks["fetches"] == 1


async def test_unknown_kid_triggers_refetch_and_picks_up_rotated_key(
    keys: Keys, jwks: dict[str, Any]
) -> None:
    await verify_token(keys.sign(claims()), issuer_row())
    rotated = Keys("k2")
    jwks["keys"] = [keys.jwk, rotated.jwk]
    result = await verify_token(rotated.sign(claims()), issuer_row())
    assert result["sub"] == "u42"
    assert jwks["fetches"] == 2


async def test_unknown_kid_that_stays_unknown_is_rejected(
    keys: Keys, jwks: dict[str, Any]
) -> None:
    await assert_unauthenticated(Keys("ghost").sign(claims()), issuer_row())


async def test_ttl_expiry_refetches(
    keys: Keys, jwks: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from krep.identity import jwt as krep_jwt

    await verify_token(keys.sign(claims()), issuer_row())
    monkeypatch.setattr(krep_jwt, "JWKS_TTL_SECONDS", -1)
    await verify_token(keys.sign(claims()), issuer_row())
    assert jwks["fetches"] == 2


async def test_jwks_fetch_failure_is_unauthenticated(
    keys: Keys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krep.identity import jwt as krep_jwt

    async def boom(uri: str) -> list[dict[str, Any]]:
        raise OSError("down")

    krep_jwt.clear_cache()
    monkeypatch.setattr(krep_jwt, "fetch_jwks", boom)
    await assert_unauthenticated(keys.sign(claims()), issuer_row())
