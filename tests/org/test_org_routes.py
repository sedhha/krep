import time
from typing import Any

import httpx
import jwt
import psycopg

from tests.conftest import role_url
from tests.org.conftest import AddUser, Keys, Org, Seed, login_headers

SECRET = "o" * 40
NEW_SECRET = "n" * 40
HMAC = {"adapter": "hmac", "config": {"audience": "krep"}, "secret": SECRET}


def hmac_token(secret: str = SECRET, **claims: Any) -> str:
    return jwt.encode(
        {"sub": "svc", "aud": "krep", "exp": int(time.time()) + 300, **claims},
        secret,
        algorithm="HS256",
    )


async def acting(
    seed: Seed, keys: Keys, group: str = "org-admin", org: Org | None = None
) -> tuple[Org, dict[str, str], str]:
    org = org or await seed.org()
    user = f"{group}-{org.slug}"
    await seed.member(org, user, [group])
    return org, login_headers(keys, user, org.slug), user


async def test_v2ac7_org_admin_manages_products(
    client: httpx.AsyncClient, seed: Seed, keys: Keys, jwks: dict[str, Any]
) -> None:
    _, headers, _ = await acting(seed, keys)
    created = await client.post(
        "/v1/org/products", json={"slug": "alpha", "name": "Alpha"}, headers=headers
    )
    assert created.status_code == 201
    product_id = created.json()["id"]
    dup = await client.post(
        "/v1/org/products", json={"slug": "alpha", "name": "Again"}, headers=headers
    )
    assert (dup.status_code, dup.json()["error"]) == (409, "slug_taken")
    listed = await client.get("/v1/org/products", headers=headers)
    assert [p["slug"] for p in listed.json()["items"]] == ["alpha"]
    renamed = await client.patch(
        f"/v1/org/products/{product_id}", json={"name": "Alpha 2"}, headers=headers
    )
    assert renamed.json()["name"] == "Alpha 2"
    archived = await client.patch(
        f"/v1/org/products/{product_id}", json={"status": "archived"}, headers=headers
    )
    assert archived.json()["status"] == "archived"


async def test_v2ac7_archiving_product_with_resources_is_409(
    client: httpx.AsyncClient,
    seed: Seed,
    keys: Keys,
    jwks: dict[str, Any],
    owner_exec: Any,
) -> None:
    org, headers, _ = await acting(seed, keys)
    product_id = await seed.product(org, "busy")
    await owner_exec(
        "INSERT INTO registry (tenant_id, type, slug, name, created_by, updated_by, scope, product_id) "
        "VALUES (%s, 'skill', 'thing', 'Thing', 'u', 'u', 'product', %s)",
        (org.id, product_id),
    )
    r = await client.patch(
        f"/v1/org/products/{product_id}", json={"status": "archived"}, headers=headers
    )
    assert (r.status_code, r.json()["error"]) == (409, "product_not_empty")


async def test_v2ac7_org_admin_gets_404_for_other_organisations_ids(
    client: httpx.AsyncClient, seed: Seed, keys: Keys, jwks: dict[str, Any]
) -> None:
    _, headers, _ = await acting(seed, keys)
    other = await seed.org()
    foreign = await seed.product(other, "theirs")
    r = await client.patch(
        f"/v1/org/products/{foreign}", json={"name": "mine now"}, headers=headers
    )
    assert r.status_code == 404
    r = await client.get(f"/v1/org/products/{foreign}/auth", headers=headers)
    assert r.status_code == 404
    other_slug = {**headers, "x-org": other.slug}
    assert (await client.get("/v1/org/products", headers=other_slug)).status_code == 401


async def test_v2ac7_writer_and_reader_cannot_touch_admin_surface(
    client: httpx.AsyncClient, seed: Seed, keys: Keys, jwks: dict[str, Any]
) -> None:
    org = await seed.org()
    for group in ("writer", "reader"):
        _, headers, _ = await acting(seed, keys, group, org)
        calls = [
            client.get("/v1/org/products", headers=headers),
            client.post(
                "/v1/org/products", json={"slug": "zz", "name": "Z"}, headers=headers
            ),
            client.get("/v1/org/auth", headers=headers),
            client.put("/v1/org/auth", json=HMAC, headers=headers),
            client.get("/v1/org/members", headers=headers),
            client.post(
                "/v1/org/members",
                json={"identifier": "x", "groups": []},
                headers=headers,
            ),
            client.put(
                "/v1/org/capabilities",
                json={"rules": {"registry-readers": '"reader" in token.groups'}},
                headers=headers,
            ),
        ]
        for call in calls:
            assert (await call).status_code == 403


