# T04 — Policy compiler to jsonpath

Spec: 8.3 (compilation table, safety rules, golden tests). Acceptance: 9 (golden), 10 (compile side). Pure Python.

## Files
- Create: `src/krep/policy/compile.py`, `tests/policy/test_compile_golden.py`, `tests/policy/test_compile_safety.py`

## Consumes
T03: `parse(source) -> dict`, `validate_ast(ast) -> int`.

## Produces (used by T05, T08, T09)
- `compile.py`: `COMPILER_VERSION: int = 1`; `compile_ast(ast: dict) -> str`.

## Steps
1. Golden tests: the 13 rule -> expected-path rows of the 8.3 table (rows 14 and 15 belong to T03), asserted verbatim.
2. Safety tests: literal `"); DROP TABLE registry; --`, key `a"."b`, backslashes, newlines, `ends_with` with every regex metacharacter (`\ . [ ] { } ( ) * + ? ^ $ |`), control characters in segments rejected, `$tenant_id` only for `var.tenant_id`.
3. Implement by walking the validated AST only; `and`/`or` children that are themselves `and`/`or` parenthesised; `not` -> `!(...)`; path always `$."a"."b"`.

## Done when
All 13 golden rows match exactly and safety tests pass. Postgres acceptance of the strings is proven in T05.
