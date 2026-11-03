# V2-04 — Identity: selector mode, login JWT, platform admin

Spec: 3.1, 3.2, 3.3, 3.4 (FastAPI side only), 9.1 (`GET /me`). Acceptance: 1, 2, 3, 4, 6 (identity side), 7 (generic 404 on member lookup is V2-05).

## Files
- Create: `src/krep/identity/selector.py`, `login.py`, `platform.py`, `tests/identity/test_selector.py`, `test_login_jwt.py`, `test_platform_admin.py`, `test_me.py`
- Modify: `src/krep/identity/resolve.py` (`Caller` already has `product_id` (added in V2-02) and gets `can_read`, `is_platform_admin`, `org_slug`; `resolve_caller` dispatches to selector mode when `X-Org` is present), `src/krep/api/deps.py`, `src/krep/api/main.py` (`GET /v1/me`), `src/krep/config.py`, `src/krep/cli.py` (`krep platform-admin grant --username`), `.env.example`, `README.md`

## Consumes
V2-01 tables and `auth_users` view; V2-02 `Caller.product_id` usage; V2-03 `load_effective`, adapters; V1 `identity/jwt.py` JWKS verification.

## Produces (used by V2-05 to V2-07)
- `selector.py`: `resolve_selector(pool, headers) -> Caller`: organisation and product from `X-Org`/`X-Product` (product optional), status must be `active`, then credential per 3.2 step 3; every failure is the identical `401 unauthenticated`.
- `login.py`: verify a login JWT through `KREP_LOGIN_JWKS_URL` with `iss`/`aud`/`exp`, `sub` not in `disabled_users`, membership or platform admin; builds `token = {"sub", "username", "groups"}` from the verified JWT and `memberships`.
- `platform.py`: `is_platform_admin(user_id)` and `X-Platform-Key` constant-time check; platform identity in an organisation gets `can_admin`, user id `platform-admin`, and the transaction flag `app.platform_admin = on` only for platform routes and global writes.
- `GET /v1/me` per spec 9.1; `krep platform-admin grant` resolves the user id from `auth_users` and inserts into `platform_admins` over the owner connection (`KREP_MIGRATION_DATABASE_URL`), per spec 3.3.

## Steps
1. Login JWT tests with the stub issuer (ac1): valid; wrong issuer, wrong audience, expired, unknown key, `alg: none` all return the identical `401`; the login issuer cannot be registered by an organisation auth config.
2. Selector and membership tests (ac2, ac3, ac4): user in organisations A and B selects either; no membership `401`; group change and membership removal apply on the next request; `disabled_users` blocks despite a valid JWT; organisation HMAC token path; unknown/suspended organisation and unknown product indistinguishable; no `X-Product` -> organisation-level `Caller.product_id is None`; product override uses only the product secret.
3. Platform admin tests (ac6 identity side): table grant and env key both work; key unset disables key auth; org JWT or non-admin user never gets platform identity; `X-Org` plus platform identity is `can_admin`.
4. V1 compatibility: requests without `X-Org` resolve exactly as before (run the V1 identity suite unchanged).
5. Review-focus: header casing, empty `X-Product`, a JWT with `groups` claim trying to inject groups (ignored: groups come from `memberships`), clock skew, JWKS fetch failure fails closed.
6. Capability read gate (not covered elsewhere; spec 4.1, 3.6): `resolve` evaluates `registry-readers` alongside admins/writers into `Caller.can_read` (writers and admins imply read; missing policy fails closed); `can_read` in `registry/resources.py`, search and the `Authenticated` routes deny a caller without it. V1 tenants created by `krep tenant init` have no `registry-readers`, so decide there whether init creates it (as `open`, matching the V2-01 backfill).
7. Implement.

## Done when
Acceptance 1-4 and the identity side of 6 pass; V1 identity tests unchanged and green.