async def test_v2ac7_platform_admin_may_use_org_routes(
    client: httpx.AsyncClient, seed: Seed, platform_headers: dict[str, str]
) -> None:
    org = await seed.org()
    r = await client.get(
        "/v1/org/products", headers={**platform_headers, "x-org": org.slug}
    )
    assert r.status_code == 200


async def test_v2ac5_org_auth_never_returns_secret_and_rotation_invalidates(
    client: httpx.AsyncClient,
    seed: Seed,
    keys: Keys,
    jwks: dict[str, Any],
    migrated_db: str,
) -> None:
    org, headers, _ = await acting(seed, keys)
    assert (await client.get("/v1/org/auth", headers=headers)).status_code == 404
    put = await client.put("/v1/org/auth", json=HMAC, headers=headers)
    assert put.status_code == 200
    assert SECRET not in put.text
    got = (await client.get("/v1/org/auth", headers=headers)).json()
    assert (got["secret_set"], got["rev"], got["adapter"]) == (True, 1, "hmac")
    assert got["key_id"] and SECRET not in str(got)
    api = {
        "x-org": org.slug,
        "authorization": f"Bearer {hmac_token(groups=['org-admin'])}",
    }
    assert (await client.get("/v1/org/products", headers=api)).status_code == 200
    rotated = await client.put(
        "/v1/org/auth", json={**HMAC, "secret": NEW_SECRET}, headers=headers
    )
    assert rotated.json()["rev"] == 2
    assert (await client.get("/v1/org/products", headers=api)).status_code == 401
    fresh = {
        "x-org": org.slug,
        "authorization": f"Bearer {hmac_token(NEW_SECRET, groups=['org-admin'])}",
    }
    assert (await client.get("/v1/org/products", headers=fresh)).status_code == 200
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        audit = str(conn.execute("SELECT detail FROM admin_audit_log").fetchall())
        stored = conn.execute("SELECT config::text FROM auth_configs").fetchall()
    assert SECRET not in audit and NEW_SECRET not in audit
    assert SECRET not in str(stored) and NEW_SECRET not in str(stored)


async def test_v2ac5_invalid_auth_config_is_422(
    client: httpx.AsyncClient, seed: Seed, keys: Keys, jwks: dict[str, Any]
) -> None:
    _, headers, _ = await acting(seed, keys)
    r = await client.put(
        "/v1/org/auth", json={**HMAC, "secret": "tiny"}, headers=headers
    )
    assert (r.status_code, r.json()["error"]) == (422, "auth_config_invalid")
    r = await client.put(
        "/v1/org/auth", json={**HMAC, "adapter": "nope"}, headers=headers
    )
    assert r.status_code == 422


async def test_v2ac4_product_override_and_effective_auth(
    client: httpx.AsyncClient, seed: Seed, keys: Keys, jwks: dict[str, Any]
) -> None:
    org, headers, _ = await acting(seed, keys)
    product_id = await seed.product(org, "override")
    base = f"/v1/org/products/{product_id}"
    assert (
        await client.get(f"{base}/effective-auth", headers=headers)
    ).status_code == 404
    await client.put("/v1/org/auth", json=HMAC, headers=headers)
    inherited = (await client.get(f"{base}/effective-auth", headers=headers)).json()
    assert (inherited["source"], inherited["secret_set"]) == ("organization", True)
    put = await client.put(
        f"{base}/auth", json={**HMAC, "secret": NEW_SECRET}, headers=headers
    )
    assert put.status_code == 200 and NEW_SECRET not in put.text
    own = (await client.get(f"{base}/effective-auth", headers=headers)).json()
    assert own["source"] == "product"
    assert (await client.get(f"{base}/auth", headers=headers)).json()["rev"] == 1
    assert (await client.delete(f"{base}/auth", headers=headers)).status_code == 204
    assert (await client.get(f"{base}/auth", headers=headers)).status_code == 404
    assert (await client.delete("/v1/org/auth", headers=headers)).status_code == 204


