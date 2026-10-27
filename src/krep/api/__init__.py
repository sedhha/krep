from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from krep.api.errors import install_error_handlers
from krep.api.limits import router as limits_router
from krep.api.logging import install_request_logging
from krep.api.policies import router as policies_router
from krep.config import get_settings
from krep.db.pool import open_pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    pool = await open_pool(get_settings())
    app.state.pool = pool
    try:
        yield
    finally:
        await pool.close()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    install_error_handlers(app)
    install_request_logging(app)
    app.include_router(policies_router)
    app.include_router(limits_router)
    return app


app = create_app()
