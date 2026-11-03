# V2-05 — Platform and organisation routes, audit

Spec: 3.5, 3.6, 9.2, 9.3, 8 (audit table). Acceptance: 6, 7, 8 (runtime), 5 (API level).

## Files
- Create: `src/krep/api/admin.py` (platform routes), `src/krep/api/org.py` (organisation routes), `src/krep/org/service.py` (create organisation, products, members, capabilities), `src/krep/org/audit.py`, `tests/org/conftest.py`, `tests/org/test_admin_routes.py`, `tests/org/test_org_routes.py`, `tests/org/test_service.py`
- Create: `migrations/versions/0011_platform_grants.py` (grants `krep_platform` write access to `access_policies`, `access_policy_history`, `memberships`, `auth_configs` and read access to `resource_limits`, `auth_users`, `registry`, `registry_policies` (the global-read policies on `access_policies` subquery them), so organisation creation is one transaction; also insert-only on `admin_audit_log` for `krep_app` so organisation writes are audited in the same transaction)
- Modify: `src/krep/api/main.py` (mount routers; admin router absent when no platform identity is configured), `src/krep/db/pool.py` (second pool for `krep_platform`), `src/krep/config.py` (`KREP_PLATFORM_DATABASE_URL`), `src/krep/cli.py` (`tenant init` delegates to the same service), `.env.example`, `README.md`

## Consumes
V2-01 tables; V2-03 `save_config`, adapters; V2-04 identity; V1 policy store (`create_policy`, reserved policy helpers).

## Produces (used by V2-07 and drop 2)
- Platform routes per 9.2 except lifecycle and global scope move (V2-07, V2-06): `GET /admin/auth-adapters`, `POST /admin/organizations` (atomic: organisation, `open-to-all`, `registry-admins`/`writers`/`readers`, first admin membership with group `org-admin` for an existing username, optional auth config), list/get, member attach/detach, platform-admin grant/revoke, user disable/enable (deny-list), `GET /admin/audit`.
- Organisation routes per 9.3: products (archive, `409 product_not_empty`), organisation and product auth (`GET` never returns the secret: `secret_set`, `key_id`, `rev`), `effective-auth`, `POST /org/auth/test`, members (`POST` by exact username or email through `auth_users`, generic `404`), capabilities (`PUT /org/capabilities` validated with the V1 parser).
- `audit.py`: `record(conn, actor, action, tenant, target, detail)`; `detail` never holds secrets.

## Steps
1. Tests: create organisation is atomic (failure at the auth step leaves no organisation, policies or membership), defaults from spec 3.6, unknown `admin_user` -> `422`; slug conflicts `409 slug_taken` (ac6 platform side).
2. Role tests (ac6, ac7): org admin can manage products, auth, members, policies of their organisation and gets `404` for another organisation; org writer and reader cannot touch products, auth or members; platform routes reject org admins and org JWTs; routes closed with no platform identity configured.
3. Member tests: add by username and by email, group updates, remove; unknown identifier returns the generic `404`; no listing endpoint reveals other users; platform admin can attach any user to any organisation.
4. Secret tests (ac5 API level): responses, audit rows and logs never contain a secret; `PUT` with a new secret bumps `rev` and old tokens stop verifying; test-a-token returns claims or a reason without echoing the secret.
5. Grants at runtime (ac8): the app pool cannot write platform tables; only the platform pool does; verify with attempted writes through the wrong pool.
6. Review-focus: removing or demoting the last org admin (blocked with `409 last_admin` unless the caller is a platform admin; the spec is silent, so raise it in the task summary), disabling an organisation's only HMAC config, capability rule lock-out and platform `reset`.
7. Implement.

## Done when
Acceptance 6 and 7 pass, 5 and 8 pass at runtime, every admin write produces an audit row.
