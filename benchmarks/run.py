import argparse
import asyncio
import os
import statistics
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from benchmarks.seed import POLICIES, Seeded, seed
from krep.config import Settings
from krep.db.pool import open_pool
from krep.db.tenant import tenant_transaction
from krep.identity.resolve import Caller
from krep.policy.parser import parse
from krep.policy.store import write_policy
from krep.registry.bundle import resolve_bundle
from krep.search.engine import _RANKED, registry_search  # pyright: ignore[reportPrivateUsage]
from krep.search.query import build_tsquery, expand, normalise

TARGETS_MS = {"search": 100.0, "policy_save": 100.0, "bundle": 30.0}
CLIENTS = 4
ITERATIONS = 100


def p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def hundred_node_rule() -> str:
    leaves = 50
    rule = " || ".join(f'token.k{i} == "v{i}"' for i in range(leaves))
    parse(rule)
    return rule


async def measure(
    work: Callable[[], Awaitable[None]],
    clients: int = CLIENTS,
    iterations: int = ITERATIONS,
) -> list[float]:
    samples: list[float] = []

    async def worker() -> None:
        for _ in range(iterations):
            start = time.perf_counter()
            await work()
            samples.append((time.perf_counter() - start) * 1000)

    await asyncio.gather(*(worker() for _ in range(clients)))
    return samples


def caller_for(seeded: Seeded) -> Caller:
    return Caller(
        seeded.tenant,
        "bench-user",
        {"token": {"groups": seeded.groups}, "principal": {}},
        False,
        False,
    )


async def explain(
    pool: AsyncConnectionPool[AsyncConnection], caller: Caller, q: str
) -> str:
    q_norm = normalise(q)
    params: dict[str, Any] = {
        "tenant": caller.tenant_id,
        "doc": Jsonb(caller.doc),
        "vars": Jsonb({"tenant_id": str(caller.tenant_id), "product_id": None}),
        "product": None,
        "admin": False,
        "user": caller.user_id,
        "type": None,
        "scope": None,
        "tags": None,
        "limit": 10,
        "offset": 0,
        "q_norm": q_norm,
        "tsq": build_tsquery(expand(q_norm, [])),
    }
    async with tenant_transaction(pool, caller.tenant_id) as conn:
        await conn.execute("SELECT set_config('jit', 'off', true)")
        await conn.execute(
            "SELECT set_config('pg_trgm.word_similarity_threshold', '0.3', true)"
        )
        cur = await conn.execute("EXPLAIN (ANALYZE, BUFFERS) " + _RANKED, params)  # type: ignore[arg-type]
        return "\n".join(row[0] for row in await cur.fetchall())


async def run(tenant: uuid.UUID | None) -> str:
    settings = Settings(
        database_url=os.environ["KREP_DATABASE_URL"], migration_database_url=""
    )
    async with await open_pool(settings, min_size=CLIENTS, max_size=CLIENTS) as pool:
        seeded = await seed(pool, tenant)
        caller = caller_for(seeded)
        rows: list[tuple[str, float, float, float | None]] = []

        async def search(q: str) -> Callable[[], Awaitable[None]]:
            async def work() -> None:
                async with tenant_transaction(pool, seeded.tenant) as conn:
                    await registry_search(conn, caller, q=q, limit=10)

            return work

        for label, q in (
            ("search, one word", "refund"),
            ("search, three words", "money back returned"),
        ):
            s = await measure(await search(q))
            rows.append((label, statistics.fmean(s), p95(s), TARGETS_MS["search"]))

        plan = await explain(pool, caller_for(seeded), "refund")

        rule = parse(hundred_node_rule())
        counter = 0

        async def save() -> None:
            nonlocal counter
            counter += 1
            async with tenant_transaction(pool, seeded.tenant) as conn:
                await write_policy(
                    conn,
                    seeded.tenant,
                    f"save-{counter % POLICIES}-{uuid.uuid4().hex[:6]}",
                    rule,
                    "bench",
                )

        s = await measure(save)
        rows.append(
            (
                "policy save, 100-node rule",
                statistics.fmean(s),
                p95(s),
                TARGETS_MS["policy_save"],
            )
        )

        bundle_caller = Caller(seeded.tenant, "bench", caller.doc, True, True)

        async def bundle() -> None:
            async with tenant_transaction(pool, seeded.tenant) as conn:
                await resolve_bundle(conn, bundle_caller, seeded.bundle_root, None)

        s = await measure(bundle)
        rows.append(
            (
                "bundle, depth 3, 10 deps",
                statistics.fmean(s),
                p95(s),
                TARGETS_MS["bundle"],
            )
        )

    lines = [
        f"tenant `{seeded.tenant}`, {CLIENTS} concurrent clients x {ITERATIONS} iterations",
        "",
        "| What | mean ms | p95 ms | p95 target ms | met |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label, mean, p, target in rows:
        met = "yes" if target is None or p <= target else "NO"
        lines.append(f"| {label} | {mean:.1f} | {p:.1f} | {target or '-'} | {met} |")
    lines += ["", "```text", plan, "```"]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="benchmarks.run")
    parser.add_argument("--tenant", type=uuid.UUID, default=None)
    args = parser.parse_args()
    print(asyncio.run(run(args.tenant)))


if __name__ == "__main__":
    main()
