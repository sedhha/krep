from typing import Any
from uuid import UUID

import psycopg
import pytest

from krep.policy.compile import compile_ast
from krep.policy.evaluate import evaluate
from krep.policy.parser import parse

TENANT = UUID("6f1d2c6e-0000-4000-8000-0000000000a1")
RULE_12 = (
    'token.department == "billing" '
    '&& ("manager" in token.roles || "support-lead" in token.roles) '
    '&& !("contractors" in token.groups)'
)


async def satisfied(
    conn: psycopg.AsyncConnection,
    rule: str,
    doc: dict[str, Any],
    tenant_id: UUID = TENANT,
) -> bool:
    return await evaluate(conn, compile_ast(parse(rule)), doc, tenant_id)


@pytest.mark.parametrize(
    ("doc", "rule", "expected"),
    [
        ({"token": {"role": "admin"}}, '"admin" in token.role', True),
        ({"token": {"roles": ["manager", "user"]}}, '"manager" in token.roles', True),
        ({"token": {}}, 'token.nope == "x"', False),
        ({"token": {}}, '!(token.nope == "x")', True),
        ({"token": {"roles": ["admin", "user"]}}, 'token.roles != "admin"', False),
        ({"token": {"clearance": 3}}, "token.clearance >= 3", True),
        ({"token": {"clearance": "3"}}, "token.clearance >= 3", False),
        (
            {"token": {"https://acme.com/roles": ["admin"]}},
            '"admin" in token["https://acme.com/roles"]',
            True,
        ),
        (
            {"token": {"email": "a@acme.com"}},
            'token.email.endsWith("@acme.com")',
            True,
        ),
        ({"token": {"nul": None}}, "token.nul == null", True),
        (
            {"token": {"department": "billing", "roles": ["manager"], "groups": ["contractors"]}},
            RULE_12,
            False,
        ),
        (
            {"token": {"department": "billing", "roles": ["manager"], "groups": ["eng"]}},
            RULE_12,
            True,
        ),
        (
            {"token": {}, "principal": {"roles": ["support"]}},
            '"support" in principal.roles',
            True,
        ),
    ],
    ids=[
        "ac9_row01_scalar_claim",
        "ac9_row02_array_claim",
        "ac9_row03_missing_claim",
        "ac9_row04_negated_missing_claim",
        "ac9_row05_not_equal_no_element",
        "ac9_row06_number_compare",
        "ac9_row07_no_coercion",
        "ac9_row08_url_key",
        "ac9_row10_ends_with",
        "ac9_row11_null_literal",
        "ac9_row12_contractor_hidden",
        "ac9_row12_without_contractors_visible",
        "ac9_row13_principal_root",
    ],
)
async def test_semantic_table(
    app_conn: psycopg.AsyncConnection, doc: dict[str, Any], rule: str, expected: bool
) -> None:
    assert await satisfied(app_conn, rule, doc) is expected


async def test_ac9_row09_tenant_variable(app_conn: psycopg.AsyncConnection) -> None:
    doc = {"token": {"tid": "t1"}}
    rule = "token.tid == var.tenant_id"
    path = compile_ast(parse(rule))
    assert await evaluate(app_conn, path, doc, "t1") is True
    assert await evaluate(app_conn, path, doc, "t2") is False


async def test_ac9_row09_tenant_variable_uses_resolved_tenant(
    app_conn: psycopg.AsyncConnection,
) -> None:
    doc = {"token": {"tid": str(TENANT)}}
    assert await satisfied(app_conn, "token.tid == var.tenant_id", doc) is True
    other = UUID("6f1d2c6e-0000-4000-8000-0000000000b2")
    assert await satisfied(app_conn, "token.tid == var.tenant_id", doc, other) is False


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ({"department": "billing", "roles": ["manager"], "groups": ["eng"]}, True),
        ({"department": "billing", "roles": "support-lead"}, True),
        ({"department": "billing", "roles": ["manager"], "groups": ["contractors"]}, False),
        ({"department": "sales", "roles": ["manager"]}, False),
        ({"roles": ["manager"]}, False),
    ],
    ids=["all_parts", "scalar_role", "contractor", "wrong_department", "no_department"],
)
async def test_ac5_worked_example_callers(
    app_conn: psycopg.AsyncConnection, token: dict[str, Any], expected: bool
) -> None:
    assert await satisfied(app_conn, RULE_12, {"token": token}) is expected


async def test_ac5_worked_example_principal_variant(
    app_conn: psycopg.AsyncConnection,
) -> None:
    rule = RULE_12.replace("token.", "principal.")
    doc = {"token": {}, "principal": {"department": "billing", "roles": ["manager"]}}
    assert await satisfied(app_conn, rule, doc) is True


async def test_ac8_evaluation_error_counts_as_not_satisfied(
    app_conn: psycopg.AsyncConnection,
) -> None:
    result = await evaluate(app_conn, '$."token"', {"token": {"a": 1}}, TENANT)
    assert result is False
    assert (await (await app_conn.execute("SELECT 1")).fetchone()) == (1,)


async def test_ac8_non_boolean_result_counts_as_not_satisfied(
    app_conn: psycopg.AsyncConnection,
) -> None:
    assert await evaluate(app_conn, '$."token"."a"."b"', {"token": {"a": 1}}, TENANT) is False


async def test_ac10_injection_literal_evaluates_and_registry_survives(
    app_conn: psycopg.AsyncConnection,
) -> None:
    literal = '"); DROP TABLE registry; --'
    rule = 'token.note == "\\"); DROP TABLE registry; --"'
    assert await satisfied(app_conn, rule, {"token": {"note": literal}}) is True
    assert await satisfied(app_conn, rule, {"token": {"note": "other"}}) is False
    row = await (await app_conn.execute("SELECT to_regclass('registry')")).fetchone()
    assert row is not None and row[0] is not None


async def test_ac10_injection_key_with_quote_and_dot(
    app_conn: psycopg.AsyncConnection,
) -> None:
    rule = 'token["a\\".\\"b"] == "v"'
    assert await satisfied(app_conn, rule, {"token": {'a"."b': "v"}}) is True
    assert await satisfied(app_conn, rule, {"token": {"a": {"b": "v"}}}) is False


async def test_empty_roots_do_not_match(app_conn: psycopg.AsyncConnection) -> None:
    for doc in ({}, {"token": {}, "principal": {}}):
        assert await satisfied(app_conn, 'token.a == "x"', doc) is False
        assert await satisfied(app_conn, '!("x" in principal.roles)', doc) is True
        assert await satisfied(app_conn, "has(token.a)", doc) is False


async def test_very_long_claim_array(app_conn: psycopg.AsyncConnection) -> None:
    groups = [f"g{i}" for i in range(20000)]
    doc = {"token": {"groups": groups}}
    assert await satisfied(app_conn, '"g19999" in token.groups', doc) is True
    assert await satisfied(app_conn, '"missing" in token.groups', doc) is False
