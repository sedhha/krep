from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request

from krep.api.admin import router as admin_router
from krep.api.errors import install_error_handlers
from krep.api.limits import router as limits_router
from krep.api.links import router as links_router
from krep.api.logging import install_request_logging
from krep.api.metrics import router as metrics_router
from krep.api.org import router as org_router
from krep.api.policies import router as policies_router
from krep.api.registry import router as registry_router
from krep.api.search import router as search_router
from krep.api.versions import router as versions_router
from krep.config import get_settings
from krep.db.pool import open_platform_pool, open_pool
from krep.identity.selector import describe_me


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    pool = await open_pool(settings)
    platform_pool = await open_platform_pool(settings)
    app.state.pool = pool
    app.state.platform_pool = platform_pool
    try:
        yield
    finally:
        await pool.close()
        if platform_pool is not None:
            await platform_pool.close()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    install_error_handlers(app)
    install_request_logging(app)
    app.include_router(metrics_router)
    app.include_router(policies_router)
    app.include_router(limits_router)
    app.include_router(search_router)
    app.include_router(registry_router)
    app.include_router(versions_router)
    app.include_router(links_router)
    app.include_router(admin_router)
    app.include_router(org_router)

    @app.get("/v1/me")
    async def me(request: Request) -> dict[str, Any]:
        return await describe_me(request.app.state.pool, request.headers)

    return app


app = create_app()
