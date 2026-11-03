import time
from typing import Any

import httpx
import jwt
import psycopg
import pytest

from krep.config import get_settings
from tests.conftest import role_url
from tests.org.conftest import (
    AddUser,
    Keys,
    Seed,
    login_headers,
    new_slug,
    org_body,
)

HMAC_SECRET = "s" * 40
AUTH = {"adapter": "hmac", "config": {"audience": "krep"}, "secret": HMAC_SECRET}


async def create(
    client: httpx.AsyncClient, headers: dict[str, str], body: dict[str, Any]
) -> httpx.Response:
    return await client.post("/v1/admin/organizations", json=body, headers=headers)


async def test_v2ac6_create_organization_applies_defaults(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    add_user: AddUser,
    seed: Seed,
    migrated_db: str,
) -> None:
    admin_id = await add_user("ravi-1")
    slug = new_slug()
    r = await create(client, platform_headers, org_body(slug, "ravi-1", auth=AUTH))
    assert r.status_code == 201
    org_id = r.json()["id"]
    assert r.json()["slug"] == slug
    assert HMAC_SECRET not in r.text
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        conn.execute("SELECT set_config('app.tenant_id', %s, false)", (org_id,))
        policies = conn.execute(
            "SELECT name, kind, reserved, source FROM access_policies ORDER BY name"
        ).fetchall()
        assert policies == [
            ("open-to-all", "open", True, "true"),
            ("registry-admins", "rule", True, '"org-admin" in token.groups'),
            (
                "registry-readers",
                "rule",
                True,
                '"org-admin" in token.groups || "writer" in token.groups || "reader" in token.groups',
            ),
            (
                "registry-writers",
                "rule",
                True,
                '"org-admin" in token.groups || "writer" in token.groups',
            ),
        ]
        assert conn.execute(
            "SELECT user_id, groups FROM memberships WHERE tenant_id = %s", (org_id,)
        ).fetchall() == [(admin_id, ["org-admin"])]
        assert conn.execute(
            "SELECT adapter, secret_enc IS NOT NULL FROM auth_configs"
        ).fetchall() == [("hmac", True)]


async def test_v2ac6_custom_capabilities_replace_defaults(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    add_user: AddUser,
    migrated_db: str,
) -> None:
    await add_user("cap-admin")
    rules = {
        "registry-admins": 'token.team == "ops"',
        "registry-writers": 'token.team == "ops"',
        "registry-readers": '"reader" in token.groups',
    }
    r = await create(
        client,
        platform_headers,
        org_body(new_slug(), "cap-admin", capabilities=rules),
    )
    assert r.status_code == 201
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        conn.execute("SELECT set_config('app.tenant_id', %s, false)", (r.json()["id"],))
        stored = dict(
            conn.execute(
                "SELECT name, source FROM access_policies WHERE kind = 'rule'"
            ).fetchall()
        )
    assert stored == rules


async def test_v2ac6_invalid_capability_rule_is_422_and_creates_nothing(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    add_user: AddUser,
    migrated_db: str,
) -> None:
    await add_user("cap-bad")
    slug = new_slug()
    r = await create(
        client,
        platform_headers,
        org_body(slug, "cap-bad", capabilities={"registry-admins": "token.groups =="}),
    )
    assert r.status_code == 422
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        assert conn.execute(
            "SELECT count(*) FROM organizations WHERE slug = %s", (slug,)
        ).fetchone() == (0,)


