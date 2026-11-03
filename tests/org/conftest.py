# pyright: reportUnusedImport=false
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.api.admin import router as admin_router
from krep.api.errors import install_error_handlers
from krep.api.org import router as org_router
from krep.config import Settings
from krep.db.pool import open_pool
from tests.conftest import role_url
from tests.identity.conftest import (  # noqa: F401
    PLATFORM_KEY,
    Keys,
    Org,
    Seed,
    add_policy,
    jwks,
    keys,
    login_headers,
    owner_exec,
    panel_env,
    pool,
    seed,
)

Pool = AsyncConnectionPool[AsyncConnection]
AddUser = Callable[..., Awaitable[str]]


@pytest_asyncio.fixture
async def platform_pool(migrated_db: str) -> AsyncIterator[Pool]:
    settings = Settings(
        database_url=role_url("krep_platform", migrated_db), migration_database_url=""
    )
    async with await open_pool(settings, min_size=1, max_size=2) as platform:
        yield platform


@pytest_asyncio.fixture
async def add_user(migrated_db: str) -> AsyncIterator[AddUser]:
    async with await AsyncConnection.connect(
        role_url("krep_auth", migrated_db), autocommit=True
    ) as conn:

        async def add(name: str | None = None, email: str | None = None) -> str:
            user_id = f"u-{uuid.uuid4().hex[:10]}"
            username = name or f"user-{uuid.uuid4().hex[:8]}"
            await conn.execute(
                'INSERT INTO auth."user" (id, username, email, name) VALUES (%s, %s, %s, %s)',
                (user_id, username, email or f"{username}@example.com", username),
            )
            return user_id

        yield add


@pytest.fixture
def make_client(
    pool: Pool,  # noqa: F811
    platform_pool: Pool,
) -> Callable[[], httpx.AsyncClient]:
    def make() -> httpx.AsyncClient:
        app = FastAPI()
        app.state.pool = pool
        app.state.platform_pool = platform_pool
        install_error_handlers(app)
        app.include_router(admin_router)
        app.include_router(org_router)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        )

    return make


@pytest_asyncio.fixture
async def client(
    make_client: Callable[[], httpx.AsyncClient],
) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client() as c:
        yield c


@pytest.fixture
def platform_headers(panel_env: None) -> dict[str, str]:  # noqa: F811
    return {"x-platform-key": PLATFORM_KEY}


def org_body(slug: str, admin_user: str, **extra: Any) -> dict[str, Any]:
    return {"slug": slug, "name": "Acme", "admin_user": admin_user, **extra}


def new_slug() -> str:
    return f"org-{uuid.uuid4().hex[:10]}"