async def test_v2ac5_test_token_returns_claims_or_reason_without_secret(
    client: httpx.AsyncClient, seed: Seed, keys: Keys, jwks: dict[str, Any]
) -> None:
    _, headers, _ = await acting(seed, keys)
    await client.put("/v1/org/auth", json=HMAC, headers=headers)
    good = await client.post(
        "/v1/org/auth/test", json={"token": hmac_token(team="a")}, headers=headers
    )
    assert good.json()["valid"] is True
    assert good.json()["claims"]["team"] == "a"
    bad = await client.post(
        "/v1/org/auth/test", json={"token": hmac_token(NEW_SECRET)}, headers=headers
    )
    assert bad.status_code == 200
    assert bad.json()["valid"] is False and bad.json()["reason"]
    assert SECRET not in bad.text and NEW_SECRET not in bad.text


async def test_v2ac7_members_added_by_username_and_email(
    client: httpx.AsyncClient,
    seed: Seed,
    keys: Keys,
    jwks: dict[str, Any],
    add_user: AddUser,
) -> None:
    _, headers, _ = await acting(seed, keys)
    by_name = await add_user("member-by-name")
    by_mail = await add_user("member-by-mail", "mail-me@example.com")
    r = await client.post(
        "/v1/org/members",
        json={"identifier": "member-by-name", "groups": ["writer"]},
        headers=headers,
    )
    assert (r.status_code, r.json()["user_id"]) == (201, by_name)
    r = await client.post(
        "/v1/org/members",
        json={"identifier": "mail-me@example.com", "groups": ["reader"]},
        headers=headers,
    )
    assert (r.status_code, r.json()["user_id"]) == (201, by_mail)
    again = await client.post(
        "/v1/org/members",
        json={"identifier": "member-by-name", "groups": []},
        headers=headers,
    )
    assert (again.status_code, again.json()["error"]) == (409, "already_member")
    listed = (await client.get("/v1/org/members", headers=headers)).json()["items"]
    row = next(m for m in listed if m["user_id"] == by_name)
    assert (row["username"], row["groups"]) == ("member-by-name", ["writer"])
    patched = await client.patch(
        f"/v1/org/members/{by_name}",
        json={"groups": ["reader", "writer"]},
        headers=headers,
    )
    assert patched.json()["groups"] == ["reader", "writer"]
    assert (
        await client.delete(f"/v1/org/members/{by_name}", headers=headers)
    ).status_code == 204
    assert (
        await client.delete(f"/v1/org/members/{by_name}", headers=headers)
    ).status_code == 404


async def test_v2ac7_unknown_identifier_is_generic_404_and_inexact_does_not_match(
    client: httpx.AsyncClient,
    seed: Seed,
    keys: Keys,
    jwks: dict[str, Any],
    add_user: AddUser,
) -> None:
    _, headers, _ = await acting(seed, keys)
    await add_user("exactname")
    for identifier in ("nobody-at-all", "exactnam", "EXACTNAME", "%", "exactname%"):
        r = await client.post(
            "/v1/org/members",
            json={"identifier": identifier, "groups": []},
            headers=headers,
        )
        assert r.status_code == 404
        assert r.json() == {"error": "not_found", "message": "user not found"}


async def test_v2ac7_group_changes_apply_on_next_request(
    client: httpx.AsyncClient,
    seed: Seed,
    keys: Keys,
    jwks: dict[str, Any],
    add_user: AddUser,
) -> None:
    org, admin, _ = await acting(seed, keys)
    user = await add_user("flip")
    await client.post(
        "/v1/org/members",
        json={"identifier": "flip", "groups": ["reader"]},
        headers=admin,
    )
    as_user = login_headers(keys, user, org.slug)
    assert (await client.get("/v1/org/products", headers=as_user)).status_code == 403
    await client.patch(
        f"/v1/org/members/{user}", json={"groups": ["org-admin"]}, headers=admin
    )
    assert (await client.get("/v1/org/products", headers=as_user)).status_code == 200


