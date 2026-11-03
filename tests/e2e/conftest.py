import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from psycopg import AsyncConnection

from krep.api import create_app
from krep.cli import main
from krep.config import Settings, get_settings
from krep.db.pool import open_pool
from krep.identity import jwt as krep_jwt
from tests.conftest import role_url
from tests.identity.conftest import AUDIENCE, ISSUER, JWKS_URI, Keys

ADMIN_RULE = 'token.groups == "grc-admins"'
WRITER_RULE = 'token.groups == "grc-editors"'


@pytest.fixture(scope="module")
def keys() -> Keys:
    return Keys("e2e")


@pytest_asyncio.fixture
async def app(
    migrated_db: str, keys: Keys, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FastAPI]:
    async def fake_fetch(_uri: str) -> list[dict[str, Any]]:
        return [keys.jwk]

    krep_jwt.clear_cache()
    monkeypatch.setattr(krep_jwt, "fetch_jwks", fake_fetch)
    monkeypatch.setenv("KREP_DATABASE_URL", role_url("krep_app", migrated_db))
    settings = Settings(
        database_url=role_url("krep_app", migrated_db), migration_database_url=""
    )
    monkeypatch.setenv("KREP_PLATFORM_ADMIN_KEY", "e2e-platform-key-" + "k" * 32)
    get_settings.cache_clear()
    platform_settings = Settings(
        database_url=role_url("krep_platform", migrated_db), migration_database_url=""
    )
    application = create_app()
    async with (
        await open_pool(settings, min_size=1, max_size=4) as pool,
        await open_pool(platform_settings, min_size=1, max_size=2) as platform_pool,
    ):
        application.state.pool = pool
        application.state.platform_pool = platform_pool
        yield application
    get_settings.cache_clear()


@pytest.fixture
def tenant() -> uuid.UUID:
    return uuid.uuid4()


@pytest_asyncio.fixture
async def onboarded(
    migrated_db: str, tenant: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> str:
    issuer = f"{ISSUER}{tenant}/"
    async with await AsyncConnection.connect(
        role_url("krep_owner", migrated_db), autocommit=True
    ) as conn:
        await conn.execute(
            "INSERT INTO token_issuers (issuer, audience, jwks_uri, tenant_id, user_claim_path, "
            "allow_principal, enabled) VALUES (%s, %s, %s, %s, ARRAY['sub'], false, true)",
            (issuer, AUDIENCE, JWKS_URI, tenant),
        )
    monkeypatch.setenv(
        "KREP_MIGRATION_DATABASE_URL", role_url("krep_owner", migrated_db)
    )
    code = await asyncio.to_thread(
        main,
        [
            "tenant",
            "init",
            "--tenant",
            str(tenant),
            "--admin-rule",
            ADMIN_RULE,
            "--writer-rule",
            WRITER_RULE,
        ],
    )
    assert code == 0
    return issuer


def make_user(
    app: FastAPI, keys: Keys, issuer: str, sub: str, **claims: Any
) -> httpx.AsyncClient:
    token = keys.sign(
        {
            "iss": issuer,
            "aud": AUDIENCE,
            "sub": sub,
            "exp": int(time.time()) + 600,
            **claims,
        }
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {token}"},
    )


async def open_policy_id(migrated_db: str, tenant: uuid.UUID) -> str:
    async with await AsyncConnection.connect(
        role_url("krep_owner", migrated_db), autocommit=True
    ) as conn:
        await conn.execute(
            "SELECT set_config('app.tenant_id', %s, false)", (str(tenant),)
        )
        cur = await conn.execute(
            "INSERT INTO access_policies (tenant_id, name, ast, source, compiled_path, "
            "compiler_version, reserved, kind, created_by, updated_by) "
            "VALUES (%s, 'open-to-all', '{}'::jsonb, 'true', 'true'::jsonpath, 1, true, 'open', "
            "'t', 't') ON CONFLICT (tenant_id, name) DO UPDATE SET kind = 'open' RETURNING id",
            (tenant,),
        )
        row = await cur.fetchone()
        assert row is not None
        return str(row[0])
