import logging

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import BaseModel

from krep.api import app as krep_app
from krep.api.errors import ApiError, install_error_handlers
from krep.api.logging import install_request_logging


class Body(BaseModel):
    slug: str
    count: int


def build_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    install_request_logging(app)

    @app.get("/boom")
    async def boom() -> None:
        raise ApiError(409, "slug_taken", "slug already exists", slug="x")

    @app.post("/validate")
    async def validate(body: Body) -> None:
        return None

    @app.get("/who/{item}")
    async def who(item: str, request: Request) -> dict[str, str]:
        request.state.tenant_id = "tenant-1"
        request.state.user_id = "user-1"
        return {"ok": "yes"}

    return app


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_api_error_renders_documented_shape() -> None:
    async with client(build_app()) as c:
        r = await c.get("/boom")
    assert r.status_code == 409
    assert r.json() == {"error": "slug_taken", "message": "slug already exists", "slug": "x"}


async def test_validation_error_renders_errors_list() -> None:
    async with client(build_app()) as c:
        r = await c.post("/validate", json={"slug": "ok", "count": "nope"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "validation_failed"
    assert body["errors"][0]["field"] == "count"
    assert isinstance(body["errors"][0]["message"], str)


async def test_request_log_has_five_fields_and_no_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="krep.request")
    async with client(build_app()) as c:
        await c.get(
            "/who/abc",
            headers={"Authorization": "Bearer SENTINEL-TOKEN", "X-Claim": "SENTINEL-CLAIM"},
        )
    records = [r for r in caplog.records if r.name == "krep.request"]
    assert len(records) == 1
    rec = vars(records[0])
    assert rec["tenant_id"] == "tenant-1"
    assert rec["user_id"] == "user-1"
    assert rec["route"] == "/who/{item}"
    assert rec["status"] == 200
    assert rec["latency_ms"] >= 0
    assert "SENTINEL" not in repr(rec)
    assert "SENTINEL" not in caplog.text


async def test_request_log_unauthenticated_fields_are_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="krep.request")
    async with client(build_app()) as c:
        await c.get("/boom")
    rec = vars([r for r in caplog.records if r.name == "krep.request"][0])
    assert rec["tenant_id"] is None and rec["user_id"] is None and rec["status"] == 409


def test_exported_app_is_fastapi() -> None:
    assert isinstance(krep_app, FastAPI)
