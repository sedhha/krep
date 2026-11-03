import logging
import time
import uuid

import jwt
import pytest
from psycopg import AsyncConnection

from krep.api.errors import ApiError
from krep.auth import crypto, store
from krep.auth.store import load_effective, save_config
from tests.auth.conftest import keys_env, make_key
from tests.db.test_rls import use_tenant
from tests.db.test_v2_schema import organization

SENTINEL = "SENTINEL-" + "s" * 40


def signed(secret: str, **claims: str) -> str:
    return jwt.encode(
        {"sub": "u", "exp": int(time.time()) + 60, **claims},
        secret,
        algorithm="HS256",
    )


async def org_and_product(conn: AsyncConnection) -> tuple[uuid.UUID, uuid.UUID]:
    tenant = await organization(conn)
    await use_tenant(conn, tenant)
    cur = await conn.execute(
        "INSERT INTO products (tenant_id,slug,name,created_by) VALUES (%s,'prod-one','P','u') RETURNING id",
        (tenant,),
    )
    row = await cur.fetchone()
    assert row
    await conn.execute("SET LOCAL ROLE krep_app")
    return tenant, row[0]


async def test_v2ac5_secret_never_leaks(
    owner_conn: AsyncConnection,
    key_ring: dict[str, str],
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.DEBUG)
    tenant, _ = await org_and_product(owner_conn)
    saved = await save_config(
        owner_conn, tenant, None, "hmac", {"audience": "krep"}, SENTINEL, "u"
    )
    assert SENTINEL not in repr(saved)
    assert saved["secret_set"] is True
    assert saved["key_id"] == "k1"
    assert saved["rev"] == 1
    assert "secret_enc" not in saved
    cur = await owner_conn.execute(
        "SELECT secret_enc, config::text FROM auth_configs WHERE tenant_id = %s",
        (tenant,),
    )
    row = await cur.fetchone()
    assert row
    assert SENTINEL.encode() not in bytes(row[0])
    assert SENTINEL not in row[1]
    resolved = await load_effective(owner_conn, tenant, None)
    assert resolved
    assert SENTINEL not in repr(resolved)
    assert SENTINEL not in str(resolved)
    assert resolved.verify(signed(SENTINEL, aud="krep"))["sub"] == "u"
    assert SENTINEL not in caplog.text


async def test_v2ac5_weak_secret_rejected_without_echo(
    owner_conn: AsyncConnection, key_ring: dict[str, str]
):
    tenant, _ = await org_and_product(owner_conn)
    weak = "weak-sentinel"
    with pytest.raises(ApiError) as exc:
        await save_config(owner_conn, tenant, None, "hmac", {}, weak, "u")
    assert (exc.value.status, exc.value.error) == (422, "auth_config_invalid")
    assert weak not in f"{exc.value} {exc.value.message} {exc.value.extra}"


async def test_invalid_config_and_unknown_adapter(
    owner_conn: AsyncConnection, key_ring: dict[str, str]
):
    tenant, _ = await org_and_product(owner_conn)
    for adapter, config in (("hmac", {"algorithms": ["none"]}), ("nope", {})):
        with pytest.raises(ApiError) as exc:
            await save_config(owner_conn, tenant, None, adapter, config, "x" * 40, "u")
        assert exc.value.error == "auth_config_invalid"


async def test_resave_bumps_rev_and_reencrypts_under_new_key(
    owner_conn: AsyncConnection,
    key_ring: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    tenant, _ = await org_and_product(owner_conn)
    first = await save_config(owner_conn, tenant, None, "hmac", {}, SENTINEL, "u")
    monkeypatch.setenv(
        "KREP_ENCRYPTION_KEYS", keys_env(("k2", make_key()), ("k1", key_ring["k1"]))
    )
    resolved = await load_effective(owner_conn, tenant, None)
    assert resolved and resolved.verify(signed(SENTINEL))
    second = await save_config(owner_conn, tenant, None, "hmac", {}, SENTINEL, "u")
    assert (first["rev"], second["rev"], second["key_id"]) == (1, 2, "k2")
    assert first["id"] == second["id"]


async def test_product_override_else_organisation(
    owner_conn: AsyncConnection, key_ring: dict[str, str]
):
    tenant, product = await org_and_product(owner_conn)
    org_secret, product_secret = "o" * 40, "p" * 40
    assert await load_effective(owner_conn, tenant, product) is None
    await save_config(owner_conn, tenant, None, "hmac", {}, org_secret, "u")
    on_product = await load_effective(owner_conn, tenant, product)
    assert on_product and on_product.product_id is None
    await save_config(owner_conn, tenant, product, "hmac", {}, product_secret, "u")
    on_product = await load_effective(owner_conn, tenant, product)
    assert on_product and on_product.product_id == product
    assert on_product.verify(signed(product_secret))
    with pytest.raises(ApiError):
        on_product.verify(signed(org_secret))
    on_org = await load_effective(owner_conn, tenant, None)
    assert on_org and on_org.product_id is None
    assert on_org.verify(signed(org_secret))


async def test_disabled_config_resolves_to_none(
    owner_conn: AsyncConnection, key_ring: dict[str, str]
):
    tenant, _ = await org_and_product(owner_conn)
    await save_config(owner_conn, tenant, None, "hmac", {}, SENTINEL, "u")
    await owner_conn.execute("UPDATE auth_configs SET enabled = false")
    assert await load_effective(owner_conn, tenant, None) is None


async def test_decrypted_verifier_cached_by_id_and_rev_for_60s(
    owner_conn: AsyncConnection,
    key_ring: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    tenant, _ = await org_and_product(owner_conn)
    await save_config(owner_conn, tenant, None, "hmac", {}, SENTINEL, "u")
    calls: list[int] = []
    real = crypto.decrypt

    def counting(ciphertext: bytes, key_id: str) -> str:
        calls.append(1)
        return real(ciphertext, key_id)

    monkeypatch.setattr(store.crypto, "decrypt", counting)
    clock = [1000.0]
    monkeypatch.setattr(store, "_now", lambda: clock[0])
    await load_effective(owner_conn, tenant, None)
    await load_effective(owner_conn, tenant, None)
    assert len(calls) == 1
    clock[0] += 61
    await load_effective(owner_conn, tenant, None)
    assert len(calls) == 2
    await save_config(owner_conn, tenant, None, "hmac", {}, "n" * 40, "u")
    resolved = await load_effective(owner_conn, tenant, None)
    assert len(calls) == 3
    assert resolved and resolved.rev == 2
