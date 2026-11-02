import uuid

import psycopg
import pytest

from krep.api.errors import ApiError
from krep.search.engine import registry_search
from krep.search.synonyms import (
    SynonymCache,
    create_group,
    delete_group,
    groups_for,
    list_groups,
    normalise_terms,
    update_group,
)
from tests.search.conftest import add_resource, caller_for

REFUND = ["refund", "money back", "reimbursement"]


async def slugs(conn: psycopg.AsyncConnection, tenant: uuid.UUID, q: str) -> list[str]:
    groups = await groups_for(conn, tenant)
    hits = await registry_search(conn, caller_for(tenant), q=q, groups=groups)
    return [h.slug for h in hits]


def test_normalise_terms_lowercases_collapses_and_dedupes() -> None:
    assert normalise_terms(["  Refund ", "Money   BACK", "refund"]) == [
        "refund",
        "money back",
    ]


@pytest.mark.parametrize(
    "terms",
    [
        ["only-one"],
        ["a", "a"],
        [f"t{i}" for i in range(11)],
        ["one two three four", "ok"],
        ["bad!char", "ok"],
        ["", "ok"],
        ["snake_case", "ok"],
    ],
)
def test_normalise_terms_rejects_invalid(terms: list[str]) -> None:
    with pytest.raises(ApiError) as exc:
        normalise_terms(terms)
    assert exc.value.status == 422
    assert exc.value.error == "validation_failed"


async def test_ac24_synonym_finds_resource_that_only_says_refund(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(
        conn, tenant, "res", "Billing Agent", description="Handles refund requests"
    )
    assert await slugs(conn, tenant, "reimbursement") == []
    await create_group(conn, caller_for(tenant), REFUND)
    assert await slugs(conn, tenant, "reimbursement") == ["res"]
    assert await slugs(conn, tenant, "money back") == ["res"]


async def test_ac24_deleting_group_removes_effect_immediately(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(
        conn, tenant, "res", "Billing Agent", description="Handles refund requests"
    )
    group = await create_group(conn, caller_for(tenant), REFUND)
    assert await slugs(conn, tenant, "reimbursement") == ["res"]
    await delete_group(conn, tenant, group["id"])
    assert await slugs(conn, tenant, "reimbursement") == []


async def test_ac24_groups_are_not_transitive(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(
        conn, tenant, "res", "Billing Agent", description="Handles gamma requests"
    )
    await create_group(conn, caller_for(tenant), ["alpha", "beta"])
    await create_group(conn, caller_for(tenant), ["beta", "gamma"])
    assert await slugs(conn, tenant, "beta") == ["res"]
    assert await slugs(conn, tenant, "alpha") == []


async def test_ac24_201st_group_returns_synonym_limit_reached(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await conn.execute(
        "INSERT INTO search_synonyms (tenant_id, terms, created_by) "
        "SELECT %s, ARRAY['a' || i, 'b' || i], 'u1' FROM generate_series(1, 200) i",
        (tenant,),
    )
    with pytest.raises(ApiError) as exc:
        await create_group(conn, caller_for(tenant), ["extra", "terms"])
    assert (exc.value.status, exc.value.error) == (409, "synonym_limit_reached")


async def test_same_term_set_returns_synonym_group_exists(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await create_group(conn, caller_for(tenant), REFUND)
    with pytest.raises(ApiError) as exc:
        await create_group(
            conn, caller_for(tenant), ["Reimbursement", "refund", "money back"]
        )
    assert (exc.value.status, exc.value.error) == (409, "synonym_group_exists")


async def test_update_group_replaces_terms_and_rejects_duplicates(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    first = await create_group(conn, caller_for(tenant), ["a1", "b1"])
    await create_group(conn, caller_for(tenant), ["c1", "d1"])
    updated = await update_group(conn, tenant, first["id"], ["a1", "b1", "e1"])
    assert updated["terms"] == ["a1", "b1", "e1"]
    with pytest.raises(ApiError) as exc:
        await update_group(conn, tenant, first["id"], ["d1", "c1"])
    assert exc.value.error == "synonym_group_exists"
    same = await update_group(conn, tenant, first["id"], ["e1", "b1", "a1"])
    assert same["id"] == first["id"]
    with pytest.raises(ApiError) as missing:
        await update_group(conn, tenant, uuid.uuid4(), ["x1", "y1"])
    assert missing.value.status == 404


async def test_delete_missing_group_is_404(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    with pytest.raises(ApiError) as exc:
        await delete_group(conn, tenant, uuid.uuid4())
    assert exc.value.status == 404


async def test_groups_are_tenant_scoped(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await create_group(conn, caller_for(tenant), REFUND)
    assert await groups_for(conn, uuid.uuid4()) == []
    assert [g["terms"] for g in await list_groups(conn, tenant)] == [REFUND]


async def test_cache_serves_until_ttl_then_reloads(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    now = [0.0]
    cache = SynonymCache(ttl=60, clock=lambda: now[0])
    assert await groups_for(conn, tenant, cache) == []
    await conn.execute(
        "INSERT INTO search_synonyms (tenant_id, terms, created_by) VALUES (%s, %s, 'u1')",
        (tenant, ["a1", "b1"]),
    )
    now[0] = 59
    assert await groups_for(conn, tenant, cache) == []
    now[0] = 61
    assert await groups_for(conn, tenant, cache) == [["a1", "b1"]]


async def test_writes_invalidate_cache(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    cache = SynonymCache(ttl=60, clock=lambda: 0.0)
    assert await groups_for(conn, tenant, cache) == []
    group = await create_group(conn, caller_for(tenant), REFUND, cache)
    assert await groups_for(conn, tenant, cache) == [REFUND]
    await update_group(conn, tenant, group["id"], ["x1", "y1"], cache)
    assert await groups_for(conn, tenant, cache) == [["x1", "y1"]]
    await delete_group(conn, tenant, group["id"], cache)
    assert await groups_for(conn, tenant, cache) == []
