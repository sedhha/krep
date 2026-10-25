# T03 — Policy parser, AST, pretty-printer

Spec: 8.2, 8.3 (AST shape, node ops). Acceptance: 9 (rows 14, 15 of golden table), 10 (parse side). Pure Python, no DB.

## Files
- Create: `src/krep/policy/grammar.lark`, `parser.py`, `ast.py`, `tests/policy/test_parser.py`, `test_ast_validation.py`, `test_pretty.py`

## Produces (used by T04, T05, T09)
- `ast.py`: `class PolicyError(Exception)`; `PolicyParseError(line: int, column: int, message: str)`; `PolicyTooLarge(nodes: int, max: int)`; `PolicyInvalid(message: str)`; `validate_ast(ast: dict) -> int` returns node count and enforces limits (100 nodes, depth 8, <= 8 segments, segment 1-128 chars no control chars, string literal <= 256, `in_list` <= 50, `and`/`or` >= 1 arg); `to_source(ast: dict) -> str` canonical text.
- `parser.py`: `parse(source: str) -> dict` returns the canonical AST (spec 8.3 shape) and validates it.

## Steps
1. Tests: each construct in the 8.2 grammar parses to the expected AST (cmp, member both forms, in_list, startsWith/endsWith, has, `var.tenant_id`, bracket keys); precedence `!` > `&&` > `||`; `to_source(parse(x))` is stable (round-trip) and `parse(to_source(ast)) == ast`.
2. Error tests: `token.a == ` raises `PolicyParseError` with line and column; 101 nodes raises `PolicyTooLarge(nodes=101, max=100)`; depth 9, 9 segments, 51-value list, 257-char literal each rejected.
3. Review-focus tests: Unicode and escaped quotes in literals, `token["a\"b"]`, empty string literal, reserved words used as keys (`token.in`), whitespace/newline variants, no regex/arithmetic/path-vs-path comparison accepted.
4. Implement grammar with lark and transformer to dict.

## Done when
Parser and validator tests pass; the AST validator is usable on API-supplied `ast` (not just parsed text).
