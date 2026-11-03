import asyncio
import hashlib
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import psycopg
import pytest
import pytest_asyncio
from psycopg import AsyncConnection, sql

from krep.cli import main
from krep.identity.resolve import Caller
from krep.jobs import PurgeResult, purge_due
from krep.policy.parser import parse
from krep.policy.store import write_policy
from krep.registry.links import create_link
from krep.registry.publish import publish
from krep.registry.resources import create_resource, delete_resource, update_resource
from tests.conftest import role_url
from tests.org.conftest import AddUser, Keys, Org, Pool, Seed, login_headers
from tests.registry.conftest import agent_body, open_policy, skill_body

ORG_ONLY_TABLES = ("admin_audit_log",)


def caller_for(org: Org) -> Caller:
    return Caller(org.id, "owner", {"token": {}, "principal": {}}, True, True)


@pytest_asyncio.fixture
async def job_conn(migrated_db: str) -> AsyncIterator[AsyncConnection]:
    async with await AsyncConnection.connect(
        role_url("krep_owner", migrated_db), autocommit=True
    ) as conn:
        yield conn


async def make_resource(
    pool: Pool, org: Org, kind: str, slug: str, *, global_scope: bool = False
) -> uuid.UUID:
    caller = caller_for(org)
    async with pool.connection() as conn, conn.transaction():
        await conn.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (str(org.id),)
        )
        policy = await open_policy(conn, org.id)
        extra: dict[str, Any] = {"scope": "org", "policies": {"read": [policy]}}
        body = (
            agent_body(slug, **extra)
            if kind == "agent"
            else {**skill_body(slug), **extra}
        )
        rid: uuid.UUID = (await create_resource(conn, caller, body))["id"]
        if kind == "skill":
            await publish(conn, caller, rid, 1)
        if global_scope:
            await conn.execute("SELECT set_config('app.platform_admin', 'on', true)")
            await update_resource(conn, caller, rid, {"scope": "global"})
    return rid


async def link_and_publish(
    pool: Pool, org: Org, agent: uuid.UUID, target: uuid.UUID
) -> None:
    caller = caller_for(org)
    async with pool.connection() as conn, conn.transaction():
        await conn.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (str(org.id),)
        )
        await create_link(conn, caller, agent, target, "uses", "out", None, False)
        await publish(conn, caller, agent, 1)


async def populate(
    pool: Pool,
    seed: Seed,
    org: Org,
    owner: AsyncConnection,
    add_user: AddUser,
    *,
    global_skill: bool = False,
) -> dict[str, uuid.UUID]:
    skill = await make_resource(
        pool, org, "skill", "base-skill", global_scope=global_skill
    )
    agent = await make_resource(pool, org, "agent", "main-agent")
    await link_and_publish(pool, org, agent, skill)
    product = await seed.product(org)
    await seed.hmac(org, "s" * 40, audience="krep")
    await seed.member(org, await add_user(), ["org-admin"])
    async with pool.connection() as conn, conn.transaction():
        await conn.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (str(org.id),)
        )
        await write_policy(
            conn, org.id, "custom", parse('token.groups == "x"'), "owner"
        )
        await write_policy(
            conn, org.id, "custom", parse('token.groups == "y"'), "owner"
        )
        await conn.execute(
            "INSERT INTO search_synonyms (tenant_id, terms, created_by) "
            "VALUES (%s, ARRAY['a','b'], 'owner')",
            (org.id,),
        )
    await owner.execute(
        "INSERT INTO resource_limits (scope_type, scope_id, resource_type, limit_key, value) "
        "VALUES ('tenant', %s, NULL, 'max_synonym_groups', 3), ('org', %s, NULL, 'max_synonym_groups', 4), "
        "('product', %s, NULL, 'max_synonym_groups', 5)",
        (str(org.id), str(org.id), str(product)),
    )
    await owner.execute(
        "INSERT INTO api_keys (tenant_id, name, key_hash) VALUES (%s, 'k', %s)",
        (org.id, hashlib.sha256(org.slug.encode()).digest()),
    )
    await owner.execute(
        "INSERT INTO token_issuers (issuer, audience, jwks_uri, tenant_id) "
        "VALUES (%s, 'aud', 'https://idp.example.com/jwks', %s)",
        (f"https://{org.slug}.example.com/", org.id),
    )
    await owner.execute(
        "INSERT INTO admin_audit_log (actor, action, tenant_id, target, detail) "
        "VALUES ('actor', 'org.create', %s, %s, '{\"note\": \"personal\"}')",
        (org.id, org.slug),
    )
    return {"skill": skill, "agent": agent, "product": product}


