# T06 — App skeleton, config, pool, tenant transaction

Spec: 2 (layout, run commands), 4.4 (set_config), 10 (error format), 11 (logging). Acceptance: 1 (service level).

## Files
- Create: `src/krep/config.py`, `src/krep/db/pool.py`, `src/krep/db/tenant.py`, `src/krep/api/__init__.py` (exposes `app`), `src/krep/api/errors.py`, `src/krep/api/logging.py`, `tests/api/test_skeleton.py`, `tests/db/test_tenant_transaction.py`
- Modify: `pyproject.toml` (keep `krep` script entry; real CLI arrives in T08)

## Produces (used by every later task)
- `config.py`: `Settings` (env-driven): `database_url`, `migration_database_url`, `search_semantic_enabled=False`, `search_log_zero_results=False`; `get_settings()`.
- `db/pool.py`: `async def open_pool(settings) -> AsyncConnectionPool`.
- `db/tenant.py`: `@asynccontextmanager async def tenant_transaction(pool, tenant_id: UUID) -> AsyncIterator[AsyncConnection]` opens a transaction and runs `SELECT set_config('app.tenant_id', %s, true)`.
- `api/errors.py`: `class ApiError(Exception)(status: int, error: str, message: str, **extra)`; handlers rendering `{"error","message",...}` and `422 validation_failed` as `{"errors":[{"field","message"}]}`.
- Request logging middleware: tenant_id, user_id, route, status, latency; never bodies, headers or claims.

## Steps
1. Tests: `tenant_transaction` isolates tenants end-to-end through the pool (pooled connection reused by tenant B sees none of A); `ApiError` and validation errors render the documented shapes; log record for a request contains the five fields and not the Authorization header or a sentinel claim.
2. Implement; `uv run uvicorn krep.api:app` starts.

## Done when
Tests pass and the server boots against the compose database.
