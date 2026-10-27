import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, LiteralString

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.api.deps import get_caller
from krep.api.errors import install_error_handlers
from krep.api.policies import router
from krep.config import Settings
from krep.db.pool import open_pool
from krep.identity.resolve import Caller
from tests.conftest import role_url

Pool = AsyncConnectionPool[AsyncConnection]
OwnerExec = Callable[..., Awaitable[None]]
MakeClient = Callable[..., httpx.AsyncClient]


@pytest_asyncio.fixture
async def pool(migrated_db: str) -> AsyncIterator[Pool]:
    settings = Settings(database_url=role_url("krep_app", migrated_db), migration_database_url="")
    async with await open_pool(settings, min_size=1, max_size=4) as pool:
        yield pool


@pytest_asyncio.fixture
async def owner_exec(migrated_db: str, tenant_id: uuid.UUID) -> AsyncIterator[OwnerExec]:
    async with await AsyncConnection.connect(
        role_url("krep_owner", migrated_db), autocommit=True
    ) as conn:
        await conn.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))

        async def run(query: LiteralString, params: tuple[Any, ...] = ()) -> None:
            await conn.execute(query, params)

        yield run


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def make_client(pool: Pool) -> MakeClient:
    def make(tenant: uuid.UUID, admin: bool = True, user: str = "u1") -> httpx.AsyncClient:
        app = FastAPI()
        app.state.pool = pool
        install_error_handlers(app)
        app.include_router(router)

        async def caller() -> Caller:
            return Caller(tenant, user, {"token": {}, "principal": {}}, admin, admin)

        app.dependency_overrides[get_caller] = caller
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        )

    return make


@pytest_asyncio.fixture
async def client(
    make_client: MakeClient, tenant_id: uuid.UUID
) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(tenant_id) as c:
        yield c
