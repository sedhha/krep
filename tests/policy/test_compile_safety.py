import json
from typing import Any

import pytest

from krep.policy.ast import PolicyInvalid, PolicyTooLarge
from krep.policy.compile import compile_ast

REGEX_METACHARACTERS = "\\.[]{}()*+?^$|"


def cmp_node(segments: list[str], literal: Any) -> dict[str, Any]:
    return {
        "op": "cmp",
        "path": {"root": "token", "segments": segments},
        "cmp": "==",
        "value": {"lit": literal},
    }


def ends_with_node(literal: str) -> dict[str, Any]:
    return {
        "op": "ends_with",
        "path": {"root": "token", "segments": ["email"]},
        "value": {"lit": literal},
    }


def test_ac10_sql_injection_literal_stays_inside_the_string() -> None:
    literal = '"); DROP TABLE registry; --'
    compiled = compile_ast(cmp_node(["a"], literal))
    assert compiled == 'exists($."token"."a"[*] ? (@ == "\\"); DROP TABLE registry; --"))'
    assert json.loads(compiled.split("@ == ", 1)[1][:-2]) == literal


def test_ac10_key_with_quote_dot_quote_is_one_segment() -> None:
    compiled = compile_ast(cmp_node(["a\".\"b"], "x"))
    assert compiled == 'exists($."token"."a\\".\\"b"[*] ? (@ == "x"))'


def test_backslashes_and_newlines_are_json_escaped() -> None:
    compiled = compile_ast(cmp_node(["a\\b"], "line\nbreak\ttab\\"))
    assert compiled == (
        'exists($."token"."a\\\\b"[*] ? (@ == "line\\nbreak\\ttab\\\\"))'
    )
    assert "\n" not in compiled
    assert "\t" not in compiled


@pytest.mark.parametrize("char", list(REGEX_METACHARACTERS))
def test_ends_with_escapes_each_regex_metacharacter(char: str) -> None:
    compiled = compile_ast(ends_with_node(f"a{char}b"))
    escaped_for_regex = f"a\\{char}b$"
    expected_literal = json.dumps(escaped_for_regex)
    assert compiled == (
        f'exists($."token"."email"[*] ? (@ like_regex {expected_literal}))'
    )


def test_ends_with_escapes_all_metacharacters_together() -> None:
    compiled = compile_ast(ends_with_node(REGEX_METACHARACTERS))
    regex = "".join(f"\\{ch}" for ch in REGEX_METACHARACTERS) + "$"
    assert compiled == (
        f'exists($."token"."email"[*] ? (@ like_regex {json.dumps(regex)}))'
    )


@pytest.mark.parametrize("bad", ["a\x00b", "a\x1fb", "a\nb", "a\x7fb", "\t"])
def test_control_characters_in_segments_are_rejected(bad: str) -> None:
    with pytest.raises(PolicyInvalid):
        compile_ast(cmp_node([bad], "x"))


@pytest.mark.parametrize("segments", [[""], ["a" * 129], ["s"] * 9])
def test_invalid_paths_are_rejected(segments: list[str]) -> None:
    with pytest.raises(PolicyInvalid):
        compile_ast(cmp_node(segments, "x"))


def test_unvalidated_ast_is_rejected() -> None:
    with pytest.raises(PolicyInvalid):
        compile_ast({"op": "cmp", "path": {"root": "token", "segments": ["a"]}})
    with pytest.raises(PolicyInvalid):
        compile_ast({"op": "raw", "sql": "1=1"})


def test_oversized_ast_is_rejected() -> None:
    ast = {"op": "and", "args": [cmp_node(["a"], i) for i in range(100)]}
    with pytest.raises(PolicyTooLarge):
        compile_ast(ast)


def test_tenant_variable_only_comes_from_var_tenant_id() -> None:
    from_var = compile_ast(
        {
            "op": "cmp",
            "path": {"root": "token", "segments": ["tid"]},
            "cmp": "==",
            "value": {"var": "tenant_id"},
        }
    )
    assert from_var.endswith("(@ == $tenant_id))")

    from_literal = compile_ast(cmp_node(["tid"], "$tenant_id"))
    assert from_literal == 'exists($."token"."tid"[*] ? (@ == "$tenant_id"))'

    from_segment = compile_ast(cmp_node(["$tenant_id"], "x"))
    assert from_segment == 'exists($."token"."$tenant_id"[*] ? (@ == "x"))'


def test_unknown_variable_is_rejected() -> None:
    with pytest.raises(PolicyInvalid):
        compile_ast(
            {
                "op": "cmp",
                "path": {"root": "token", "segments": ["tid"]},
                "cmp": "==",
                "value": {"var": "other"},
            }
        )
