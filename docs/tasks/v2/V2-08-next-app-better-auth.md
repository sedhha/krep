# V2-08 — Next.js app with Better Auth and the BFF proxy

Spec: 3.4, 9.1, 10 (stack), 11, 12. Acceptance: 1 (e2e half), 2 (ban pairing). Starts with a spike.

## Files
- Create: `ui/package.json`, `ui/tsconfig.json`, `ui/next.config.ts`, `ui/src/lib/auth.ts` (Better Auth config), `ui/src/app/api/auth/[...all]/route.ts`, `ui/src/app/api/v1/[...path]/route.ts` (proxy), `ui/src/app/login/page.tsx`, `ui/src/app/signup/page.tsx`, `ui/src/lib/api.ts`, `ui/src/lib/session.ts`, `ui/tests/e2e/auth.spec.ts`, `ui/tests/unit/proxy.test.ts`, `docs/registry/ui-auth.md` (spike notes)
- Modify: `docker-compose.yml` (role `krep_auth` and schema bootstrap only if needed), `.env.example`, `README.md` (setup steps from spec 12), `docker/initdb/02-roles-v2.sql` (grants for `krep_auth`)

## Consumes
Backend drop 1 (selector mode, login JWT verification, `GET /v1/me`, `disabled_users`, `platform_admins`).

## Produces (used by V2-09 to V2-11)
- Better Auth configured with the Postgres adapter in schema `auth` (connecting as `krep_auth`), plugins `username`, `admin`, `jwt` (lifetime from `KREP_LOGIN_JWT_TTL_SECONDS`, JWKS served at `/api/auth/jwks`), email verification off, rate limiting on, sign-up controlled by `KREP_ALLOW_SIGNUP`; the `organization` plugin is not enabled.
- `/api/v1/*` proxy: requires a session, mints/forwards the login JWT as `Authorization: Bearer`, copies `X-Org`/`X-Product`, never forwards cookies or client-supplied `Authorization`, streams multipart bodies, same-origin only.
- Session helper and a typed API client; login and sign-up pages; startup docs: run the Better Auth migration before `alembic upgrade head`.
- Ban flow helper: ban in Better Auth then `POST /v1/admin/users/{id}/disable`, retry-safe in either order.

## Steps
1. Spike first (write findings to `docs/registry/ui-auth.md`): schema `auth` placement via the connection search path, `username` + `jwt` + `admin` plugins together, JWKS shape accepted by the FastAPI verifier, claim names (`sub`, `username`), and the `auth_users` view over the generated tables. Stop and report if any assumption in the spec fails.
2. Unit tests: proxy strips client `Authorization`/`Cookie`, rejects without session, forwards `X-Org`/`X-Product`, preserves status and error bodies, refuses cross-origin.
3. E2E (Playwright, real FastAPI, ac1 e2e half): sign up, username sign-in, `GET /v1/me` through the proxy returns the user; JWT from another issuer is rejected; ban pairing makes the next request `401` even with an unexpired JWT (ac2).
4. Review-focus: JWT refresh near expiry, session cookie flags, CSRF/origin checks on Better Auth routes, open sign-up rate limiting, secrets only from env.
5. Implement.

## Done when
Spike notes written and accepted; e2e sign-up, sign-in and proxied `/v1/me` pass; lint and typecheck clean.

## Flag
Open sign-up is intentional (spec 3.4) but needs Security review before the app is reachable outside a private network.
