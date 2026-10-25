# T08 — Ops CLI

Spec: 4.3 (reserved policies, commands), 5.4 (CLI connects as owner and sets `app.tenant_id`), 8.3 (`policy recompile`). Acceptance: 4, 12 (reserved).

## Files
- Create: `src/krep/cli.py`, `src/krep/policy/store.py`, `tests/cli/test_tenant_init.py`, `test_policy_reset.py`, `test_recompile.py`
- Modify: `pyproject.toml` (`krep = "krep.cli:main"`), `src/krep/__init__.py`

## Consumes
T03 `parse`, T04 `compile_ast`/`COMPILER_VERSION`, T06 `tenant_transaction`.

## Produces (used by T09)
- `policy/store.py`: `async def write_policy(conn, tenant_id, name, ast, user, *, reserved=False, expected_rev: int | None = None) -> PolicyRow` (derives `source` and `compiled_path`, bumps `rev`, inserts history, trims history to `max_policy_history`); reused by the API.
- CLI: `krep tenant init --tenant --admin-rule --writer-rule`, `krep policy reset <name> --tenant --rule`, `krep policy recompile`.

## Steps
1. Tests: init creates both reserved policies (`reserved = true`) and is idempotent; reset replaces the rule and bumps `rev`; invalid rule exits non-zero with the parse error and writes nothing; reset only accepts the two reserved names; recompile rewrites `compiled_path` for rows with an older `compiler_version`.
2. Implement CLI over the owner connection, setting `app.tenant_id` per tenant.

## Done when
The commands from spec 4.3 run verbatim against the compose database.
