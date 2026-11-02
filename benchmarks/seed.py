import uuid
from dataclasses import dataclass

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from krep.db.tenant import tenant_transaction
from krep.identity.resolve import Caller
from krep.policy.parser import parse
from krep.policy.store import write_policy
from krep.registry.publish import publish
from krep.registry.resources import create_resource
from tests.registry.conftest import agent_body, skill_body

RESOURCES = 10_000
POLICIES = 300
GROUPS = 40
RESTRICTED_SHARE = 0.3

_WORDS = (
    "refund invoice billing claims onboarding contract audit compliance payroll support"
).split()


@dataclass(frozen=True)
class Seeded:
    tenant: uuid.UUID
    groups: list[str]
    bundle_root: uuid.UUID


async def _seed_policies(conn: AsyncConnection, tenant: uuid.UUID) -> list[uuid.UUID]:
    for i in range(POLICIES):
        await write_policy(
            conn, tenant, f"policy-{i:03d}", parse(f'token.groups == "g{i}"'), "bench"
        )
    cur = await conn.execute(
        "SELECT id FROM access_policies WHERE tenant_id = %s AND name LIKE 'policy-%%' "
        "ORDER BY name",
        (tenant,),
    )
    return [row[0] for row in await cur.fetchall()]


async def _seed_resources(
    conn: AsyncConnection, tenant: uuid.UUID, policy_ids: list[uuid.UUID]
) -> None:
    restricted = int(RESTRICTED_SHARE * 10)
    await conn.execute(
        "INSERT INTO registry (tenant_id, type, slug, name, description, tags, visibility, "
        "policy_id, status, created_by, updated_by) "
        "SELECT %(tenant)s, 'agent', 'agent-' || i, "
        "(%(words)s::text[])[1 + i %% 10] || ' assistant ' || i, "
        "'Handles ' || (%(words)s::text[])[1 + (i * 7) %% 10] || ' requests for team ' || i %% 50, "
        "ARRAY[(%(words)s::text[])[1 + i %% 10]], "
        "CASE WHEN i %% 10 < %(restricted)s THEN 'restricted' "
        "WHEN i %% 10 = 9 THEN 'private' ELSE 'tenant' END, "
        "CASE WHEN i %% 10 < %(restricted)s THEN (%(policies)s::uuid[])[1 + i %% %(n)s] END, "
        "'published', 'owner-' || i %% 20, 'owner-' || i %% 20 "
        "FROM generate_series(1, %(count)s) AS i",
        {
            "tenant": tenant,
            "words": _WORDS,
            "restricted": restricted,
            "policies": policy_ids,
            "n": len(policy_ids),
            "count": RESOURCES,
        },
    )


async def _seed_bundle(
    pool: AsyncConnectionPool[AsyncConnection], tenant: uuid.UUID
) -> uuid.UUID:
    caller = Caller(tenant, "bench", {"token": {}, "principal": {}}, True, True)
    async with tenant_transaction(pool, tenant) as conn:
        skills: dict[str, uuid.UUID] = {}
        for slug in ["a1", "a2", "a3", "a4", "b1", "b2", "b3", "c1", "c2", "c3"]:
            created = await create_resource(conn, caller, skill_body(f"bench-{slug}"))
            skills[slug] = created["id"]
            await publish(conn, caller, created["id"], 1)
        root = (await create_resource(conn, caller, agent_body("bench-root")))["id"]
        await publish(conn, caller, root, 1)
        edges = [("root", s) for s in ("a1", "a2", "a3", "a4")]
        edges += [("a1", s) for s in ("b1", "b2", "b3")]
        edges += [("b1", s) for s in ("c1", "c2", "c3")]
        skills["root"] = root
        for source, target in edges:
            await conn.execute(
                "INSERT INTO registry_version_deps (version_id, depends_on_version_id, "
                "tenant_id, relation, auto_load) "
                "SELECT s.id, t.id, %s, 'uses', true FROM registry_versions s, registry_versions t "
                "WHERE s.registry_id = %s AND s.version = 1 AND t.registry_id = %s "
                "AND t.version = 1",
                (tenant, skills[source], skills[target]),
            )
    return root


async def seed(
    pool: AsyncConnectionPool[AsyncConnection], tenant: uuid.UUID | None = None
) -> Seeded:
    tenant = tenant or uuid.uuid4()
    async with tenant_transaction(pool, tenant) as conn:
        policy_ids = await _seed_policies(conn, tenant)
        await _seed_resources(conn, tenant, policy_ids)
        await conn.execute("ANALYZE registry")
    root = await _seed_bundle(pool, tenant)
    return Seeded(tenant, [f"g{i}" for i in range(GROUPS)], root)
