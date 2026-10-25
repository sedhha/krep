# Conventions (apply to every task)

Spec: `docs/specs/v1.md`. Platform context: `v1-platform.md`.

## Stack and layout
- Python 3.13, `uv`, FastAPI, psycopg 3 async (no ORM), Alembic (explicit SQL only, no models, no autogenerate), `lark`, PostgreSQL 17. Layout exactly as spec section 2.
- Migrations: one revision per file, `op.get_bind().exec_driver_sql`, no bare `%` in SQL, never edit a merged revision.
- Env vars: `KREP_DATABASE_URL` (role `krep_app`), `KREP_MIGRATION_DATABASE_URL` (role `krep_owner`). Document plain env var names only.

## Testing
- Test first. `pytest` + `pytest-asyncio`. Database tests run against the docker-compose Postgres in a throwaway database migrated with `alembic upgrade head`, and connect as `krep_app` (never owner/superuser) unless the test is about migrations.
- Each task lists the spec acceptance tests (section 14) it must make pass; cite them by number in test names or docstring-free comments-free naming, e.g. `test_ac15_publish_11th_deletes_oldest`.

## Code rules
- No code comments unless the WHY is non-obvious.
- Errors: `{"error": "<code>", "message": "...", ...}` with the exact codes from the spec.
- Never log token claims, principals, prompts, or skill content. Secrets from env vars only; no endpoint is public.
- Hidden resources return 404, never 403.
- All SQL uses bound parameters; user text is never concatenated.

## Definition of done (every task)
- Listed tests pass, `uv run pytest -q` is green, no unrelated files touched.
- `progress.md` updated only after my approval.
