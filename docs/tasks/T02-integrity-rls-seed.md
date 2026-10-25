# T02 — Integrity triggers, RLS, grants, seed

Spec: 4.4, 5.1, 5.2, 5.4 (`0003` block). Acceptance: 1 (DB level), 14, 28.

## Files
- Create: `migrations/versions/0002_integrity_triggers.py`, `0003_rls_and_grants.py`, `0004_seed.py`, `tests/db/test_rls.py`, `tests/db/test_immutability.py`, `tests/db/test_migrations.py`

## Consumes
T01 fixtures (`migrated_db`, `owner_conn`, `app_conn`).

## Steps
1. Tests first:
   - `test_ac1_rls_cross_tenant_zero_rows`: as `krep_app` with `app.tenant_id = A`, `SELECT ... WHERE tenant_id = B` returns zero rows; insert with tenant B fails `WITH CHECK`.
   - `test_rls_unset_and_empty_setting_fail_closed`: unset and `''` after a prior `set_config(..., true)` transaction return zero rows without error.
   - `test_krep_app_has_no_ddl_and_read_only_global_tables`.
   - `test_ac14_published_version_and_subtype_rows_immutable` (versions, agents, skills; UPDATE raises `23514`; draft -> published UPDATE succeeds).
   - `test_ac28_downgrade_base_then_upgrade_head`.
   - Seed: `registry_types` has agent/skill, `link_rules` has agent-uses-skill, the six global limits exist.
2. Implement `0002`, `0003` (`TENANT_TABLES` as spec), `0004`; downgrades per 5.4.

## Done when
All above pass; `uv run alembic upgrade head` and `downgrade base` both clean.
