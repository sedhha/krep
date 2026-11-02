import httpx
import pytest
from fastapi import FastAPI

from krep.api import metrics as metrics_api
from krep.api.errors import install_error_handlers
from krep.config import Settings
from krep.metrics import SEARCH_ZERO_RESULTS


def make_client(monkeypatch: pytest.MonkeyPatch, token: str) -> httpx.AsyncClient:
    settings = Settings(database_url="", migration_database_url="", metrics_token=token)
    monkeypatch.setattr(metrics_api, "get_settings", lambda: settings)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(metrics_api.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_metrics_disabled_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async with make_client(monkeypatch, "") as c:
        assert (await c.get("/metrics")).status_code == 404
        assert (await c.get("/metrics", headers={"Authorization": "Bearer "})).status_code == 404


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic s3cret"}]
)
async def test_metrics_rejects_missing_or_wrong_token(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    async with make_client(monkeypatch, "s3cret") as c:
        res = await c.get("/metrics", headers=headers)
        assert (res.status_code, res.json()["error"]) == (401, "unauthenticated")


async def test_metrics_serves_prometheus_text_with_valid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    SEARCH_ZERO_RESULTS.labels(tenant="tenant-for-metrics-test").inc()
    async with make_client(monkeypatch, "s3cret") as c:
        res = await c.get("/metrics", headers={"Authorization": "Bearer s3cret"})
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/plain")
        assert 'search_zero_results_total{tenant="tenant-for-metrics-test"} 1.0' in res.text
