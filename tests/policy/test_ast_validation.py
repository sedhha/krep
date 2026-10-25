import copy
from typing import Any

import pytest

from krep.policy.ast import (
    PolicyError,
    PolicyInvalid,
    PolicyParseError,
    PolicyTooLarge,
    validate_ast,
)
from krep.policy.parser import parse


def has(*segments: str, root: str = "token") -> dict[str, Any]:
    return {"op": "has", "path": {"root": root, "segments": list(segments)}}


def nested_not(depth: int) -> dict[str, Any]:
    node: dict[str, Any] = has("a")
    for _ in range(depth - 1):
        node = {"op": "not", "arg": node}
    return node


def test_validate_returns_node_count() -> None:
    assert validate_ast(has("a")) == 1
    assert validate_ast({"op": "and", "args": [has("a"), {"op": "not", "arg": has("b")}]}) == 4


def test_depth_8_accepted_and_9_rejected() -> None:
    assert validate_ast(nested_not(8)) == 8
    with pytest.raises(PolicyInvalid, match="depth"):
        validate_ast(nested_not(9))
    with pytest.raises(PolicyInvalid, match="depth"):
        parse("!(" * 8 + "has(token.a)" + ")" * 8)


def test_depth_9_via_parser_text() -> None:
    source = "!" * 8 + "has(token.a)"
    with pytest.raises(PolicyInvalid, match="depth"):
        parse(source)
    assert parse("!" * 7 + "has(token.a)")


def test_segments_8_accepted_and_9_rejected() -> None:
    assert validate_ast(has(*[f"s{i}" for i in range(8)])) == 1
    with pytest.raises(PolicyInvalid, match="segments"):
        validate_ast(has(*[f"s{i}" for i in range(9)]))
    with pytest.raises(PolicyInvalid, match="segments"):
        parse("has(token." + ".".join(f"s{i}" for i in range(9)) + ")")


def test_segment_length_bounds() -> None:
    assert validate_ast(has("a" * 128)) == 1
    with pytest.raises(PolicyInvalid):
        validate_ast(has("a" * 129))
    with pytest.raises(PolicyInvalid):
        validate_ast(has(""))


@pytest.mark.parametrize("bad", ["a\x00b", "a\nb", "a\x1fb", "a\x7fb"])
def test_segment_control_characters_rejected(bad: str) -> None:
    with pytest.raises(PolicyInvalid):
        validate_ast(has(bad))


def test_in_list_50_accepted_and_51_rejected() -> None:
    def in_list(n: int) -> dict[str, Any]:
        return {
            "op": "in_list",
            "path": {"root": "token", "segments": ["a"]},
            "values": [{"lit": i} for i in range(n)],
        }

    assert validate_ast(in_list(50)) == 1
    with pytest.raises(PolicyInvalid, match="50"):
        validate_ast(in_list(51))
    with pytest.raises(PolicyInvalid):
        validate_ast(in_list(0))
    with pytest.raises(PolicyInvalid, match="50"):
        parse("token.a in [" + ",".join(str(i) for i in range(51)) + "]")


def test_string_literal_256_accepted_and_257_rejected() -> None:
    assert parse(f'token.a == "{"x" * 256}"')
    with pytest.raises(PolicyInvalid, match="256"):
        parse(f'token.a == "{"x" * 257}"')
    with pytest.raises(PolicyInvalid, match="256"):
        parse(f'token.email.startsWith("{"x" * 257}")')
    with pytest.raises(PolicyInvalid, match="256"):
        parse(f'token.a in ["{"x" * 257}"]')


def test_string_literal_length_counts_characters_not_bytes() -> None:
    assert parse(f'token.a == "{"é" * 256}"')


def test_and_or_need_at_least_one_arg() -> None:
    with pytest.raises(PolicyInvalid):
        validate_ast({"op": "and", "args": []})
    with pytest.raises(PolicyInvalid):
        validate_ast({"op": "or", "args": []})


def test_too_large_reports_counts_for_api_supplied_ast() -> None:
    ast: dict[str, Any] = {"op": "and", "args": [has(f"k{i}") for i in range(100)]}
    with pytest.raises(PolicyTooLarge) as exc:
        validate_ast(ast)
    assert (exc.value.nodes, exc.value.max) == (101, 100)


def test_deeply_nested_api_ast_is_rejected_without_recursion_error() -> None:
    ast: dict[str, Any] = has("a")
    for _ in range(5000):
        ast = {"op": "not", "arg": ast}
    with pytest.raises(PolicyTooLarge):
        validate_ast(ast)


def test_exceptions_share_a_base() -> None:
    for exc in (PolicyParseError(1, 1, "m"), PolicyTooLarge(2, 1), PolicyInvalid("m")):
        assert isinstance(exc, PolicyError)


@pytest.mark.parametrize(
    "ast",
    [
        None,
        [],
        "x",
        {},
        {"op": "bogus"},
        {"op": "has"},
        {"op": "has", "path": {"root": "other", "segments": ["a"]}},
        {"op": "has", "path": {"root": "token", "segments": "a"}},
        {"op": "has", "path": {"root": "token", "segments": [1]}},
        {"op": "has", "path": {"root": "token"}},
        {"op": "has", "path": {"root": "token", "segments": ["a"]}, "extra": 1},
        {"op": "not"},
        {"op": "not", "arg": None},
        {"op": "and", "args": "x"},
        {"op": "and", "args": [None]},
        {"op": "cmp", "path": {"root": "token", "segments": ["a"]}, "cmp": "=~", "value": {"lit": 1}},
        {"op": "cmp", "path": {"root": "token", "segments": ["a"]}, "cmp": "==", "value": 1},
        {"op": "cmp", "path": {"root": "token", "segments": ["a"]}, "cmp": "==", "value": {"lit": [1]}},
        {"op": "cmp", "path": {"root": "token", "segments": ["a"]}, "cmp": "==", "value": {"lit": {"a": 1}}},
        {"op": "cmp", "path": {"root": "token", "segments": ["a"]}, "cmp": "==", "value": {"lit": 1, "var": "tenant_id"}},
        {"op": "cmp", "path": {"root": "token", "segments": ["a"]}, "cmp": "==", "value": {"var": "other"}},
        {"op": "cmp", "path": {"root": "token", "segments": ["a"]}, "cmp": "==", "value": {"lit": float("inf")}},
        {"op": "cmp", "path": {"root": "token", "segments": ["a"]}, "cmp": "==", "value": {"lit": float("nan")}},
        {"op": "member", "path": {"root": "token", "segments": ["a"]}},
        {"op": "in_list", "path": {"root": "token", "segments": ["a"]}, "values": "x"},
        {"op": "in_list", "path": {"root": "token", "segments": ["a"]}, "values": [1]},
        {"op": "starts_with", "path": {"root": "token", "segments": ["a"]}, "value": {"lit": 1}},
        {"op": "ends_with", "path": {"root": "token", "segments": ["a"]}, "value": {"var": "tenant_id"}},
    ],
)
def test_malformed_api_ast_is_rejected(ast: Any) -> None:
    with pytest.raises(PolicyInvalid):
        validate_ast(copy.deepcopy(ast))


def test_validate_does_not_mutate() -> None:
    ast = parse('token.a == "x" && has(token.b)')
    snapshot = copy.deepcopy(ast)
    validate_ast(ast)
    assert ast == snapshot
