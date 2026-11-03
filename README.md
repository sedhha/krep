# krep

Registry V1: a multi-tenant registry for agents and skills with access policies, search and bundle resolution. Spec: `docs/specs/v1.md`.

## Requirements

Python 3.13, `uv`, Docker (PostgreSQL 17).

## Environment variables

| Name | Role |
| --- | --- |
| `KREP_DATABASE_URL` | Postgres URL for role `krep_app` (the API and benchmark) |
| `KREP_MIGRATION_DATABASE_URL` | Postgres URL for role `krep_owner` (Alembic and the `krep` CLI) |
| `KREP_ENCRYPTION_KEYS` | Comma list of `<key_id>:<urlsafe-base64-32-bytes>` Fernet keys for organisation secrets; first key encrypts, all decrypt; generate one with `krep keys generate` |
| `KREP_METRICS_TOKEN` | Bearer token for `/metrics`; unset means `/metrics` returns 404 |
| `KREP_SEARCH_LOG_ZERO_RESULTS` | `true` logs normalised zero-result queries |
| `KREP_SEARCH_SEMANTIC_ENABLED` | `true` enables semantic search (off by default) |

## Run

```bash
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn krep.api:app
```

Onboard a tenant after inserting its `token_issuers` row:

```bash
uv run krep tenant init --tenant <tenant-uuid> --admin-rule 'token.groups == "grc-admins"' --writer-rule 'token.groups == "grc-editors"'
```

## Test

```bash
uv run pytest -q
```

Tests create throwaway databases on the compose Postgres (`KREP_TEST_DB_HOST`, default `localhost:5432`).

## Benchmark

```bash
uv run python -m benchmarks.run
```

See `docs/registry/benchmark.md`.
