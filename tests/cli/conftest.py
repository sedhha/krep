import uuid
from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from tests.conftest import role_url

ADMIN_RULE = 'token.groups == "grc-admins"'
WRITER_RULE = 'token.groups == "grc-editors"'


@pytest.fixture
def cli_db(migrated_db: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("KREP_MIGRATION_DATABASE_URL", role_url("krep_owner", migrated_db))
    return migrated_db


@pytest.fixture
def tenant() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def query(cli_db: str) -> Callable[..., list[tuple[Any, ...]]]:
    def run(sql: str, *params: Any) -> list[tuple[Any, ...]]:
        with psycopg.connect(role_url("postgres", cli_db)) as conn:
            return conn.execute(sql, params).fetchall()

    return run
