from typing import Any

import pytest

from krep.policy.ast import PolicyError, PolicyParseError, PolicyTooLarge
from krep.policy.parser import parse


def path(root: str, *segments: str) -> dict[str, Any]:
    return {"root": root, "segments": list(segments)}


def lit(value: object) -> dict[str, object]:
    return {"lit": value}


def test_cmp_equals_string() -> None:
    assert parse('token.department == "billing"') == {
        "op": "cmp",
        "path": path("token", "department"),
        "cmp": "==",
        "value": lit("billing"),
    }


@pytest.mark.parametrize("operator", ["==", "!=", "<", "<=", ">", ">="])
def test_cmp_operators(operator: str) -> None:
    assert parse(f"token.clearance {operator} 3")["cmp"] == operator


def test_member_literal_first() -> None:
    assert parse('"admin" in token.roles') == {
        "op": "member",
        "path": path("token", "roles"),
        "value": lit("admin"),
    }


def test_member_with_var() -> None:
    assert parse("var.tenant_id in token.tenants") == {
        "op": "member",
        "path": path("token", "tenants"),
        "value": {"var": "tenant_id"},
    }


def test_in_list() -> None:
    assert parse('token.org.region in ["emea","apac"]') == {
        "op": "in_list",
        "path": path("token", "org", "region"),
        "values": [lit("emea"), lit("apac")],
    }


def test_in_list_mixed_literals() -> None:
    ast = parse('principal.k in [1, 2.5, true, false, null, "x", var.tenant_id]')
    assert ast["values"] == [
        lit(1),
        lit(2.5),
        lit(True),
        lit(False),
        lit(None),
        lit("x"),
        {"var": "tenant_id"},
    ]


def test_starts_with_and_ends_with() -> None:
    assert parse('token.email.startsWith("a@")') == {
        "op": "starts_with",
        "path": path("token", "email"),
        "value": lit("a@"),
    }
    assert parse('token.email.endsWith("@acme.com")') == {
        "op": "ends_with",
        "path": path("token", "email"),
        "value": lit("@acme.com"),
    }


def test_has() -> None:
    assert parse("has(token.org.region)") == {
        "op": "has",
        "path": path("token", "org", "region"),
    }


def test_has_root_only() -> None:
    assert parse("has(principal)") == {"op": "has", "path": path("principal")}


def test_var_tenant_id_value() -> None:
    assert parse("token.tid == var.tenant_id")["value"] == {"var": "tenant_id"}


def test_bracket_keys() -> None:
    assert parse('token["https://acme.com/roles"] == "admin"')["path"] == path(
        "token", "https://acme.com/roles"
    )


def test_mixed_dot_and_bracket_segments() -> None:
    assert parse('token.a["b.c"].d == 1')["path"] == path("token", "a", "b.c", "d")


def test_literal_types() -> None:
    assert parse("token.a == 3")["value"] == lit(3)
    assert isinstance(parse("token.a == 3")["value"]["lit"], int)
    assert parse("token.a == -3.5")["value"] == lit(-3.5)
    assert parse("token.a == 1e2")["value"] == lit(100.0)
    assert parse("token.a == true")["value"] == lit(True)
    assert parse("token.a == false")["value"] == lit(False)
    assert parse("token.nul == null")["value"] == lit(None)


def test_not() -> None:
    assert parse('!("contractors" in token.groups)') == {
        "op": "not",
        "arg": {
            "op": "member",
            "path": path("token", "groups"),
            "value": lit("contractors"),
        },
    }


def test_not_without_parentheses() -> None:
    assert parse("!has(token.a)") == {
        "op": "not",
        "arg": {"op": "has", "path": path("token", "a")},
    }


def test_and_is_flat_and_nary() -> None:
    ast = parse("has(token.a) && has(token.b) && has(token.c)")
    assert ast["op"] == "and"
    assert len(ast["args"]) == 3


def test_or_is_flat_and_nary() -> None:
    ast = parse("has(token.a) || has(token.b) || has(token.c)")
    assert ast["op"] == "or"
    assert len(ast["args"]) == 3


