# T05 — Policy evaluation, summary, leaf testing

Spec: 8.3 (semantic tests), 8.4, 8.5, 8.6 (test endpoint semantics, warnings). Acceptance: 8, 9 (semantic), 10, 13 (engine side).

## Files
- Create: `src/krep/policy/evaluate.py`, `summary.py`, `tests/policy/test_semantics_pg.py`, `test_summary.py`, `test_leaves.py`

## Consumes
T03 `parse`; T04 `compile_ast`; T01/T02 fixtures.

## Produces (used by T07, T09, T13)
- `evaluate.py`:
  - `async def evaluate(conn, compiled_path: str, doc: dict, tenant_id: UUID) -> bool` via `jsonb_path_match(doc, path, vars, true)`; NULL/error -> `False`.
  - `@dataclass class LeafResult: text: str; result: bool; note: str | None`
  - `async def evaluate_leaves(conn, ast: dict, doc: dict, tenant_id: UUID) -> list[LeafResult]` each leaf compiled and evaluated separately, `note="negated in the rule"` under a `not`.
  - `def warnings_for(ast: dict, doc: dict) -> list[str]`: claim absent, type differs from literal, Entra overage (`_claim_names` contains `groups`).
- `summary.py`: `summarize(ast: dict) -> str` in the 8.6 style ("Visible when: ...").

## Steps
1. Semantic tests: the 13 document/rule/expected rows of the 8.3 semantic table through real Postgres, plus the five-caller table in 8.5.
2. Review-focus tests: a compiled path forced to error at evaluation counts as not satisfied and does not raise (acceptance 8); the injection rule from acceptance 10 evaluates correctly and `registry` still exists afterwards; empty `{}` roots; very long claim arrays.
3. Leaf and warning tests mirroring the 8.6 example (contractor token with string clearance).
4. Implement.

## Done when
All 13 semantic rows, 8.5 rows, leaf and warning tests pass.
