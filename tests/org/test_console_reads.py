import asyncio

import httpx
import pytest
from psycopg import AsyncConnection

from krep.registry.resources import delete_resource
from tests.conftest import role_url
from tests.org.conftest import AddUser, Pool, Seed
from tests.org.test_purge import caller_for, link_and_publish, make_resource


async def test_v2ac16_console_reads_suspended_members_auth_and_blockers(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    add_user: AddUser,
) -> None:
    org = await seed.org()
    uid = await add_user()
    await seed.member(org, uid, ["org-admin"])
    base = f"/v1/admin/organizations/{org.id}"
    assert (
        await client.post(f"{base}/suspend", headers=platform_headers)
    ).status_code == 200
    members = await client.get(f"{base}/members", headers=platform_headers)
    assert members.status_code == 200
    assert members.json()["items"][0]["user_id"] == uid
    blockers = await client.get(f"{base}/purge-blockers", headers=platform_headers)
    assert blockers.status_code == 200
    assert blockers.json() == {"legal_hold": False, "items": []}
    await client.put(
        f"{base}/legal-hold", json={"legal_hold": True}, headers=platform_headers
    )
    assert (
        await client.get(f"{base}/purge-blockers", headers=platform_headers)
    ).json()["legal_hold"]
    assert (
        await client.get(f"{base}/auth", headers=platform_headers)
    ).status_code == 404


async def test_v2ac6_user_status_counts_memberships_in_every_organization(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    add_user: AddUser,
) -> None:
    uid = await add_user()
    path = f"/v1/admin/users/{uid}"
    response = await client.get(path, headers=platform_headers)
    assert response.status_code == 200
    assert response.json() == {
        "user_id": uid,
        "is_platform_admin": False,
        "memberships": [],
        "is_orphan": True,
        "disabled": False,
    }
    org = await seed.org()
    await seed.member(org, uid, ["reader"])
    response = await client.get(path, headers=platform_headers)
    assert response.json()["memberships"] == [str(org.id)]
    assert not response.json()["is_orphan"]
    await client.delete(
        f"/v1/admin/organizations/{org.id}/members/{uid}", headers=platform_headers
    )
    await client.put(f"/v1/admin/platform-admins/{uid}", headers=platform_headers)
    response = await client.get(path, headers=platform_headers)
    assert response.json()["is_platform_admin"]
    assert not response.json()["is_orphan"]
    assert (
        await client.get("/v1/admin/users/unknown", headers=platform_headers)
    ).status_code == 404


async def test_v2ac6_console_reads_require_platform_credentials(
    client: httpx.AsyncClient,
    seed: Seed,
) -> None:
    org = await seed.org()
    for path in [
        f"/v1/admin/organizations/{org.id}/members",
        f"/v1/admin/organizations/{org.id}/auth",
        f"/v1/admin/organizations/{org.id}/purge-blockers",
        "/v1/admin/users/any",
    ]:
        assert (await client.get(path)).status_code == 401


async def test_v2ac6_identity_operations_record_only_action_and_target(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    add_user: AddUser,
) -> None:
    uid = await add_user()
    path = f"/v1/admin/users/{uid}/identity-audit"
    response = await client.post(
        path, headers=platform_headers, json={"action": "password_reset"}
    )
    assert response.status_code == 204
    rows = (await client.get("/v1/admin/audit", headers=platform_headers)).json()[
        "items"
    ]
    assert rows[0]["action"] == "user.password_reset"
    assert rows[0]["target"] == uid
    assert rows[0]["detail"] is None
    assert (
        await client.post(path, headers=platform_headers, json={"action": "anything"})
    ).status_code == 422


async def test_v2ac16_console_reports_foreign_global_resource_references(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    pool: Pool,
) -> None:
    owner = await seed.org()
    consumer = await seed.org()
    skill = await make_resource(pool, owner, "skill", "shared", global_scope=True)
    agent = await make_resource(pool, consumer, "agent", "consumer")
    await link_and_publish(pool, consumer, agent, skill)
    try:
        response = await client.get(
            f"/v1/admin/organizations/{owner.id}/purge-blockers",
            headers=platform_headers,
        )
        assert response.status_code == 200
        assert response.json() == {
            "legal_hold": False,
            "items": [
                {
                    "resource": "shared",
                    "organization": consumer.slug,
                    "kind": "link",
                    "referrers": 1,
                },
                {
                    "resource": "shared",
                    "organization": consumer.slug,
                    "kind": "version_dep",
                    "referrers": 1,
                },
            ],
        }
    finally:
        for org, resource in ((consumer, agent), (owner, skill)):
            async with pool.connection() as conn, conn.transaction():
                await conn.execute(
                    "SELECT set_config('app.tenant_id', %s, true)", (str(org.id),)
                )
                await delete_resource(conn, caller_for(org), resource)


@pytest.mark.parametrize("operation", ["attach", "grant", "create", "org-add"])
async def test_v2ac6_identity_deletion_lock_serializes_new_grants(
    operation: str,
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    add_user: AddUser,
    migrated_db: str,
) -> None:
    username = f"locked-{operation}"
    uid = await add_user(username)
    org = await seed.org()
    headers = dict(platform_headers)
    if operation == "attach":
        method, path, body = (
            "PUT",
            f"/v1/admin/organizations/{org.id}/members/{uid}",
            {"groups": ["reader"]},
        )
    elif operation == "grant":
        method, path, body = "PUT", f"/v1/admin/platform-admins/{uid}", None
    elif operation == "create":
        method, path, body = (
            "POST",
            "/v1/admin/organizations",
            {"slug": f"locked-{operation}", "name": "Locked", "admin_user": username},
        )
    else:
        headers["x-org"] = org.slug
        method, path, body = (
            "POST",
            "/v1/org/members",
            {"identifier": username, "groups": ["reader"]},
        )
    async with await AsyncConnection.connect(
        role_url("krep_auth", migrated_db)
    ) as identity:
        await identity.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (uid,)
        )
        task = asyncio.create_task(
            client.request(method, path, json=body, headers=headers)
        )
        done, _ = await asyncio.wait([task], timeout=0.1)
        try:
            assert not done, "grant must wait for identity deletion's lock"
            await identity.execute('DELETE FROM auth."user" WHERE id = %s', (uid,))
        finally:
            await identity.commit()
        response = await task
        assert response.status_code == (422 if operation == "create" else 404)


async def test_v2ac6_audit_defaults_to_latest_100_and_api_can_fetch_more(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    platform_pool: Pool,
) -> None:
    async with platform_pool.connection() as conn, conn.transaction():
        cur = await conn.execute(
            "INSERT INTO admin_audit_log (actor, action, target) "
            "SELECT 'audit-limit-test', 'test.audit', n::text "
            "FROM generate_series(1, 130) AS n RETURNING id"
        )
        ids = sorted((row[0] for row in await cur.fetchall()), reverse=True)
    default = await client.get("/v1/admin/audit", headers=platform_headers)
    assert default.status_code == 200
    assert [row["id"] for row in default.json()["items"]] == ids[:100]
    expanded = await client.get("/v1/admin/audit?limit=130", headers=platform_headers)
    assert [row["id"] for row in expanded.json()["items"]] == ids
    older = await client.get(
        f"/v1/admin/audit?before={ids[99]}", headers=platform_headers
    )
    assert [row["id"] for row in older.json()["items"]][:30] == ids[100:]
