import json
import logging
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Route

from tests.e2e.conftest import make_user
from tests.e2e.test_walkthrough import principal_header, skill_zip
from tests.identity.conftest import Keys

SENTINEL = "SENTINEL-7f3a9c"


def concrete(path: str) -> str:
    for name in ("resource_id", "policy_id", "group_id", "link_id"):
        path = path.replace("{" + name + "}", str(uuid.uuid4()))
    return path.replace("{n}", "1")


def all_routes(app: FastAPI) -> list[Route | APIRoute]:
    found: list[Route | APIRoute] = []
    for route in app.routes:
        nested: Any = getattr(route, "original_router", None)
        candidates: list[Any] = nested.routes if nested is not None else [route]
        found.extend(r for r in candidates if isinstance(r, Route))
    return found


async def test_every_route_rejects_unauthenticated_requests(app: FastAPI) -> None:
    routes = all_routes(app)
    assert len(routes) > 30
    seen: list[tuple[str, str]] = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        for route in routes:
            for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
                r = await client.request(method, concrete(route.path))
                seen.append((method, route.path))
                assert r.status_code in (401, 404), (method, route.path, r.status_code)
                if r.status_code == 404:
                    assert route.path == "/metrics", (method, route.path, r.text)
    assert ("GET", "/v1/registry/search") in seen


async def test_no_request_data_reaches_the_logs(
    app: FastAPI,
    keys: Keys,
    onboarded: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    writer = make_user(
        app,
        keys,
        onboarded,
        "writer",
        groups=["grc-editors"],
        department=f"{SENTINEL}-claim",
    )
    admin = make_user(app, keys, onboarded, "admin", groups=["grc-admins"])
    async with writer, admin:
        r = await writer.post(
            "/v1/registry",
            json={
                "type": "agent",
                "slug": "sentinel-agent",
                "name": "Sentinel Agent",
                "visibility": "tenant",
                "spec": {
                    "model": "claude-sonnet-5-5",
                    "system_prompt": f"{SENTINEL}-prompt",
                },
            },
        )
        assert r.status_code == 201, r.text
        agent = r.json()["id"]
        assert (
            await writer.post(f"/v1/registry/{agent}/versions/1/publish")
        ).status_code == 200

        r = await writer.post(
            "/v1/registry",
            data={
                "metadata": json.dumps(
                    {
                        "type": "skill",
                        "slug": "refund-policy",
                        "name": "Refund Policy",
                    }
                )
            },
            files={
                "archive": (
                    "s.zip",
                    skill_zip(f"{SENTINEL}-skill-content"),
                    "application/zip",
                )
            },
        )
        assert r.status_code == 201, r.text
        skill = r.json()["id"]
        assert (
            await writer.post(f"/v1/registry/{skill}/versions/1/publish")
        ).status_code == 200
        assert (await writer.get(f"/v1/registry/{agent}/bundle")).status_code == 200
        assert (await writer.get(f"/v1/registry/{skill}/bundle")).status_code == 200
        r = await writer.get("/v1/registry/search", params={"q": f"{SENTINEL}-query"})
        assert r.status_code == 200
        r = await admin.post(
            "/v1/access-policies",
            json={"name": "p", "source": f'token.department == "{SENTINEL}-literal"'},
        )
        assert r.status_code == 201, r.text
        probe: dict[str, Any] = {"id": f"{SENTINEL}-principal"}
        r = await writer.get(
            "/v1/registry",
            headers={"X-Principal": principal_header(probe)},
        )
        assert r.status_code == 200

    assert [rec for rec in caplog.records if rec.name == "krep.request"]
    server = [rec for rec in caplog.records if rec.name != "httpx"]
    rendered = "".join(rec.getMessage() + repr(vars(rec)) for rec in server)
    assert SENTINEL not in rendered