async def make_due(owner: AsyncConnection, org: Org) -> None:
    await owner.execute(
        "UPDATE organizations SET status = 'pending_delete', "
        "delete_after = now() - interval '1 minute' WHERE id = %s",
        (org.id,),
    )


async def tenant_tables(owner: AsyncConnection) -> list[str]:
    cur = await owner.execute(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name = 'tenant_id' "
        "AND table_name NOT IN ('admin_audit_log') ORDER BY table_name"
    )
    return [r[0] for r in await cur.fetchall()]


async def counts(owner: AsyncConnection, org: Org) -> dict[str, int]:
    result: dict[str, int] = {}
    async with owner.transaction():
        await owner.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (str(org.id),)
        )
        for table in await tenant_tables(owner):
            cur = await owner.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE tenant_id = %s").format(
                    sql.Identifier(table)
                ),
                (org.id,),
            )
            row = await cur.fetchone()
            assert row is not None
            result[table] = row[0]
        cur = await owner.execute(
            "SELECT count(*) FROM resource_limits WHERE scope_id IN "
            "(%s, (SELECT id::text FROM products WHERE tenant_id = %s))",
            (str(org.id), org.id),
        )
        row = await cur.fetchone()
        assert row is not None
        result["resource_limits"] = row[0]
        cur = await owner.execute(
            "SELECT count(*) FROM organizations WHERE id = %s", (org.id,)
        )
        row = await cur.fetchone()
        assert row is not None
        result["organizations"] = row[0]
    return result


def outcome(results: list[PurgeResult], org: Org) -> PurgeResult:
    (match,) = [r for r in results if r.organization_id == org.id]
    return match


async def test_v2ac16_nothing_is_purged_before_delete_after(
    pool: Pool,
    seed: Seed,
    job_conn: AsyncConnection,
    add_user: AddUser,
) -> None:
    org = await seed.org(status="pending_delete")
    await populate(pool, seed, org, job_conn, add_user)
    before = await counts(job_conn, org)

    results = await purge_due(job_conn)

    assert all(r.organization_id != org.id for r in results)
    assert await counts(job_conn, org) == before


async def test_v2ac16_legal_hold_blocks_purge(
    pool: Pool,
    seed: Seed,
    job_conn: AsyncConnection,
    add_user: AddUser,
) -> None:
    org = await seed.org()
    await populate(pool, seed, org, job_conn, add_user)
    await make_due(job_conn, org)
    await job_conn.execute(
        "UPDATE organizations SET legal_hold = true WHERE id = %s", (org.id,)
    )
    before = await counts(job_conn, org)

    results = await purge_due(job_conn)

    assert all(r.organization_id != org.id for r in results)
    assert await counts(job_conn, org) == before

    await job_conn.execute(
        "UPDATE organizations SET legal_hold = false WHERE id = %s", (org.id,)
    )
    assert outcome(await purge_due(job_conn), org).purged is True


async def test_v2ac16_purge_removes_every_row_of_the_tenant(
    pool: Pool,
    seed: Seed,
    job_conn: AsyncConnection,
    add_user: AddUser,
) -> None:
    org = await seed.org()
    await populate(pool, seed, org, job_conn, add_user)
    await make_due(job_conn, org)
    before = await counts(job_conn, org)
    for table in (
        "registry",
        "registry_versions",
        "agents",
        "skills",
        "skill_files",
        "registry_links",
        "registry_version_deps",
        "registry_policies",
        "access_policies",
        "access_policy_history",
        "search_synonyms",
        "products",
        "auth_configs",
        "memberships",
        "api_keys",
        "token_issuers",
        "resource_limits",
        "organizations",
    ):
        assert before[table] > 0, table

    result = outcome(await purge_due(job_conn), org)

    assert result.purged is True
    assert result.slug == org.slug
    after = await counts(job_conn, org)
    assert after == {table: 0 for table in before}


