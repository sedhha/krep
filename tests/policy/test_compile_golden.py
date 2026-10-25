import pytest

from krep.policy.compile import COMPILER_VERSION, compile_ast
from krep.policy.parser import parse

RULE_12 = (
    'token.department == "billing" && ("manager" in token.roles || '
    '"support-lead" in token.roles) && !("contractors" in token.groups)'
)

GOLDEN = [
    (
        1,
        'token.department == "billing"',
        'exists($."token"."department"[*] ? (@ == "billing"))',
    ),
    (
        2,
        '"admin" in token.roles',
        'exists($."token"."roles"[*] ? (@ == "admin"))',
    ),
    (
        3,
        'token.org.region in ["emea","apac"]',
        'exists($."token"."org"."region"[*] ? (@ == "emea" || @ == "apac"))',
    ),
    (
        4,
        "token.clearance >= 3",
        'exists($."token"."clearance"[*] ? (@ >= 3))',
    ),
    (
        5,
        'token.roles != "admin"',
        '!(exists($."token"."roles"[*] ? (@ == "admin")))',
    ),
    (
        6,
        "has(token.org.region)",
        'exists($."token"."org"."region")',
    ),
    (
        7,
        'token["https://acme.com/roles"] == "admin"',
        'exists($."token"."https://acme.com/roles"[*] ? (@ == "admin"))',
    ),
    (
        8,
        'token.email.startsWith("a@")',
        'exists($."token"."email"[*] ? (@ starts with "a@"))',
    ),
    (
        9,
        'token.email.endsWith("@acme.com")',
        'exists($."token"."email"[*] ? (@ like_regex "@acme\\\\.com$"))',
    ),
    (
        10,
        "token.tid == var.tenant_id",
        'exists($."token"."tid"[*] ? (@ == $tenant_id))',
    ),
    (
        11,
        '!("contractors" in token.groups)',
        '!(exists($."token"."groups"[*] ? (@ == "contractors")))',
    ),
    (
        12,
        RULE_12,
        'exists($."token"."department"[*] ? (@ == "billing")) && '
        '(exists($."token"."roles"[*] ? (@ == "manager")) || '
        'exists($."token"."roles"[*] ? (@ == "support-lead"))) && '
        '!(exists($."token"."groups"[*] ? (@ == "contractors")))',
    ),
    (
        13,
        'token.name == "O\\"Brien"',
        'exists($."token"."name"[*] ? (@ == "O\\"Brien"))',
    ),
]


@pytest.mark.parametrize(
    ("rule", "expected"),
    [(rule, expected) for _, rule, expected in GOLDEN],
    ids=[f"row{number}" for number, _, _ in GOLDEN],
)
def test_ac9_golden_compile(rule: str, expected: str) -> None:
    assert compile_ast(parse(rule)) == expected


def test_compiler_version_is_one() -> None:
    assert COMPILER_VERSION == 1


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("token.n < 3", 'exists($."token"."n"[*] ? (@ < 3))'),
        ("token.n <= 3", 'exists($."token"."n"[*] ? (@ <= 3))'),
        ("token.n > 3", 'exists($."token"."n"[*] ? (@ > 3))'),
        ("token.n == true", 'exists($."token"."n"[*] ? (@ == true))'),
        ("token.n == null", 'exists($."token"."n"[*] ? (@ == null))'),
        ("principal.id == 1.5", 'exists($."principal"."id"[*] ? (@ == 1.5))'),
    ],
)
def test_comparison_and_literal_forms(rule: str, expected: str) -> None:
    assert compile_ast(parse(rule)) == expected


def test_nested_same_op_children_are_parenthesised() -> None:
    ast = {
        "op": "or",
        "args": [
            {"op": "has", "path": {"root": "token", "segments": ["a"]}},
            {
                "op": "or",
                "args": [
                    {"op": "has", "path": {"root": "token", "segments": ["b"]}},
                    {"op": "has", "path": {"root": "token", "segments": ["c"]}},
                ],
            },
        ],
    }
    assert compile_ast(ast) == (
        'exists($."token"."a") || (exists($."token"."b") || exists($."token"."c"))'
    )


def test_not_over_group_keeps_parentheses() -> None:
    assert compile_ast(parse("!(has(token.a) && has(token.b))")) == (
        '!(exists($."token"."a") && exists($."token"."b"))'
    )
