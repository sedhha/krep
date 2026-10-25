import os
import subprocess
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
HOST = os.environ.get("KREP_TEST_DB_HOST", "localhost:5432")
SUPERUSER_URL = f"postgresql://postgres:dev@{HOST}/postgres"


def role_url(role: str, database: str) -> str:
    return f"postgresql://{role}:dev@{HOST}/{database}"


def alembic(database: str, *args: str) -> None:
    env = {
        **os.environ,
        "KREP_MIGRATION_DATABASE_URL": role_url("krep_owner", database).replace(
            "postgresql://", "postgresql+psycopg://"
        ),
    }
    subprocess.run(["uv", "run", "alembic", *args], cwd=ROOT, env=env, check=True)


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    name = f"krep_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(SUPERUSER_URL, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER krep_owner").format(sql.Identifier(name))
        )
    with psycopg.connect(
        f"postgresql://postgres:dev@{HOST}/{name}", autocommit=True
    ) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        conn.execute("ALTER SCHEMA public OWNER TO krep_owner")
        conn.execute("GRANT USAGE ON SCHEMA public TO krep_app")
    alembic(name, "upgrade", "head")
    yield name
    with psycopg.connect(SUPERUSER_URL, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


@pytest_asyncio.fixture
async def owner_conn(migrated_db: str) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(
        role_url("krep_owner", migrated_db)
    ) as conn:
        yield conn
        await conn.rollback()


@pytest_asyncio.fixture
async def app_conn(migrated_db: str) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(
        role_url("krep_app", migrated_db)
    ) as conn:
        yield conn
        await conn.rollback()
