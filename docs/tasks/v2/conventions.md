# V2 conventions

Spec: `docs/specs/v2.md`. Everything in `docs/tasks/conventions.md` (V1) still applies; this file only adds to it.

## Additions
- Acceptance tests are the numbered list in `docs/specs/v2.md` section 14; name tests `test_v2ac12_...`. V1 acceptance tests keep their `test_ac..` names.
- Roles: `krep_app` (API), `krep_platform` (writes organisations, platform admins, deny-list, audit), `krep_auth` (owns schema `auth`), `krep_owner` (migrations, purge). Tests connect as the role the production code uses.
- The `auth` schema is created by Better Auth in production. Backend tests create a stand-in `auth."user"` table (`id text`, `username`, `email`, `name`) in the test harness only; never in a migration.
- Login JWT tests use a stub issuer with a generated key and a JWKS fixture (reuse the V1 `Keys` fixtures in `tests/identity/conftest.py`).
- Env vars (plain names, no tooling): `KREP_PLATFORM_ADMIN_KEY`, `KREP_ENCRYPTION_KEYS`, `KREP_LOGIN_ISSUER`, `KREP_LOGIN_JWKS_URL`, `KREP_LOGIN_AUDIENCE`, `KREP_LOGIN_JWT_TTL_SECONDS`, `KREP_ORG_DELETE_GRACE_DAYS`, `KREP_ENV`. Add each to `.env.example` and the README table when the task first uses it.
- Selector-mode and credential failures all return the identical `401 unauthenticated` body.
- Never log or return organisation secrets, passwords, `Authorization`, `Cookie` or `X-Platform-Key`.
- Updating an existing V1 test is allowed only where it referenced `visibility` or `policy_id`; say so in the task summary.

## UI (drop 2, `ui/`)
- Next.js (App Router) + TypeScript strict, shadcn/ui, TanStack Query, Better Auth (pinned version), `react-querybuilder`. Unit tests with Vitest, end-to-end with Playwright against the real FastAPI and Postgres.
- Next is UI + BFF + identity only: no registry or policy logic, no authorization decisions, no Next middleware for authorization. All access decisions come from FastAPI (`GET /v1/me` only hides controls).
- Browser code never sees FastAPI credentials; it calls `/api/v1/*` on the Next server, which forwards the user's login JWT with `X-Org` and `X-Product`.
- No secret is ever rendered or stored client-side after submission; forms for secrets are write-only.
- Same comment rule as the backend; run the project's lint and typecheck as part of "tests pass".
