import uuid
from typing import Any

import psycopg
import pytest

from krep.identity.resolve import Caller
from krep.search.engine import registry_search
from tests.search.conftest import add_policy, add_resource, caller_for


async def slugs(conn: psycopg.AsyncConnection, caller: Caller, **kw: Any) -> list[str]:
    kw.setdefault("q", "refund")
    return [h.slug for h in await registry_search(conn, caller, **kw)]


async def test_ac5_visibility_matrix_in_search(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    policy = await add_policy(conn, tenant, "billing", 'token.department == "billing"')
    await add_resource(
        conn, tenant, "priv", "Refund Private", visibility="private", created_by="u1"
    )
    await add_resource(
        conn, tenant, "ten", "Refund Tenant", visibility="tenant", created_by="u1"
    )
    await add_resource(
        conn,
        tenant,
        "res",
        "Refund Restricted",
        visibility="restricted",
        policy_id=policy,
    )
    creator = caller_for(tenant, "u1")
    other = caller_for(tenant, "u2")
    matching = caller_for(tenant, "u3", {"department": "billing"})
    assert sorted(await slugs(conn, creator)) == ["priv", "ten"]
    assert await slugs(conn, other) == ["ten"]
    assert sorted(await slugs(conn, matching)) == ["res", "ten"]
    assert await slugs(conn, caller_for(uuid.uuid4(), "u1")) == []


async def test_ac6_hidden_rows_absent_and_no_total(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    policy = await add_policy(conn, tenant, "p", 'token.department == "billing"')
    await add_resource(
        conn,
        tenant,
        "res",
        "Refund Restricted",
        visibility="restricted",
        policy_id=policy,
    )
    hits = await registry_search(
        conn, caller_for(tenant, "u2", {"department": "sales"}), q="refund"
    )
    assert hits == []


async def test_ac7_recall_with_filter_pages_exactly(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    policy = await add_policy(conn, tenant, "vis", 'token.group == "a"')
    for i in range(480):
        await add_resource(
            conn,
            tenant,
            f"hidden-{i}",
            f"Refund Hidden {i}",
            visibility="restricted",
            policy_id=policy,
        )
    for i in range(12):
        await add_resource(
            conn, tenant, f"match-{i}", f"Refund Agent {i}", visibility="tenant"
        )
    for i in range(8):
        await add_resource(
            conn, tenant, f"other-{i}", f"Invoice Agent {i}", visibility="tenant"
        )
    caller = caller_for(tenant, "u9")
    page1 = await registry_search(conn, caller, q="refund", limit=10, offset=0)
    page2 = await registry_search(conn, caller, q="refund", limit=10, offset=10)
    assert len(page1) == 10
    assert len(page2) == 2
    assert not {h.id for h in page1} & {h.id for h in page2}
    assert all(h.slug.startswith("match-") for h in page1 + page2)


async def test_ac8_policy_error_hides_resource_and_request_succeeds(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    policy = await add_policy(conn, tenant, "p", 'token.a == "b"')
    cur = await conn.execute(
        "UPDATE access_policies SET compiled_path = '$.token.a'::jsonpath WHERE id = %s",
        (policy,),
    )
    assert cur.rowcount == 1
    await add_resource(
        conn,
        tenant,
        "res",
        "Refund Restricted",
        visibility="restricted",
        policy_id=policy,
    )
    await add_resource(conn, tenant, "ten", "Refund Tenant")
    assert await slugs(conn, caller_for(tenant, "u2", {"a": "b"})) == ["ten"]


async def test_archived_and_draft_rows_never_returned(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(conn, tenant, "arch", "Refund Archived", status="archived")
    await add_resource(conn, tenant, "draft", "Refund Draft", status="draft")
    await add_resource(conn, tenant, "pub", "Refund Published")
    assert await slugs(conn, caller_for(tenant)) == ["pub"]
    assert await slugs(conn, caller_for(tenant), q="") == ["pub"]


async def test_ac23_stemming_finds_refund(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(
        conn, tenant, "ra", "Refund Assistant", description="Handles refunds"
    )
    await add_resource(
        conn, tenant, "inv", "Invoice Helper", description="Builds invoices"
    )
    assert await slugs(conn, caller_for(tenant), q="refunds") == ["ra"]


async def test_ac23_fuzzy_name_finds_typo(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(conn, tenant, "ra", "Refund Assistant")
    await add_resource(conn, tenant, "inv", "Invoice Helper")
    assert await slugs(conn, caller_for(tenant), q="refnd") == ["ra"]


async def test_ac23_or_query_ranks_most_matching_words_first(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(
        conn, tenant, "one", "Support Bot", description="Sends your money to people"
    )
    await add_resource(
        conn,
        tenant,
        "ra",
        "Refund Assistant",
        description="Gets your money back when returned",
    )
    await add_resource(conn, tenant, "none", "Weather Bot", description="Forecasts")
    assert await slugs(conn, caller_for(tenant), q="money back returned") == [
        "ra",
        "one",
    ]


@pytest.mark.parametrize(
    "q", ["refund | ) & !", "'\"; --", "the a of", "!!!", "<-> :* ( ("]
)
async def test_ac25_hostile_queries_return_a_list(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID, q: str
) -> None:
    await add_resource(conn, tenant, "ra", "Refund Assistant")
    assert isinstance(await registry_search(conn, caller_for(tenant), q=q), list)


async def test_hostile_query_with_real_word_still_matches(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(conn, tenant, "ra", "Refund Assistant")
    assert await slugs(conn, caller_for(tenant), q="refund | ) & !") == ["ra"]


async def test_empty_q_lists_by_updated_at_desc(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    first = await add_resource(conn, tenant, "a-one", "Alpha")
    await add_resource(conn, tenant, "b-two", "Beta")
    await conn.execute(
        "UPDATE registry SET updated_at = now() + interval '1 hour' WHERE id = %s",
        (first,),
    )
    assert await slugs(conn, caller_for(tenant), q="  ") == ["a-one", "b-two"]


async def test_type_filter_and_unknown_type(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(conn, tenant, "ag", "Refund Agent", type="agent")
    await add_resource(conn, tenant, "sk", "Refund Skill", type="skill")
    assert await slugs(conn, caller_for(tenant), type="skill") == ["sk"]
    assert await slugs(conn, caller_for(tenant), type="nope") == []


async def test_tags_require_all_and_unknown_tag(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(conn, tenant, "both", "Refund Both", tags=["billing", "refunds"])
    await add_resource(conn, tenant, "one", "Refund One", tags=["billing"])
    assert await slugs(conn, caller_for(tenant), tags=["billing", "refunds"]) == [
        "both"
    ]
    assert sorted(await slugs(conn, caller_for(tenant), tags=["billing"])) == [
        "both",
        "one",
    ]
    assert await slugs(conn, caller_for(tenant), tags=["ghost"]) == []


async def test_limit_and_offset_bounds_are_clamped(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    for i in range(60):
        await add_resource(conn, tenant, f"r-{i}", f"Refund {i}")
    caller = caller_for(tenant)
    assert len(await registry_search(conn, caller, q="refund", limit=1000)) == 50
    assert await registry_search(conn, caller, q="refund", limit=-5) == []
    assert await registry_search(conn, caller, q="refund", offset=-5, limit=3) != []
    assert await registry_search(conn, caller, q="refund", offset=10_000) == []


async def test_offset_beyond_branch_depth_returns_what_branches_produced(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    for i in range(120):
        await add_resource(conn, tenant, f"r-{i}", f"Refund {i}")
    caller = caller_for(tenant)
    deep = await registry_search(conn, caller, q="refund", limit=50, offset=90)
    assert len(deep) <= 10
    assert await registry_search(conn, caller, q="refund", limit=50, offset=150) == []


async def test_other_users_private_resource_hidden_in_same_tenant(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(
        conn, tenant, "mine", "Refund Mine", visibility="private", created_by="u2"
    )
    assert await slugs(conn, caller_for(tenant, "u1")) == []
    assert await slugs(conn, caller_for(tenant, "u2")) == ["mine"]


async def test_synonym_groups_expand_the_query(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(conn, tenant, "ra", "Refund Assistant")
    caller = caller_for(tenant)
    assert await slugs(conn, caller, q="reimbursement") == []
    groups = [["refund", "money back", "reimbursement"]]
    assert await slugs(conn, caller, q="reimbursement", groups=groups) == ["ra"]


async def test_hits_are_hydrated(
    conn: psycopg.AsyncConnection, tenant: uuid.UUID
) -> None:
    await add_resource(
        conn, tenant, "ra", "Refund Assistant", description="d", tags=["billing"]
    )
    [hit] = await registry_search(conn, caller_for(tenant), q="refund")
    assert (hit.type, hit.slug, hit.name, hit.description, hit.tags) == (
        "agent",
        "ra",
        "Refund Assistant",
        "d",
        ["billing"],
    )
    assert hit.current_version is None
    assert hit.score > 0
