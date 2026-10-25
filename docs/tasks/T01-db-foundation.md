# T01 — DB foundation

Spec: 2, 5 (DDL), 5.4 (rules, roles). Acceptance: 28 (partly).

## Files
- Create: `docker-compose.yml`, `docker/initdb/01-roles.sql`, `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_registry_schema.py`, `tests/conftest.py`, `tests/db/test_schema.py`
- Modify: `pyproject.toml` (runtime deps: fastapi, uvicorn, psycopg[binary,pool], alembic, sqlalchemy, lark, pyjwt[crypto], httpx, jsonschema; dev: pytest, pytest-asyncio), `.env.example` (the two URL names)

## Produces
- `tests/conftest.py` fixtures: `migrated_db` (session; creates a throwaway database, runs `alembic upgrade head` as `krep_owner`), `owner_conn`, `app_conn` (async psycopg connections as `krep_owner` / `krep_app`).
- Revision `0001` exactly the DDL block of spec section 5, with a `downgrade()` that drops in reverse dependency order and never drops extensions.

## Steps
1. Write `test_schema.py`: every table and index from section 5 exists; `registry` rejects `visibility='restricted'` with null `policy_id`; slug/name/tags CHECKs fire; `registry_versions` CHECK ties `status='published'` to `published_at` + `content_hash`.
2. Compose + roles script + `env.py` (reads `KREP_MIGRATION_DATABASE_URL`, `target_metadata = None`, online only).
3. Write `0001`; make tests pass; verify `alembic downgrade base` then `upgrade head` works at this revision.

## Done when
Schema tests pass on a fresh container; downgrade/upgrade round-trips.

## Decision to confirm
Tests use the compose Postgres (a throwaway database per session) rather than testcontainers.
