import base64
import hashlib
import io
import json
import uuid
import zipfile
from typing import Any

import httpx
from fastapi import FastAPI
from psycopg import AsyncConnection

from tests.conftest import role_url
from tests.e2e.conftest import make_user, open_policy_id
from tests.identity.conftest import Keys

TOKEN_CLAUSE = (
    'token.department == "billing" && ("manager" in token.roles || "support-lead" in token.roles)'
    ' && !("contractors" in token.groups)'
)
PRINCIPAL_CLAUSE = (
    'principal.department == "billing" && ("manager" in principal.roles'
    ' || "support-lead" in principal.roles) && !("contractors" in principal.groups)'
)


def skill_zip(body: str) -> bytes:
    md = f"---\nname: refund-policy\ndescription: Refund rules.\n---\n# Refunds\n{body}\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("refund-policy/SKILL.md", md)
    return buf.getvalue()


def principal_header(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


async def test_walkthrough_steps_0_to_11(
    app: FastAPI,
    keys: Keys,
    onboarded: str,
    tenant: uuid.UUID,
    migrated_db: str,
) -> None:
    open_id = await open_policy_id(migrated_db, tenant)
    admin = make_user(app, keys, onboarded, "admin", groups=["grc-admins"])
    ravi = make_user(app, keys, onboarded, "ravi", groups=["grc-editors"])
    priya = make_user(app, keys, onboarded, "priya", groups=["grc-editors"])
    billing = make_user(
        app, keys, onboarded, "caller-1", department="billing", roles=["manager"]
    )
    contractor = make_user(
        app,
        keys,
        onboarded,
        "caller-2",
        department="billing",
        roles=["manager"],
        groups=["contractors"],
    )

    async with admin, ravi, priya, billing, contractor:
        r = await admin.post(
            "/v1/access-policies",
            json={"name": "Billing leads", "source": TOKEN_CLAUSE},
        )
        assert r.status_code == 201, r.text
        p1 = r.json()

        r = await ravi.post(
            "/v1/registry",
            json={
                "type": "agent",
                "slug": "refund-assistant",
                "name": "Refund Assistant",
                "description": "Answers refund questions.",
                "spec": {"model": "claude-sonnet-5-5", "system_prompt": "You help."},
            },
        )
        assert r.status_code == 201, r.text
        a1 = r.json()["id"]

        archive = skill_zip("v1")
        r = await priya.post(
            "/v1/registry",
            data={
                "metadata": json.dumps(
                    {
                        "type": "skill",
                        "slug": "refund-policy",
                        "name": "Refund Policy",
                        "policies": {"read": [open_id]},
                    }
                )
            },
            files={"archive": ("s.zip", archive, "application/zip")},
        )
        assert r.status_code == 201, r.text
        s1 = r.json()["id"]
        r = await priya.post(f"/v1/registry/{s1}/versions/1/publish")
        assert r.status_code == 200, r.text
        assert r.json()["current_version"] == 1

        r = await ravi.post(
            f"/v1/registry/{a1}/links",
            json={
                "other_id": s1,
                "relation": "uses",
                "direction": "out",
                "auto_load": True,
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "accepted"

        r = await ravi.patch(
            f"/v1/registry/{a1}",
            json={"policies": {"read": [p1["id"]]}},
        )
        assert r.status_code == 200, r.text

        r = await ravi.post(f"/v1/registry/{a1}/versions/1/publish")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "published"
        async with await AsyncConnection.connect(
            role_url("krep_owner", migrated_db), autocommit=True
        ) as conn:
            await conn.execute(
                "SELECT set_config('app.tenant_id', %s, false)", (str(tenant),)
            )
            cur = await conn.execute(
                "SELECT t.version FROM registry_version_deps d "
                "JOIN registry_versions v ON v.id = d.version_id "
                "JOIN registry_versions t ON t.id = d.depends_on_version_id "
                "WHERE v.registry_id = %s AND v.version = 1",
                (a1,),
            )
            assert [row[0] for row in await cur.fetchall()] == [1]

        r = await billing.get(
            "/v1/registry/search", params={"q": "refund", "type": "agent"}
        )
        assert r.status_code == 200
        assert [i["slug"] for i in r.json()["items"]] == ["refund-assistant"]

        r = await billing.get(f"/v1/registry/{a1}/bundle")
        assert r.status_code == 200, r.text
        bundle = r.json()
        assert bundle["root"]["version"] == 1
        assert [d["version"] for d in bundle["dependencies"]] == [1]

        r = await contractor.get(
            "/v1/registry/search", params={"q": "refund", "type": "agent"}
        )
        assert r.status_code == 200
        assert r.json()["items"] == []
        assert (await contractor.get(f"/v1/registry/{a1}")).status_code == 404

        r = await admin.put(
            f"/v1/access-policies/{p1['id']}",
            json={
                "name": "Billing leads",
                "source": f"{TOKEN_CLAUSE} || {PRINCIPAL_CLAUSE}",
                "rev": p1["rev"],
            },
        )
        assert r.status_code == 200, r.text

        key = uuid.uuid4().hex + uuid.uuid4().hex
        async with await AsyncConnection.connect(
            role_url("krep_owner", migrated_db), autocommit=True
        ) as conn:
            await conn.execute(
                "INSERT INTO api_keys (id, tenant_id, name, key_hash, allow_principal) "
                "VALUES (%s, %s, 'backend', %s, true)",
                (uuid.uuid4(), tenant, hashlib.sha256(key.encode()).digest()),
            )

        def backend(principal: dict[str, Any]) -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://t",
                headers={"X-API-Key": key, "X-Principal": principal_header(principal)},
            )

        allowed = {"id": "user-9", "roles": ["manager"], "department": "billing"}
        async with backend(allowed) as c:
            r = await c.get(
                "/v1/registry/search", params={"q": "refund", "type": "agent"}
            )
            assert [i["slug"] for i in r.json()["items"]] == ["refund-assistant"]
            r = await c.get(f"/v1/registry/{a1}/bundle")
            assert r.status_code == 200
            assert [d["version"] for d in r.json()["dependencies"]] == [1]

        async with backend({**allowed, "groups": ["contractors"]}) as c:
            r = await c.get(
                "/v1/registry/search", params={"q": "refund", "type": "agent"}
            )
            assert r.json()["items"] == []
            assert (await c.get(f"/v1/registry/{a1}")).status_code == 404

        r = await priya.post(
            f"/v1/registry/{s1}/versions",
            files={"archive": ("s.zip", skill_zip("v2"), "application/zip")},
        )
        assert r.status_code == 201, r.text
        r = await priya.post(f"/v1/registry/{s1}/versions/2/publish")
        assert r.status_code == 200, r.text

        r = await billing.get(f"/v1/registry/{a1}/bundle", params={"version": 1})
        assert [d["version"] for d in r.json()["dependencies"]] == [1]

        r = await ravi.post(f"/v1/registry/{a1}/versions")
        assert r.status_code == 201, r.text
        assert r.json()["version"]["version"] == 2
        r = await ravi.post(f"/v1/registry/{a1}/versions/2/publish")
        assert r.status_code == 200, r.text
        r = await billing.get(f"/v1/registry/{a1}/bundle")
        assert r.json()["root"]["version"] == 2
        assert [d["version"] for d in r.json()["dependencies"]] == [2]