def test_precedence_and_binds_tighter_than_or() -> None:
    ast = parse("has(token.a) || has(token.b) && has(token.c)")
    assert ast["op"] == "or"
    assert ast["args"][0]["op"] == "has"
    assert ast["args"][1]["op"] == "and"


def test_precedence_not_binds_tighter_than_and() -> None:
    ast = parse("!has(token.a) && has(token.b)")
    assert ast["op"] == "and"
    assert ast["args"][0]["op"] == "not"
    assert ast["args"][1]["op"] == "has"


def test_parentheses_override_precedence() -> None:
    ast = parse("(has(token.a) || has(token.b)) && has(token.c)")
    assert ast["op"] == "and"
    assert ast["args"][0]["op"] == "or"


def test_parenthesised_same_op_is_not_flattened() -> None:
    ast = parse("(has(token.a) && has(token.b)) && has(token.c)")
    assert ast["op"] == "and"
    assert [a["op"] for a in ast["args"]] == ["and", "has"]


def test_redundant_parentheses_collapse() -> None:
    assert parse("((has(token.a)))") == {"op": "has", "path": path("token", "a")}


def test_spec_example_rule() -> None:
    ast = parse(
        'token.department == "billing" && ("manager" in token.roles || '
        '"support-lead" in token.roles) && !("contractors" in token.groups)'
    )
    assert ast == {
        "op": "and",
        "args": [
            {
                "op": "cmp",
                "path": path("token", "department"),
                "cmp": "==",
                "value": lit("billing"),
            },
            {
                "op": "or",
                "args": [
                    {
                        "op": "member",
                        "path": path("token", "roles"),
                        "value": lit("manager"),
                    },
                    {
                        "op": "member",
                        "path": path("token", "roles"),
                        "value": lit("support-lead"),
                    },
                ],
            },
            {
                "op": "not",
                "arg": {
                    "op": "member",
                    "path": path("token", "groups"),
                    "value": lit("contractors"),
                },
            },
        ],
    }


def test_syntax_error_reports_line_and_column() -> None:
    with pytest.raises(PolicyParseError) as exc:
        parse("token.a == ")
    assert exc.value.line == 1
    assert exc.value.column == 12
    assert exc.value.message


def test_syntax_error_in_middle_reports_position() -> None:
    with pytest.raises(PolicyParseError) as exc:
        parse('token.a == "x" &&\n  token.b == == 1')
    assert exc.value.line == 2
    assert exc.value.column == 14


def test_unexpected_character_reports_position() -> None:
    with pytest.raises(PolicyParseError) as exc:
        parse("token.a == 1 @")
    assert (exc.value.line, exc.value.column) == (1, 14)


def test_empty_source_is_a_parse_error() -> None:
    with pytest.raises(PolicyParseError):
        parse("")
    with pytest.raises(PolicyParseError):
        parse("   \n ")


def test_101_nodes_is_too_large() -> None:
    source = " && ".join(f"has(token.k{i})" for i in range(100))
    with pytest.raises(PolicyTooLarge) as exc:
        parse(source)
    assert (exc.value.nodes, exc.value.max) == (101, 100)


def test_100_nodes_is_accepted() -> None:
    source = " && ".join(f"has(token.k{i})" for i in range(99))
    assert parse(source)["op"] == "and"


def value_of(source: str) -> object:
    return parse(source)["value"]["lit"]


def test_unicode_literal() -> None:
    assert value_of('token.a == "héllo ☃ 😀"') == "héllo ☃ 😀"


def test_json_unicode_escape_literal() -> None:
    assert value_of('token.a == "\\u00e9\\ud83d\\ude00"') == "é😀"


def test_escaped_quote_literal() -> None:
    assert value_of('token.name == "O\\"Brien"') == 'O"Brien'


def test_escaped_backslash_and_control_escapes() -> None:
    assert value_of('token.a == "a\\\\b\\n\\t\\/"') == "a\\b\n\t/"


def test_escaped_quote_in_bracket_key() -> None:
    assert parse('token["a\\"b"] == 1')["path"]["segments"] == ['a"b']


