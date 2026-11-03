from typing import Any

import httpx
import psycopg
import pytest

from krep.config import get_settings
from tests.conftest import role_url
from tests.org.conftest import Keys, Org, Seed, login_headers

ADMIN = "/v1/admin/organizations"


async def acting_member(seed: Seed, org: Org, keys: Keys) -> dict[str, str]:
    user = f"admin-{org.slug}"
    await seed.member(org, user, ["org-admin"])
    return login_headers(keys, user, org.slug)


async def post(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    org: Org,
    action: str,
    body: dict[str, Any] | None = None,
) -> httpx.Response:
    return await client.post(f"{ADMIN}/{org.id}/{action}", json=body, headers=headers)


def audit_actions(migrated_db: str, org: Org) -> list[str]:
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT action FROM admin_audit_log WHERE tenant_id = %s ORDER BY id",
                (org.id,),
            ).fetchall()
        ]


async def test_v2ac16_suspend_blocks_every_request_and_activate_restores(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    keys: Keys,
    jwks: dict[str, Any],
    migrated_db: str,
) -> None:
    org = await seed.org()
    headers = await acting_member(seed, org, keys)
    assert (await client.get("/v1/org/products", headers=headers)).status_code == 200

    r = await post(client, platform_headers, org, "suspend")
    assert r.status_code == 200
    assert r.json()["status"] == "suspended"
    denied = await client.get("/v1/org/products", headers=headers)
    assert denied.status_code == 401
    assert denied.json()["error"] == "unauthenticated"

    r = await post(client, platform_headers, org, "activate")
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    assert (await client.get("/v1/org/products", headers=headers)).status_code == 200
    assert audit_actions(migrated_db, org) == ["org.suspend", "org.activate"]