async def test_v2ac16_purge_leaves_other_tenants_untouched(
    pool: Pool,
    seed: Seed,
    job_conn: AsyncConnection,
    add_user: AddUser,
) -> None:
    doomed = await seed.org()
    other = await seed.org()
    await populate(pool, seed, doomed, job_conn, add_user)
    await populate(pool, seed, other, job_conn, add_user)
    await make_due(job_conn, doomed)
    before = await counts(job_conn, other)

    assert outcome(await purge_due(job_conn), doomed).purged is True

    assert await counts(job_conn, other) == before


async def test_v2ac16_purge_nulls_audit_detail_and_keeps_the_row(
    pool: Pool,
    seed: Seed,
    job_conn: AsyncConnection,
    add_user: AddUser,
) -> None:
    doomed = await seed.org()
    other = await seed.org()
    await populate(pool, seed, doomed, job_conn, add_user)
    await populate(pool, seed, other, job_conn, add_user)
    await make_due(job_conn, doomed)

    await purge_due(job_conn)

    cur = await job_conn.execute(
        "SELECT tenant_id, action, detail, at IS NOT NULL FROM admin_audit_log "
        "WHERE tenant_id IN (%s, %s) AND action = 'org.create' ORDER BY target",
        (doomed.id, other.id),
    )
    rows = {r[0]: r[1:] for r in await cur.fetchall()}
    assert rows[doomed.id] == ("org.create", None, True)
    assert rows[other.id][1] == {"note": "personal"}


async def test_v2ac16_rerun_is_idempotent(
    pool: Pool,
    seed: Seed,
    job_conn: AsyncConnection,
    add_user: AddUser,
) -> None:
    org = await seed.org()
    await populate(pool, seed, org, job_conn, add_user)
    await make_due(job_conn, org)

    assert outcome(await purge_due(job_conn), org).purged is True
    assert all(r.organization_id != org.id for r in await purge_due(job_conn))
    await job_conn.execute("SELECT purge_organization(%s)", (org.id,))


async def test_v2ac16_purge_is_blocked_while_other_organisations_link_to_global_resources(
    pool: Pool,
    seed: Seed,
    job_conn: AsyncConnection,
    add_user: AddUser,
) -> None:
    doomed = await seed.org()
    consumer = await seed.org()
    ids = await populate(pool, seed, doomed, job_conn, add_user, global_skill=True)
    consumer_agent = await make_resource(pool, consumer, "agent", "consumer")
    await link_and_publish(pool, consumer, consumer_agent, ids["skill"])
    await make_due(job_conn, doomed)
    before = await counts(job_conn, doomed)

    result = outcome(await purge_due(job_conn), doomed)

    assert result.purged is False
    assert {(b["organization"], b["kind"]) for b in result.blockers} == {
        (consumer.slug, "link"),
        (consumer.slug, "version_dep"),
    }
    assert {b["resource"] for b in result.blockers} == {"base-skill"}
    assert await counts(job_conn, doomed) == before

    async with pool.connection() as conn, conn.transaction():
        await conn.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (str(consumer.id),)
        )
        await delete_resource(conn, caller_for(consumer), consumer_agent)

    assert outcome(await purge_due(job_conn), doomed).purged is True
    assert set((await counts(job_conn, doomed)).values()) == {0}


async def test_v2ac16_requests_for_a_pending_delete_organisation_are_401(
    client: httpx.AsyncClient,
    pool: Pool,
    seed: Seed,
    keys: Keys,
    jwks: dict[str, Any],
    job_conn: AsyncConnection,
    add_user: AddUser,
) -> None:
    org = await seed.org()
    await populate(pool, seed, org, job_conn, add_user)
    await seed.member(org, "late-admin", ["org-admin"])
    headers = login_headers(keys, "late-admin", org.slug)
    await make_due(job_conn, org)

    assert (await client.get("/v1/org/products", headers=headers)).status_code == 401
    await purge_due(job_conn)
    assert (await client.get("/v1/org/products", headers=headers)).status_code == 401


