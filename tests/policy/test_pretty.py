from typing import Any

import pytest

from krep.policy.ast import to_source
from krep.policy.parser import parse

RULES = [
    'token.department == "billing"',
    '"admin" in token.roles',
    'token.org.region in ["emea", "apac"]',
    "token.clearance >= 3",
    'token.roles != "admin"',
    "has(token.org.region)",
    'token["https://acme.com/roles"] == "admin"',
    'token.email.startsWith("a@")',
    'token.email.endsWith("@acme.com")',
    "token.tid == var.tenant_id",
    'var.tenant_id in token["tenants"]',
    '!("contractors" in token.groups)',
    'token.department == "billing" && ("manager" in token.roles || "support-lead" in token.roles) && !("contractors" in token.groups)',
    'token.name == "O\\"Brien"',
    'token.a == "" || token.b == null',
    'token.a == true && token.b == false',
    "token.a == 1.5 && token.b == -2 && token.c == 100.0",
    'token["a\\"b"] == 1',
    'token.a == "é☃😀"',
    "!(!(has(token.a)))",
    "(has(token.a) && has(token.b)) && has(token.c)",
    "(has(token.a) || has(token.b)) || has(token.c)",
    "has(token.a) || has(token.b) && has(token.c)",
    "(has(token.a) || has(token.b)) && has(token.c)",
    "!(has(token.a) && has(token.b))",
    "has(principal.id)",
    "has(token)",
    'token.in == 1 && token.has == 2 && token.true == 3 && token.var == 4',
    'token["a.b"]["c d"] == 1',
]


@pytest.mark.parametrize("source", RULES)
def test_round_trip_is_stable(source: str) -> None:
    ast = parse(source)
    text = to_source(ast)
    assert parse(text) == ast
    assert to_source(parse(text)) == text


def test_canonical_formatting() -> None:
    assert to_source(parse('token.org.region in ["emea","apac"]')) == (
        'token.org.region in ["emea", "apac"]'
    )
    assert to_source(parse('  token.a   ==\n"x"  ')) == 'token.a == "x"'
    assert to_source(parse("!has(token.a)")) == "!(has(token.a))"
    assert to_source(parse('token["roles"] == 1')) == "token.roles == 1"
    assert to_source(parse('token["https://acme.com/roles"] == 1')) == (
        'token["https://acme.com/roles"] == 1'
    )
    assert to_source(parse("token.tid == var.tenant_id")) == "token.tid == var.tenant_id"


def test_and_or_children_are_parenthesised() -> None:
    text = to_source(parse("has(token.a) || has(token.b) && has(token.c)"))
    assert text == "has(token.a) || (has(token.b) && has(token.c))"


def test_non_identifier_segments_use_bracket_form() -> None:
    ast: dict[str, Any] = {
        "op": "has",
        "path": {"root": "token", "segments": ["a-b", "9x", "ok_1", "é"]},
    }
    assert to_source(ast) == 'has(token["a-b"]["9x"].ok_1["é"])'


def test_string_literals_are_json_escaped() -> None:
    ast = parse('token.a == "line\\nbreak \\\\ \\"q\\""')
    assert to_source(ast) == 'token.a == "line\\nbreak \\\\ \\"q\\""'