async def test_v2ac6_failure_at_auth_step_leaves_nothing_behind(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    add_user: AddUser,
    migrated_db: str,
) -> None:
    await add_user("atomic-1")
    slug = new_slug()
    r = await create(
        client,
        platform_headers,
        org_body(slug, "atomic-1", auth={**AUTH, "secret": "short"}),
    )
    assert r.status_code == 422
    assert r.json()["error"] == "auth_config_invalid"
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        assert conn.execute(
            "SELECT count(*) FROM organizations WHERE slug = %s", (slug,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM admin_audit_log WHERE action = 'org.create' AND target = %s",
            (slug,),
        ).fetchone() == (0,)
    ok = await create(client, platform_headers, org_body(slug, "atomic-1"))
    assert ok.status_code == 201


async def test_v2ac6_unknown_admin_user_is_422(
    client: httpx.AsyncClient, platform_headers: dict[str, str]
) -> None:
    r = await create(client, platform_headers, org_body(new_slug(), "nobody-here"))
    assert r.status_code == 422
    assert r.json()["error"] == "admin_user_not_found"


async def test_v2ac6_duplicate_slug_is_409_slug_taken(
    client: httpx.AsyncClient, platform_headers: dict[str, str], add_user: AddUser
) -> None:
    await add_user("dup-admin")
    slug = new_slug()
    assert (
        await create(client, platform_headers, org_body(slug, "dup-admin"))
    ).status_code == 201
    r = await create(client, platform_headers, org_body(slug, "dup-admin"))
    assert (r.status_code, r.json()["error"]) == (409, "slug_taken")


async def test_v2ac6_invalid_slug_is_422(
    client: httpx.AsyncClient, platform_headers: dict[str, str], add_user: AddUser
) -> None:
    await add_user("slug-admin")
    r = await create(client, platform_headers, org_body("Bad Slug", "slug-admin"))
    assert r.status_code == 422


async def test_v2ac6_list_and_get_organizations(
    client: httpx.AsyncClient, platform_headers: dict[str, str], add_user: AddUser
) -> None:
    await add_user("list-admin")
    slug = new_slug()
    org_id = (
        await create(client, platform_headers, org_body(slug, "list-admin"))
    ).json()["id"]
    listed = await client.get("/v1/admin/organizations", headers=platform_headers)
    assert slug in [o["slug"] for o in listed.json()["items"]]
    got = await client.get(
        f"/v1/admin/organizations/{org_id}", headers=platform_headers
    )
    assert got.status_code == 200
    assert got.json()["status"] == "active"
    missing = await client.get(
        "/v1/admin/organizations/00000000-0000-0000-0000-000000000000",
        headers=platform_headers,
    )
    assert missing.status_code == 404


async def test_v2ac6_platform_routes_accept_only_platform_admins(
    client: httpx.AsyncClient,
    seed: Seed,
    keys: Keys,
    jwks: dict[str, Any],
    platform_headers: dict[str, str],
) -> None:
    org = await seed.org()
    await seed.member(org, "plain-admin", ["org-admin"])
    await seed.platform_admin("boss-1")
    url = "/v1/admin/organizations"
    assert (
        await client.get(url, headers=login_headers(keys, "plain-admin"))
    ).status_code == 403
    assert (
        await client.get(url, headers=login_headers(keys, "boss-1"))
    ).status_code == 200
    assert (await client.get(url, headers=platform_headers)).status_code == 200
    assert (await client.get(url)).status_code == 401
    assert (
        await client.get(url, headers={"x-platform-key": "wrong" * 10})
    ).status_code == 401
    token = jwt.encode(
        {"sub": "x", "aud": "krep", "exp": int(time.time()) + 60},
        "s" * 40,
        algorithm="HS256",
    )
    assert (
        await client.get(url, headers={"authorization": f"Bearer {token}"})
    ).status_code == 401


async def test_v2ac6_routes_closed_without_any_platform_identity(
    client: httpx.AsyncClient,
    seed: Seed,
    platform_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KREP_PLATFORM_ADMIN_KEY", "")
    monkeypatch.setenv("KREP_LOGIN_ISSUER", "")
    get_settings.cache_clear()
    r = await client.get("/v1/admin/organizations", headers=platform_headers)
    assert r.status_code == 404


async def test_v2ac7_platform_admin_attaches_and_detaches_any_member(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    add_user: AddUser,
    migrated_db: str,
) -> None:
    await add_user("att-admin")
    member = await add_user("att-member")
    org_id = (
        await create(client, platform_headers, org_body(new_slug(), "att-admin"))
    ).json()["id"]
    url = f"/v1/admin/organizations/{org_id}/members/{member}"
    r = await client.put(url, json={"groups": ["writer"]}, headers=platform_headers)
    assert r.status_code == 200
    r = await client.put(url, json={"groups": ["reader"]}, headers=platform_headers)
    assert r.json()["groups"] == ["reader"]
    ghost = await client.put(
        f"/v1/admin/organizations/{org_id}/members/ghost-id",
        json={"groups": []},
        headers=platform_headers,
    )
    assert ghost.status_code == 404
    assert (await client.delete(url, headers=platform_headers)).status_code == 204
    assert (await client.delete(url, headers=platform_headers)).status_code == 404


async def test_v2ac6_grant_and_revoke_platform_admin(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    add_user: AddUser,
    keys: Keys,
    jwks: dict[str, Any],
    seed: Seed,
) -> None:
    user = await add_user("promoted")
    url = f"/v1/admin/platform-admins/{user}"
    list_url = "/v1/admin/organizations"
    assert (
        await client.get(list_url, headers=login_headers(keys, user))
    ).status_code == 403
    assert (await client.put(url, headers=platform_headers)).status_code == 200
    assert (
        await client.get(list_url, headers=login_headers(keys, user))
    ).status_code == 200
    assert (await client.delete(url, headers=platform_headers)).status_code == 204
    assert (
        await client.get(list_url, headers=login_headers(keys, user))
    ).status_code == 403
    assert (
        await client.put("/v1/admin/platform-admins/ghost", headers=platform_headers)
    ).status_code == 404


async def test_v2ac2_disable_and_enable_user(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    add_user: AddUser,
    keys: Keys,
    jwks: dict[str, Any],
    seed: Seed,
) -> None:
    user = await add_user("banned")
    await seed.platform_admin(user)
    url = "/v1/admin/organizations"
    assert (await client.get(url, headers=login_headers(keys, user))).status_code == 200
    r = await client.post(
        f"/v1/admin/users/{user}/disable",
        json={"reason": "abuse"},
        headers=platform_headers,
    )
    assert r.status_code == 200
    assert (await client.get(url, headers=login_headers(keys, user))).status_code == 401
    assert (
        await client.post(f"/v1/admin/users/{user}/enable", headers=platform_headers)
    ).status_code == 200
    assert (await client.get(url, headers=login_headers(keys, user))).status_code == 200


async def test_v2ac6_adapter_listing(
    client: httpx.AsyncClient, platform_headers: dict[str, str]
) -> None:
    r = await client.get("/v1/admin/auth-adapters", headers=platform_headers)
    assert r.status_code == 200
    hmac_entry = next(a for a in r.json()["items"] if a["type"] == "hmac")
    assert hmac_entry["secret_fields"] == ["secret"]
    assert "properties" in hmac_entry["config_schema"]


async def test_v2ac8_every_platform_write_is_audited(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    add_user: AddUser,
    migrated_db: str,
) -> None:
    await add_user("aud-admin")
    other = await add_user("aud-member")
    org_id = (
        await create(
            client, platform_headers, org_body(new_slug(), "aud-admin", auth=AUTH)
        )
    ).json()["id"]
    await client.put(
        f"/v1/admin/organizations/{org_id}/members/{other}",
        json={"groups": []},
        headers=platform_headers,
    )
    await client.delete(
        f"/v1/admin/organizations/{org_id}/members/{other}", headers=platform_headers
    )
    await client.put(f"/v1/admin/platform-admins/{other}", headers=platform_headers)
    await client.delete(f"/v1/admin/platform-admins/{other}", headers=platform_headers)
    await client.post(f"/v1/admin/users/{other}/disable", headers=platform_headers)
    await client.post(f"/v1/admin/users/{other}/enable", headers=platform_headers)
    audit = await client.get("/v1/admin/audit?limit=200", headers=platform_headers)
    actions = {a["action"] for a in audit.json()["items"]}
    assert {
        "org.create",
        "org.member.attach",
        "org.member.detach",
        "platform_admin.grant",
        "platform_admin.revoke",
        "user.disable",
        "user.enable",
    } <= actions
    assert HMAC_SECRET not in audit.text
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        assert HMAC_SECRET not in str(
            conn.execute("SELECT detail FROM admin_audit_log").fetchall()
        )


async def test_v2ac8_app_pool_cannot_write_platform_tables(
    pool: Any, platform_pool: Any
) -> None:
    for statement in (
        "INSERT INTO platform_admins (user_id, granted_by) VALUES ('x', 'x')",
        "INSERT INTO disabled_users (user_id, disabled_by) VALUES ('x', 'x')",
        "UPDATE admin_audit_log SET actor = 'x'",
        "DELETE FROM admin_audit_log",
        "INSERT INTO organizations (slug, name, created_by) VALUES ('wrongpool', 'n', 'x')",
    ):
        async with pool.connection() as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await conn.execute(statement)
    async with platform_pool.connection() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute(
                "INSERT INTO products (tenant_id, slug, name, created_by) VALUES (gen_random_uuid(), 'pp', 'n', 'x')"
            )