async def test_v2ac16_schedule_and_cancel_delete(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    migrated_db: str,
) -> None:
    org = await seed.org()
    r = await post(client, platform_headers, org, "schedule-delete", {"grace_days": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending_delete"
    assert body["delete_after"] is not None
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        days = conn.execute(
            "SELECT round(extract(epoch FROM delete_after - now()) / 86400) "
            "FROM organizations WHERE id = %s",
            (org.id,),
        ).fetchone()
    assert days == (10,)

    r = await post(client, platform_headers, org, "cancel-delete")
    assert r.status_code == 200
    assert r.json()["status"] == "suspended"
    assert r.json()["delete_after"] is None
    assert audit_actions(migrated_db, org) == [
        "org.schedule_delete",
        "org.cancel_delete",
    ]


async def test_v2ac16_schedule_delete_defaults_to_configured_grace(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    migrated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = await seed.org()
    r = await post(client, platform_headers, org, "schedule-delete")
    assert r.status_code == 200
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        days = conn.execute(
            "SELECT round(extract(epoch FROM delete_after - now()) / 86400) "
            "FROM organizations WHERE id = %s",
            (org.id,),
        ).fetchone()
    assert days == (30,)

    other = await seed.org()
    monkeypatch.setenv("KREP_ORG_DELETE_GRACE_DAYS", "7")
    get_settings.cache_clear()
    r = await post(client, platform_headers, other, "schedule-delete")
    assert r.status_code == 200
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        days = conn.execute(
            "SELECT round(extract(epoch FROM delete_after - now()) / 86400) "
            "FROM organizations WHERE id = %s",
            (other.id,),
        ).fetchone()
    assert days == (7,)


@pytest.mark.parametrize("grace", [91, 365])
async def test_v2ac16_grace_above_ninety_days_is_422(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    grace: int,
) -> None:
    org = await seed.org()
    r = await post(
        client, platform_headers, org, "schedule-delete", {"grace_days": grace}
    )
    assert r.status_code == 422
    r = await client.get(f"{ADMIN}/{org.id}", headers=platform_headers)
    assert r.json()["status"] == "active"


@pytest.mark.parametrize("grace", [0, -1])
async def test_v2ac16_grace_below_one_day_is_422(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    grace: int,
) -> None:
    org = await seed.org()
    r = await post(
        client, platform_headers, org, "schedule-delete", {"grace_days": grace}
    )
    assert r.status_code == 422


async def test_v2ac16_grace_of_ninety_days_is_accepted(
    client: httpx.AsyncClient, platform_headers: dict[str, str], seed: Seed
) -> None:
    org = await seed.org()
    r = await post(client, platform_headers, org, "schedule-delete", {"grace_days": 90})
    assert r.status_code == 200


@pytest.mark.parametrize(
    ("status", "action"),
    [
        ("active", "activate"),
        ("active", "cancel-delete"),
        ("suspended", "suspend"),
        ("suspended", "cancel-delete"),
        ("pending_delete", "suspend"),
        ("pending_delete", "activate"),
        ("pending_delete", "schedule-delete"),
    ],
)
async def test_v2ac16_invalid_transitions_are_409(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    status: str,
    action: str,
) -> None:
    org = await seed.org(status=status)
    r = await post(client, platform_headers, org, action)
    assert r.status_code == 409
    assert r.json()["error"] == "invalid_state"
    after = await client.get(f"{ADMIN}/{org.id}", headers=platform_headers)
    assert after.json()["status"] == status


async def test_v2ac16_schedule_delete_from_suspended_is_allowed(
    client: httpx.AsyncClient, platform_headers: dict[str, str], seed: Seed
) -> None:
    org = await seed.org(status="suspended")
    r = await post(client, platform_headers, org, "schedule-delete")
    assert r.status_code == 200
    assert r.json()["status"] == "pending_delete"


async def test_v2ac16_legal_hold_toggles_in_any_state_and_is_audited(
    client: httpx.AsyncClient,
    platform_headers: dict[str, str],
    seed: Seed,
    migrated_db: str,
) -> None:
    org = await seed.org(status="pending_delete")
    r = await client.put(
        f"{ADMIN}/{org.id}/legal-hold",
        json={"legal_hold": True},
        headers=platform_headers,
    )
    assert r.status_code == 200
    assert r.json()["legal_hold"] is True
    r = await client.put(
        f"{ADMIN}/{org.id}/legal-hold",
        json={"legal_hold": False},
        headers=platform_headers,
    )
    assert r.json()["legal_hold"] is False
    assert audit_actions(migrated_db, org) == ["org.legal_hold", "org.legal_hold"]


async def test_v2ac16_lifecycle_routes_for_unknown_organization_are_404(
    client: httpx.AsyncClient, platform_headers: dict[str, str]
) -> None:
    missing = "00000000-0000-4000-8000-000000000000"
    for action in ("suspend", "activate", "schedule-delete", "cancel-delete"):
        r = await client.post(f"{ADMIN}/{missing}/{action}", headers=platform_headers)
        assert r.status_code == 404
    r = await client.put(
        f"{ADMIN}/{missing}/legal-hold",
        json={"legal_hold": True},
        headers=platform_headers,
    )
    assert r.status_code == 404


async def test_v2ac16_platform_organization_is_protected(
    client: httpx.AsyncClient, platform_headers: dict[str, str], migrated_db: str
) -> None:
    with psycopg.connect(role_url("krep_owner", migrated_db)) as conn:
        row = conn.execute("SELECT id FROM organizations WHERE is_platform").fetchone()
    assert row is not None
    for action in ("suspend", "schedule-delete"):
        r = await client.post(f"{ADMIN}/{row[0]}/{action}", headers=platform_headers)
        assert r.status_code == 409
        assert r.json()["error"] == "platform_organization_protected"


async def test_v2ac6_lifecycle_routes_require_platform_admin(
    client: httpx.AsyncClient, seed: Seed, keys: Keys, jwks: dict[str, Any]
) -> None:
    org = await seed.org()
    headers = await acting_member(seed, org, keys)
    for action in ("suspend", "activate", "schedule-delete", "cancel-delete"):
        r = await client.post(f"{ADMIN}/{org.id}/{action}", headers=headers)
        assert r.status_code == 403
    r = await client.put(
        f"{ADMIN}/{org.id}/legal-hold", json={"legal_hold": True}, headers=headers
    )
    assert r.status_code == 403
