import time
from typing import Annotated, Any

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.api.deps import db, get_caller, require_read
from krep.api.errors import ApiError, install_error_handlers
from krep.config import get_settings
from krep.identity.platform import PLATFORM_USER, key_matches
from krep.identity.resolve import Caller, resolve_caller
from tests.identity.conftest import PLATFORM_KEY, Keys, Seed, login_headers

Pool = AsyncConnectionPool[AsyncConnection]


async def failure(pool: Pool, headers: dict[str, str]) -> None:
    with pytest.raises(ApiError) as exc:
        await resolve_caller(pool, headers)
    assert exc.value.status == 401


async def test_v2ac6_table_grant_gives_platform_identity_in_any_org(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.platform_admin("boss")
    caller = await resolve_caller(pool, login_headers(keys, "boss", org.slug))
    assert caller.tenant_id == org.id
    assert (
        caller.is_platform_admin,
        caller.can_admin,
        caller.can_write,
        caller.can_read,
    ) == (
        True,
        True,
        True,
        True,
    )
    assert caller.user_id == "boss"


async def test_v2ac6_env_key_gives_platform_identity(pool: Pool, seed: Seed) -> None:
    org = await seed.org()
    caller = await resolve_caller(
        pool, {"x-org": org.slug, "x-platform-key": PLATFORM_KEY}
    )
    assert caller.tenant_id == org.id
    assert (caller.is_platform_admin, caller.can_admin, caller.source) == (
        True,
        True,
        "platform_key",
    )
    assert caller.user_id == PLATFORM_USER
    assert caller.doc["token"]["sub"] == PLATFORM_USER


async def test_v2ac6_wrong_key_is_401_even_with_a_valid_bearer(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.member(org, "u-1", ["org-admin"])
    headers = {**login_headers(keys, "u-1", org.slug), "x-platform-key": "wrong" * 10}
    await failure(pool, headers)
    await failure(pool, {"x-org": org.slug, "x-platform-key": ""})


async def test_v2ac6_unset_key_disables_key_auth(
    pool: Pool, seed: Seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await seed.org()
    monkeypatch.setenv("KREP_PLATFORM_ADMIN_KEY", "")
    get_settings.cache_clear()
    await failure(pool, {"x-org": org.slug, "x-platform-key": PLATFORM_KEY})
    await failure(pool, {"x-org": org.slug, "x-platform-key": ""})


async def test_v2ac6_short_key_is_treated_as_unset(
    pool: Pool, seed: Seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await seed.org()
    monkeypatch.setenv("KREP_PLATFORM_ADMIN_KEY", "short")
    get_settings.cache_clear()
    assert key_matches("short") is False
    await failure(pool, {"x-org": org.slug, "x-platform-key": "short"})


def test_key_matches_is_exact(seed: Seed) -> None:
    assert key_matches(PLATFORM_KEY)
    assert not key_matches(PLATFORM_KEY + "x")
    assert not key_matches(PLATFORM_KEY[:-1])
    assert not key_matches("")


async def test_v2ac6_org_jwt_never_gets_platform_identity(
    pool: Pool, seed: Seed
) -> None:
    org = await seed.org()
    await seed.platform_admin("boss")
    await seed.hmac(org, "o" * 40)
    token = jwt.encode(
        {"sub": "boss", "groups": ["platform-admin"], "exp": int(time.time()) + 60},
        "o" * 40,
        algorithm="HS256",
    )
    caller = await resolve_caller(
        pool, {"authorization": f"Bearer {token}", "x-org": org.slug}
    )
    assert (caller.is_platform_admin, caller.can_admin) == (False, False)


async def test_v2ac6_non_admin_user_never_gets_platform_identity(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.member(org, "u-1", ["org-admin"])
    caller = await resolve_caller(pool, login_headers(keys, "u-1", org.slug))
    assert caller.is_platform_admin is False
    assert caller.can_admin is True


async def test_disabled_platform_admin_is_blocked(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.platform_admin("boss")
    await seed.disable("boss")
    await failure(pool, login_headers(keys, "boss", org.slug))


async def test_platform_admin_in_a_suspended_org_is_still_401(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org(status="suspended")
    await seed.platform_admin("boss")
    await failure(pool, login_headers(keys, "boss", org.slug))


def flag_app(pool: Pool) -> FastAPI:
    app = FastAPI()
    app.state.pool = pool
    install_error_handlers(app)

    @app.get("/flag")
    async def flag(
        _: Annotated[Caller, Depends(get_caller)],
        conn: Annotated[AsyncConnection, Depends(db)],
    ) -> dict[str, str | None]:
        cur = await conn.execute("SELECT current_setting('app.platform_admin', true)")
        row = await cur.fetchone()
        assert row
        return {"flag": row[0] or None}

    @app.get("/read", dependencies=[Depends(require_read)])
    async def read() -> dict[str, bool]:
        return {"ok": True}

    return app


async def test_platform_flag_is_set_only_for_platform_callers(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.member(org, "u-1", ["org-admin"])
    await seed.platform_admin("boss")
    transport = httpx.ASGITransport(app=flag_app(pool))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        member = await client.get("/flag", headers=login_headers(keys, "u-1", org.slug))
        boss = await client.get("/flag", headers=login_headers(keys, "boss", org.slug))
        by_key = await client.get(
            "/flag", headers={"x-org": org.slug, "x-platform-key": PLATFORM_KEY}
        )
    assert member.json() == {"flag": None}
    assert boss.json() == {"flag": "on"}
    assert by_key.json() == {"flag": "on"}


async def test_require_read_denies_callers_without_read_capability(
    pool: Pool, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.member(org, "reader", ["reader"])
    await seed.member(org, "nobody", ["other"])
    transport = httpx.ASGITransport(app=flag_app(pool))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        ok = await client.get("/read", headers=login_headers(keys, "reader", org.slug))
        denied = await client.get(
            "/read", headers=login_headers(keys, "nobody", org.slug)
        )
    assert ok.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["error"] == "forbidden"


def test_cli_grant_resolves_username_and_is_idempotent(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid

    import psycopg

    from krep.cli import main
    from tests.conftest import role_url

    user_id = f"u-{uuid.uuid4().hex[:8]}"
    username = f"name-{uuid.uuid4().hex[:8]}"
    with psycopg.connect(role_url("postgres", migrated_db), autocommit=True) as conn:
        conn.execute(
            'INSERT INTO auth."user" (id, username, email, name) VALUES (%s, %s, %s, %s)',
            (user_id, username, f"{username}@example.com", "N"),
        )
    monkeypatch.setenv(
        "KREP_MIGRATION_DATABASE_URL", role_url("krep_owner", migrated_db)
    )

    def granted() -> list[tuple[Any, ...]]:
        with psycopg.connect(role_url("postgres", migrated_db)) as conn:
            return conn.execute(
                "SELECT user_id, granted_by FROM platform_admins WHERE user_id = %s",
                (user_id,),
            ).fetchall()

    assert main(["platform-admin", "grant", "--username", "nobody-by-that-name"]) == 1
    assert granted() == []
    assert main(["platform-admin", "grant", "--username", username]) == 0
    assert main(["platform-admin", "grant", "--username", username]) == 0
    assert granted() == [(user_id, "ops:cli")]
