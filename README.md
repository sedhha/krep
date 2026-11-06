# krep

Registry V1: a multi-tenant registry for agents and skills with access policies, search and bundle resolution. Spec: `docs/specs/v1.md`.

## Requirements

Python 3.13, `uv`, Docker (PostgreSQL 17), Node 22 and pnpm (admin panel in `ui/`).

## Environment variables

| Name | Role |
| --- | --- |
| `KREP_DATABASE_URL` | Postgres URL for role `krep_app` (the API and benchmark) |
| `KREP_MIGRATION_DATABASE_URL` | Postgres URL for role `krep_owner` (Alembic and the `krep` CLI) |
| `KREP_PLATFORM_DATABASE_URL` | Postgres URL for role `krep_platform`; enables `/v1/admin/*` and the audit log; unset closes the platform routes |
| `KREP_ENCRYPTION_KEYS` | Comma list of `<key_id>:<urlsafe-base64-32-bytes>` Fernet keys for organisation secrets; first key encrypts, all decrypt; generate one with `krep keys generate` |
| `KREP_PLATFORM_ADMIN_KEY` | Key (at least 32 characters) accepted in `X-Platform-Key` as platform admin; unset or shorter disables key auth |
| `KREP_LOGIN_ISSUER` | `iss` of panel login JWTs; a JWT with this issuer is only verified against the login JWKS |
| `KREP_LOGIN_JWKS_URL` | JWKS URL of the login issuer (`https://`; `http://` is accepted only when `KREP_ENV=local`) |
| `KREP_LOGIN_AUDIENCE` | Required `aud` of panel login JWTs |
| `KREP_LOGIN_JWT_TTL_SECONDS` | Lifetime of panel login JWTs minted by the UI (default 3600) |
| `KREP_AUTH_DATABASE_URL` | Postgres URL for role `krep_auth` (Better Auth in `ui/`; tables live in schema `auth`) |
| `BETTER_AUTH_URL` | Public base URL of the UI (also the login issuer, e.g. `http://localhost:3000`) |
| `BETTER_AUTH_SECRET` | Better Auth signing secret (at least 32 random characters) |
| `KREP_API_URL` | FastAPI base URL the UI proxy forwards `/api/v1/*` to (default `http://localhost:8000`) |
| `KREP_ALLOW_SIGNUP` | `true` allows open sign-up in the UI (needs Security review before any non-private exposure) |
| `KREP_ORG_DELETE_GRACE_DAYS` | Default grace period in days for `schedule-delete` (default 30, request maximum 90) |
| `KREP_ENV` | Set to `local` for local development relaxations |
| `KREP_METRICS_TOKEN` | Bearer token for `/metrics`; unset means `/metrics` returns 404 |
| `KREP_SEARCH_LOG_ZERO_RESULTS` | `true` logs normalised zero-result queries |
| `KREP_SEARCH_SEMANTIC_ENABLED` | `true` enables semantic search (off by default) |

## Run

```bash
docker compose up -d db
cd ui && pnpm install && pnpm auth:migrate && cd ..
uv run alembic upgrade head
uv run uvicorn krep.api:app
cd ui && pnpm dev
```

The Better Auth migration (`pnpm auth:migrate`, connects as `krep_auth`) runs before Alembic because migration `0009` builds the `auth_users` view over `auth."user"`. Export the UI and login variables from the table above first; `KREP_LOGIN_ISSUER` must equal `BETTER_AUTH_URL` and `KREP_LOGIN_JWKS_URL` is `<BETTER_AUTH_URL>/api/auth/jwks`. A compose volume created before V2 needs `docker compose down -v` so the `krep_auth` role and `auth` schema are created.

Onboard a tenant after inserting its `token_issuers` row:

```bash
uv run krep tenant init --tenant <tenant-uuid> --admin-rule 'token.groups == "grc-admins"' --writer-rule 'token.groups == "grc-editors"'
```

Purge organisations whose delete date has passed (run from cron or a scheduled task; needs `KREP_MIGRATION_DATABASE_URL`):

```bash
uv run krep jobs purge-due
```

## Test

```bash
uv run pytest -q
```

UI checks (from `ui/`): `pnpm lint`, `pnpm typecheck`, `pnpm test` (unit), and `pnpm exec playwright install chromium` once, then `pnpm test:e2e`. The e2e run needs `docker compose up -d db`; it recreates database `krep_e2e`, runs both migrations and starts FastAPI (port 8100) and Next (port 3100) itself.

Tests create throwaway databases on the compose Postgres (`KREP_TEST_DB_HOST`, default `localhost:5432`).

## Benchmark

```bash
uv run python -m benchmarks.run
```

See `docs/registry/benchmark.md`.
