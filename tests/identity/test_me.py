from collections.abc import AsyncIterator
from typing import Any

import httpx
import jwt
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.api.main import create_app
from tests.identity.conftest import PLATFORM_KEY, Keys, Seed, login_headers

Pool = AsyncConnectionPool[AsyncConnection]


@pytest_asyncio.fixture
async def client(pool: Pool, panel_env: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.state.pool = pool
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_me_lists_memberships_without_selector_headers(
    client: httpx.AsyncClient, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    a, b, c = await seed.org(), await seed.org(), await seed.org()
    await seed.member(a, "u-1", ["org-admin"])
    await seed.member(b, "u-1", ["reader", "x"])
    await seed.member(c, "someone-else", ["org-admin"])
    r = await client.get("/v1/me", headers=login_headers(keys, "u-1"))
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u-1"
    assert body["username"] == "name-u-1"
    assert body["is_platform_admin"] is False
    assert {m["organization"]: m["groups"] for m in body["memberships"]} == {
        a.slug: ["org-admin"],
        b.slug: ["reader", "x"],
    }
    assert body["resolved"] is None


async def test_me_hides_memberships_of_suspended_organisations(
    client: httpx.AsyncClient, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    live, gone = await seed.org(), await seed.org(status="suspended")
    await seed.member(live, "u-1")
    await seed.member(gone, "u-1")
    body = (await client.get("/v1/me", headers=login_headers(keys, "u-1"))).json()
    assert [m["organization"] for m in body["memberships"]] == [live.slug]


async def test_me_with_selector_returns_resolved_capabilities(
    client: httpx.AsyncClient, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.product(org)
    await seed.member(org, "u-1", ["writer"])
    r = await client.get(
        "/v1/me", headers=login_headers(keys, "u-1", org.slug, "prod-one")
    )
    assert r.json()["resolved"] == {
        "organization": org.slug,
        "product": "prod-one",
        "can_read": True,
        "can_write": True,
        "can_admin": False,
    }
    org_level = await client.get("/v1/me", headers=login_headers(keys, "u-1", org.slug))
    assert org_level.json()["resolved"]["product"] is None


async def test_me_reports_platform_admin(
    client: httpx.AsyncClient, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    org = await seed.org()
    await seed.platform_admin("boss")
    body = (
        await client.get("/v1/me", headers=login_headers(keys, "boss", org.slug))
    ).json()
    assert body["is_platform_admin"] is True
    assert body["memberships"] == []
    assert body["resolved"]["can_admin"] is True


async def test_me_with_platform_key(client: httpx.AsyncClient, seed: Seed) -> None:
    body = (await client.get("/v1/me", headers={"x-platform-key": PLATFORM_KEY})).json()
    assert body["is_platform_admin"] is True
    assert body["memberships"] == []
    assert body["resolved"] is None


async def test_me_requires_a_panel_credential(
    client: httpx.AsyncClient, keys: Keys, jwks: dict[str, Any], seed: Seed
) -> None:
    assert (await client.get("/v1/me")).status_code == 401
    await seed.member(await seed.org(), "u-1")
    await seed.disable("u-1")
    r = await client.get("/v1/me", headers=login_headers(keys, "u-1"))
    assert r.status_code == 401
    assert r.json()["error"] == "unauthenticated"


async def test_me_does_not_list_memberships_for_org_token_callers(
    client: httpx.AsyncClient, seed: Seed
) -> None:
    import time

    org, other = await seed.org(), await seed.org()
    await seed.member(other, "victim", ["org-admin"])
    await seed.hmac(org, "o" * 40)
    token = jwt.encode(
        {"sub": "victim", "exp": int(time.time()) + 60}, "o" * 40, algorithm="HS256"
    )
    r = await client.get(
        "/v1/me", headers={"authorization": f"Bearer {token}", "x-org": org.slug}
    )
    body = r.json()
    assert body["memberships"] == []
    assert body["is_platform_admin"] is False
    assert body["resolved"]["organization"] == org.slug