async def test_v2f_last_org_admin_cannot_be_removed_or_demoted(
    client: httpx.AsyncClient,
    seed: Seed,
    keys: Keys,
    jwks: dict[str, Any],
    platform_headers: dict[str, str],
) -> None:
    org, headers, admin = await acting(seed, keys)
    demote = await client.patch(
        f"/v1/org/members/{admin}", json={"groups": ["writer"]}, headers=headers
    )
    assert (demote.status_code, demote.json()["error"]) == (409, "last_admin")
    remove = await client.delete(f"/v1/org/members/{admin}", headers=headers)
    assert (remove.status_code, remove.json()["error"]) == (409, "last_admin")
    platform = {**platform_headers, "x-org": org.slug}
    ok = await client.patch(
        f"/v1/org/members/{admin}", json={"groups": ["writer"]}, headers=platform
    )
    assert ok.status_code == 200


async def test_v2f_capability_update_validates_and_blocks_self_lockout(
    client: httpx.AsyncClient,
    seed: Seed,
    keys: Keys,
    jwks: dict[str, Any],
    platform_headers: dict[str, str],
) -> None:
    org, headers, _ = await acting(seed, keys)
    ok = await client.put(
        "/v1/org/capabilities",
        json={"rules": {"registry-readers": '"reader" in token.groups'}},
        headers=headers,
    )
    assert ok.status_code == 200
    bad = await client.put(
        "/v1/org/capabilities",
        json={"rules": {"registry-admins": "token.groups =="}},
        headers=headers,
    )
    assert bad.status_code == 422
    unknown = await client.put(
        "/v1/org/capabilities", json={"rules": {"open-to-all": "true"}}, headers=headers
    )
    assert unknown.status_code == 422
    lockout = await client.put(
        "/v1/org/capabilities",
        json={"rules": {"registry-admins": '"someone-else" in token.groups'}},
        headers=headers,
    )
    assert (lockout.status_code, lockout.json()["error"]) == (409, "capability_lockout")
    platform = {**platform_headers, "x-org": org.slug}
    forced = await client.put(
        "/v1/org/capabilities",
        json={"rules": {"registry-admins": '"someone-else" in token.groups'}},
        headers=platform,
    )
    assert forced.status_code == 200
    assert (await client.get("/v1/org/products", headers=headers)).status_code == 403


async def test_v2ac8_every_org_write_is_audited(
    client: httpx.AsyncClient,
    seed: Seed,
    keys: Keys,
    jwks: dict[str, Any],
    add_user: AddUser,
    platform_headers: dict[str, str],
) -> None:
    org, headers, admin = await acting(seed, keys)
    await add_user("audited")
    product = (
        await client.post(
            "/v1/org/products", json={"slug": "au", "name": "A"}, headers=headers
        )
    ).json()["id"]
    await client.patch(
        f"/v1/org/products/{product}", json={"name": "B"}, headers=headers
    )
    await client.put("/v1/org/auth", json=HMAC, headers=headers)
    await client.put(f"/v1/org/products/{product}/auth", json=HMAC, headers=headers)
    await client.delete(f"/v1/org/products/{product}/auth", headers=headers)
    await client.delete("/v1/org/auth", headers=headers)
    member = (
        await client.post(
            "/v1/org/members",
            json={"identifier": "audited", "groups": []},
            headers=headers,
        )
    ).json()["user_id"]
    await client.patch(
        f"/v1/org/members/{member}", json={"groups": ["reader"]}, headers=headers
    )
    await client.delete(f"/v1/org/members/{member}", headers=headers)
    await client.put(
        "/v1/org/capabilities",
        json={"rules": {"registry-readers": '"reader" in token.groups'}},
        headers=headers,
    )
    audit = await client.get("/v1/admin/audit?limit=500", headers=platform_headers)
    mine = {a["action"] for a in audit.json()["items"] if a["tenant_id"] == str(org.id)}
    assert {
        "product.create",
        "product.update",
        "auth.set",
        "auth.delete",
        "product.auth.set",
        "product.auth.delete",
        "member.add",
        "member.update",
        "member.remove",
        "capabilities.update",
    } <= mine
    assert {
        a["actor"] for a in audit.json()["items"] if a["tenant_id"] == str(org.id)
    } == {admin}
