# V2-01 — Migrations: organisations, identity tables, scope, policy join, roles

Spec: 2.1, 3.3, 4.4, 6 (rule table), 8. Acceptance: 8 (grants), 17 (migration side), V1 acceptance 28. Additive only: `visibility` and `policy_id` stay until V2-02.

## Files
- Create: `migrations/versions/0005_orgs_identity.py` (organizations, platform_tenant_id(), products, auth_configs, memberships, platform_admins, disabled_users, admin_audit_log), `0006_registry_scope_policies.py` (registry `scope`/`product_id`, `access_policies.kind`, `registry_policies`, `link_scope_rules` + seed, scope trigger), `0007_rls_v2.py` (RLS, grants, global `SELECT` rules), `0008_backfill.py` (platform organisation, one organisation per existing tenant, `open-to-all`, `registry-readers`, visibility -> `registry_policies`), `0009_auth_users_view.py`, `docker/initdb/02-roles-v2.sql` (`krep_platform`, `krep_auth`), `tests/db/test_v2_schema.py`, `test_v2_rls.py`, `test_v2_backfill.py`
- Modify: `tests/conftest.py` (role setup, stand-in `auth."user"`, `role_url` for the new roles), `tests/db/test_migrations.py` (downgrade/upgrade chain)

## Consumes
V1 schema (revisions 0001-0004), V1 test harness.

## Produces (used by every later task)
- Tables, columns, functions and roles exactly as spec section 8, including the CHECK that blocks `allowed = true` for global -> org/product link rules and the seed rows from spec section 6.
- Trigger: setting `registry.scope = 'global'` requires `current_setting('app.platform_admin', true) = 'on'`.
- Backfill: every distinct V1 `tenant_id` gets an `organizations` row (slug `tenant-<first 8 uuid chars>`), `open-to-all` (`kind = 'open'`, compiled path `true`), `registry-readers` (copy of open semantics); `tenant` visibility -> `registry_policies(read, open-to-all)`, `restricted` -> `registry_policies(read, policy_id)`, `private` -> none.

## Steps
1. Tests: schema presence and constraints (scope/product CHECK, one platform organisation, unique `(tenant_id, product_id, type, slug)` semantics, link-rule CHECK); scope trigger rejects `global` without the flag and accepts it with the flag; V1 data fixture migrated per the backfill table; `alembic downgrade base` then `upgrade head` works (V1 acceptance 28).
2. Grant tests as `krep_app`: cannot write `organizations`, `platform_admins`, `disabled_users`; can read them; can `SELECT` the `auth_users` view and nothing else in `auth`; `krep_platform` can write exactly those tables and `admin_audit_log`.
3. RLS tests: `products`, `auth_configs`, `registry_policies` isolated by tenant; `memberships` readable for own tenant or own `user_id`, writable for own tenant only; global `SELECT` rules let tenant B read tenant A's `scope = 'global'` resource, its versions/subtypes/files, and the policies it references, and nothing else of A.
4. Implement.

## Done when
Tests pass, V1 tests are still green (old columns untouched), and downgrade/upgrade works.

## Flag
`auth_users` needs schema `auth`; production runs the Better Auth migration first. In tests the harness creates the stand-in table before `alembic upgrade head`.
