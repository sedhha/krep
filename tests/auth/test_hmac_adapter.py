import time
from typing import Any

import jwt
import pytest

from krep.api.errors import ApiError
from krep.auth import get_adapter
from krep.auth.hmac import HmacConfig

SECRET = "h" * 64


def adapter_config(**overrides: Any) -> HmacConfig:
    return HmacConfig.model_validate({"secret": SECRET, **overrides})


def token(secret: str = SECRET, alg: str = "HS256", **claims: Any) -> str:
    payload = {"sub": "u1", "exp": int(time.time()) + 300, **claims}
    return jwt.encode(payload, secret, algorithm=alg)


def verify(raw: str, config: HmacConfig | None = None) -> Any:
    config = config or adapter_config()
    return get_adapter("hmac").verify(raw, config, {"secret": SECRET})


@pytest.mark.parametrize("alg", ["HS256", "HS384", "HS512"])
def test_valid_algorithms(alg: str):
    config = adapter_config(algorithms=[alg])
    assert verify(token(alg=alg), config)["sub"] == "u1"


def assert_rejected(raw: str, config: HmacConfig | None = None) -> None:
    with pytest.raises(ApiError) as exc:
        verify(raw, config)
    assert (exc.value.status, exc.value.error) == (401, "unauthenticated")


def test_wrong_secret():
    assert_rejected(token(secret="x" * 64))


def test_expired():
    assert_rejected(token(exp=int(time.time()) - 120))


def test_missing_exp():
    assert_rejected(jwt.encode({"sub": "u1"}, SECRET, algorithm="HS256"))


def test_alg_none():
    unsigned = (
        "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJ1MSIsImV4cCI6OTk5OTk5OTk5OX0."
    )
    assert_rejected(unsigned)


def test_rs256_header():
    header = (
        "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiJ1MSIsImV4cCI6OTk5OTk5OTk5OX0.c2ln"
    )
    assert_rejected(header)


def test_algorithm_not_in_config_list():
    assert_rejected(token(alg="HS512"), adapter_config(algorithms=["HS256"]))


def test_audience_and_issuer():
    config = adapter_config(audience="krep", issuer="acme")
    assert verify(token(aud="krep", iss="acme"), config)["aud"] == "krep"
    assert_rejected(token(aud="other", iss="acme"), config)
    assert_rejected(token(aud="krep", iss="other"), config)
    assert_rejected(token(iss="acme"), config)


def test_unconfigured_audience_ignores_claim():
    assert verify(token(aud="anything"))["sub"] == "u1"


def test_leeway_boundary():
    assert verify(token(exp=int(time.time()) - 20))["sub"] == "u1"
    assert_rejected(token(exp=int(time.time()) - 40))


def test_garbage_token():
    assert_rejected("not-a-jwt")


@pytest.mark.parametrize(
    "overrides",
    [
        {"secret": "short"},
        {"algorithms": ["none"]},
        {"algorithms": ["RS256"]},
        {"algorithms": []},
        {"unknown": 1},
    ],
)
def test_invalid_config_rejected(overrides: dict[str, Any]):
    with pytest.raises(ValueError):
        HmacConfig.model_validate({"secret": SECRET, **overrides})
