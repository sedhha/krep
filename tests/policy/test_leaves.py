from typing import Any
from uuid import UUID

import psycopg

from krep.policy.evaluate import LeafResult, evaluate_leaves, warnings_for
from krep.policy.parser import parse

TENANT = UUID("6f1d2c6e-0000-4000-8000-0000000000a1")
RULE = (
    'token.department == "billing" '
    '&& ("manager" in token.roles || "support-lead" in token.roles) '
    '&& !("contractors" in token.groups)'
)
CONTRACTOR_DOC: dict[str, Any] = {
    "token": {
        "department": "billing",
        "roles": ["manager"],
        "groups": ["contractors"],
        "clearance": "3",
    },
    "principal": None,
}


async def test_ac13_leaf_results_for_contractor_token(
    app_conn: psycopg.AsyncConnection,
) -> None:
    leaves = await evaluate_leaves(app_conn, parse(RULE), CONTRACTOR_DOC, TENANT)
    assert leaves == [
        LeafResult('token.department == "billing"', True, None),
        LeafResult('"manager" in token.roles', True, None),
        LeafResult('"support-lead" in token.roles', False, None),
        LeafResult('"contractors" in token.groups', True, "negated in the rule"),
    ]


async def test_ac13_single_leaf_rule(app_conn: psycopg.AsyncConnection) -> None:
    leaves = await evaluate_leaves(
        app_conn, parse("token.clearance >= 3"), {"token": {"clearance": 5}}, TENANT
    )
    assert leaves == [LeafResult("token.clearance >= 3", True, None)]


async def test_double_negation_is_still_marked(
    app_conn: psycopg.AsyncConnection,
) -> None:
    leaves = await evaluate_leaves(
        app_conn, parse('!(!(token.a == "x"))'), {"token": {"a": "x"}}, TENANT
    )
    assert [leaf.note for leaf in leaves] == ["negated in the rule"]


async def test_leaf_with_tenant_variable(app_conn: psycopg.AsyncConnection) -> None:
    leaves = await evaluate_leaves(
        app_conn,
        parse("token.tid == var.tenant_id"),
        {"token": {"tid": str(TENANT)}},
        TENANT,
    )
    assert leaves[0].result is True


def test_ac13_type_mismatch_warning() -> None:
    warnings = warnings_for(parse("token.clearance >= 3"), CONTRACTOR_DOC)
    assert warnings == ['token.clearance is a string ("3") but is compared with a number']


def test_ac13_absent_claim_warning() -> None:
    warnings = warnings_for(parse('token.department == "billing"'), {"token": {}})
    assert warnings == ["token.department is absent from the sample"]


def test_absent_root_and_null_principal() -> None:
    warnings = warnings_for(parse('principal.roles == "x"'), {"token": {}, "principal": None})
    assert warnings == ["principal.roles is absent from the sample"]


def test_matching_types_do_not_warn() -> None:
    doc = {"token": {"department": "billing", "roles": ["manager"], "clearance": 3}}
    rule = 'token.department == "billing" && "manager" in token.roles && token.clearance >= 3'
    assert warnings_for(parse(rule), doc) == []


def test_array_claim_with_matching_elements_does_not_warn() -> None:
    doc = {"token": {"roles": ["manager", "user"]}}
    assert warnings_for(parse('"manager" in token.roles'), doc) == []


def test_array_claim_with_wrong_element_type_warns() -> None:
    doc = {"token": {"levels": ["1", "2"]}}
    assert warnings_for(parse("token.levels >= 1"), doc) == [
        'token.levels is a list of strings but is compared with a number'
    ]


def test_ac13_group_overage_warning() -> None:
    doc = {"token": {"_claim_names": {"groups": "src1"}}}
    warnings = warnings_for(parse('"x" in token.groups'), doc)
    assert any("overage" in w and "groups" in w for w in warnings)


def test_overage_marker_without_groups_does_not_warn() -> None:
    doc = {"token": {"_claim_names": {"roles": "src1"}, "department": "billing"}}
    assert warnings_for(parse('token.department == "billing"'), doc) == []


def test_has_on_absent_claim_still_reports_absence() -> None:
    assert warnings_for(parse("has(token.org.region)"), {"token": {}}) == [
        "token.org.region is absent from the sample"
    ]


def test_warnings_are_deduplicated() -> None:
    rule = 'token.a == "x" || token.a == "y"'
    assert warnings_for(parse(rule), {"token": {}}) == [
        "token.a is absent from the sample"
    ]