def test_key_with_dots_and_quotes_stays_one_segment() -> None:
    assert parse('token["a\\".\\"b"] == 1')["path"]["segments"] == ['a"."b']


def test_empty_string_literal() -> None:
    assert value_of('token.a == ""') == ""


def test_empty_bracket_key_is_rejected() -> None:
    with pytest.raises(Exception):
        parse('token[""] == 1')


@pytest.mark.parametrize(
    "key", ["in", "has", "true", "false", "null", "var", "token", "principal", "startsWith", "endsWith"]
)
def test_reserved_words_as_keys(key: str) -> None:
    assert parse(f"token.{key} == 1")["path"]["segments"] == [key]
    assert parse(f"has(principal.{key})")["path"]["segments"] == [key]


def test_reserved_word_key_before_method_call() -> None:
    ast = parse('token.in.startsWith("x")')
    assert ast["op"] == "starts_with"
    assert ast["path"]["segments"] == ["in"]


def test_method_name_as_final_path_segment_is_not_a_call() -> None:
    assert parse("has(token.startsWith)")["path"]["segments"] == ["startsWith"]


def test_whitespace_and_newline_variants() -> None:
    canonical = parse('token.a == "x" && has(token.b)')
    assert parse('token.a=="x"&&has(token.b)') == canonical
    assert parse('\n  token.a\n==\n"x"\n&&\n  has( token.b )\n') == canonical
    assert parse('\ttoken . a == "x"\r\n&& has ( token . b )') == canonical


def test_in_keyword_needs_separation() -> None:
    assert parse('"a"in token.roles')["op"] == "member"
    with pytest.raises(PolicyParseError):
        parse('"a" intoken.roles')


@pytest.mark.parametrize(
    "source",
    [
        'token.a =~ "x"',
        'token.a like_regex "x"',
        'token.a matches "x"',
        "token.a + 1 == 2",
        "token.a == 1 + 2",
        "token.a * 2 == 4",
        "token.a == token.b",
        "token.a == principal.b",
        "token.a < token.b",
        'token.a in token.b',
        'token.a == "x" # comment',
        'token.a == "x" // comment',
        'token.a == "x" /* c */',
        "token.a",
        '"x"',
        "true",
        "token.a == [1]",
        "token.a == {}",
        "token.a ==",
        "token.a == == 1",
        "token.a in []",
        "token.a in [1,]",
        "token.a in 1",
        "token.1 == 1",
        "token..a == 1",
        "token.a. == 1",
        "other.a == 1",
        "var.other == 1",
        "token.a == var.tenant",
        'token.a.startsWith(1)',
        'token.a.startsWith(token.b)',
        'token.a.startsWith()',
        'token.a.contains("x")',
        'token.a.startsWith("x") == true',
        "has()",
        "has(1)",
        "has(token.a, token.b)",
        "token.a == 'x'",
        'token.a == "unterminated',
        'token.a == "bad \\q escape"',
        'token.a == "raw\nnewline"',
        "token.a == 01",
        "token.a == +1",
        "token.a == .5",
        "token.a == 1.",
        "token.a == NaN",
        "token.a == True",
        "!",
        "()",
        "(token.a == 1",
        "token.a == 1)",
        "token.a == 1 &&",
        "|| token.a == 1",
        "token.a == 1 & token.b == 2",
        "token.a == 1 | token.b == 2",
        "token.a = 1",
        "token.a === 1",
    ],
)
def test_unsupported_syntax_is_rejected(source: str) -> None:
    with pytest.raises(PolicyParseError):
        parse(source)


def test_parse_error_has_location_for_every_rejection() -> None:
    with pytest.raises(PolicyParseError) as exc:
        parse("token.a + 1 == 2")
    assert exc.value.line >= 1 and exc.value.column >= 1


def test_deeply_nested_parentheses_do_not_crash() -> None:
    assert parse("(" * 5000 + "has(token.a)" + ")" * 5000)["op"] == "has"


def test_deeply_nested_negations_are_rejected_not_crashed() -> None:
    with pytest.raises(PolicyError):
        parse("!" * 5000 + "has(token.a)")