async def test_v2ac16_large_tenant_purges_in_one_transaction(
    seed: Seed, job_conn: AsyncConnection
) -> None:
    org = await seed.org()
    async with job_conn.transaction():
        await job_conn.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (str(org.id),)
        )
        await job_conn.execute(
            "INSERT INTO registry (tenant_id, type, slug, name, created_by, updated_by) "
            "SELECT %s, 'agent', 'bulk-' || g, 'Bulk ' || g, 'u', 'u' "
            "FROM generate_series(1, 10000) g",
            (org.id,),
        )
        await job_conn.execute(
            "INSERT INTO registry_versions (registry_id, tenant_id, version, created_by) "
            "SELECT id, tenant_id, 1, 'u' FROM registry WHERE tenant_id = %s",
            (org.id,),
        )
    await make_due(job_conn, org)

    started = time.monotonic()
    result = outcome(await purge_due(job_conn), org)

    assert result.purged is True
    assert time.monotonic() - started < 60
    assert (await counts(job_conn, org))["registry"] == 0


@pytest.mark.parametrize("role", ["krep_app", "krep_platform"])
async def test_v2ac8_only_the_owner_role_can_call_purge(
    seed: Seed, migrated_db: str, role: str
) -> None:
    org = await seed.org()
    async with await AsyncConnection.connect(
        role_url(role, migrated_db), autocommit=True
    ) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("SELECT purge_organization(%s)", (org.id,))


@pytest.mark.parametrize(
    "state",
    [
        "active",
        "suspended",
        "pending_delete_not_due",
        "pending_delete_legal_hold",
    ],
)
async def test_v2ac16_purge_function_refuses_organisations_that_are_not_due(
    pool: Pool,
    seed: Seed,
    job_conn: AsyncConnection,
    add_user: AddUser,
    state: str,
) -> None:
    org = await seed.org(
        status="pending_delete" if state.startswith("pending") else state
    )
    await populate(pool, seed, org, job_conn, add_user)
    if state == "pending_delete_legal_hold":
        await make_due(job_conn, org)
        await job_conn.execute(
            "UPDATE organizations SET legal_hold = true WHERE id = %s", (org.id,)
        )
    before = await counts(job_conn, org)

    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        await job_conn.execute("SELECT purge_organization(%s)", (org.id,))

    assert await counts(job_conn, org) == before


async def test_v2ac16_purge_function_refuses_the_platform_organisation(
    job_conn: AsyncConnection,
) -> None:
    cur = await job_conn.execute("SELECT id FROM organizations WHERE is_platform")
    row = await cur.fetchone()
    assert row is not None
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        await job_conn.execute("SELECT purge_organization(%s)", (row[0],))


async def test_v2ac16_cli_purge_due_reports_purged_and_blocked(
    pool: Pool,
    seed: Seed,
    job_conn: AsyncConnection,
    add_user: AddUser,
    migrated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clean = await seed.org()
    blocked = await seed.org()
    consumer = await seed.org()
    await populate(pool, seed, clean, job_conn, add_user)
    ids = await populate(pool, seed, blocked, job_conn, add_user, global_skill=True)
    agent = await make_resource(pool, consumer, "agent", "consumer")
    await link_and_publish(pool, consumer, agent, ids["skill"])
    await make_due(job_conn, clean)
    await make_due(job_conn, blocked)
    monkeypatch.setenv(
        "KREP_MIGRATION_DATABASE_URL", role_url("krep_owner", migrated_db)
    )

    try:
        assert await asyncio.to_thread(main, ["jobs", "purge-due"]) == 0

        out = capsys.readouterr().out
        assert f"purged {clean.slug}" in out
        assert f"blocked {blocked.slug}" in out
        assert consumer.slug in out
        assert set((await counts(job_conn, clean)).values()) == {0}
    finally:
        async with pool.connection() as conn, conn.transaction():
            await conn.execute(
                "SELECT set_config('app.tenant_id', %s, true)", (str(consumer.id),)
            )
            await delete_resource(conn, caller_for(consumer), agent)
        await purge_due(job_conn)
