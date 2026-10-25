import psycopg
import pytest
from psycopg import AsyncConnection

from tests.conftest import alembic, role_url


async def test_ac28_downgrade_base_then_upgrade_head(scratch_db: str) -> None:
    alembic(scratch_db, "upgrade", "head")
    alembic(scratch_db, "downgrade", "base")
    with psycopg.connect(role_url("krep_owner", scratch_db)) as conn:
        remaining = conn.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
        ).fetchone()
        assert remaining == (0,)
    alembic(scratch_db, "upgrade", "head")
    with psycopg.connect(role_url("krep_owner", scratch_db)) as conn:
        assert conn.execute("SELECT count(*) FROM registry_types").fetchone() == (2,)


async def test_seed_registry_types(owner_conn: AsyncConnection) -> None:
    cur = await owner_conn.execute("SELECT type, subtype_table FROM registry_types")
    assert set(await cur.fetchall()) == {("agent", "agents"), ("skill", "skills")}


async def test_seed_link_rules(owner_conn: AsyncConnection) -> None:
    cur = await owner_conn.execute(
        "SELECT source_type, target_type, relation, auto_load_allowed, accept_by "
        "FROM link_rules"
    )
    assert await cur.fetchall() == [("agent", "skill", "uses", True, "source")]


async def test_seed_global_limits(owner_conn: AsyncConnection) -> None:
    cur = await owner_conn.execute(
        "SELECT limit_key, value FROM resource_limits "
        "WHERE scope_type = 'global' AND resource_type IS NULL"
    )
    assert dict(await cur.fetchall()) == {
        "max_drafts": 50,
        "max_published_versions": 10,
        "max_policies": 500,
        "max_policy_nodes": 100,
        "max_synonym_groups": 200,
        "max_policy_history": 20,
    }


@pytest.mark.parametrize("table", ["registry_types", "link_rules", "resource_limits"])
async def test_seed_is_removed_on_downgrade_of_0004(scratch_db: str, table: str) -> None:
    alembic(scratch_db, "upgrade", "head")
    alembic(scratch_db, "downgrade", "0003")
    with psycopg.connect(role_url("krep_owner", scratch_db)) as conn:
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # type: ignore[arg-type]
        assert row == (0,)
