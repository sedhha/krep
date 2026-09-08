# Design 001: API Foundation

| Field | Value |
| ----- | ----- |
| Status | `Accepted` |
| Author | sedhha |
| Created | 2026-09-06 |
| Spec | [spec.md](spec.md) |
| Review notes | [notes.md](notes.md) |

## Approach

Stand up `krep.api` as a FastAPI application built from a small application
factory. The factory constructs the `FastAPI` instance, registers exception
handlers, and explicitly includes every router — one call per router, in one
file. Each capability's routes live in their own module under `api/routes/`,
but nothing outside `api` ever edits that inclusion list, so criterion 4
("a new router file is registered without editing any other capability's
file") is satisfied with respect to *capability* code; the api package's own
registration file is the one place transport wiring lives, by design.
Confirmed with the human: `krep.api.app` is exempt from "capability's file"
— every capability editing that one shared file to add its
`include_router()` call is the accepted cost of explicit registration (see
Alternatives Considered and Failure Modes).

FastAPI's own OpenAPI generation and Swagger UI (`/docs`) are used unmodified
— no custom schema generation. `/health` is a single unconditional endpoint:
it performs no I/O and returns a Pydantic-modelled body with service status
and version, string-literal `"ok"` for now since there is no dependency yet
that could make the service unready.

Validation errors (422) are left in FastAPI's default shape — no wrapping,
no custom envelope — since consuming clients already know that shape and
criterion 5 only requires *a* documented model, not a bespoke one. Unhandled
exceptions (500) are caught by a single exception handler and converted to a
custom `ErrorResponse` Pydantic model (`code`, `message`) so no traceback or
internal detail leaks.

An unmatched route (404) or a matched route with the wrong method (405) is
the third error path. Left unhandled, Starlette raises `HTTPException` for
both and its default handler returns a raw `{"detail": "..."}` body — a
dict, not a Pydantic model, which violates criterion 7. A handler for
`StarletteHTTPException` is installed alongside the 500 handler so 404, 405,
and any other framework-raised `HTTPException` all return the same
`ErrorResponse` envelope. 422 remains the one deliberate exception to
criterion 7, made explicitly and only for that status code.

Configuration (service name) is read once at startup via a small Pydantic
`Settings` model sourced from environment variables, documented in
`.env.example`. Version is not env-sourced: it is read from the installed
package's own metadata via `importlib.metadata.version("krep")`, which
`uv_build` derives from `pyproject.toml`'s `[project].version` — one source
of truth, no drift possible between the two.

`create_app()` is built with a `lifespan` context manager (the modern
replacement for `@app.on_event("startup"/"shutdown")`), even though it has
nothing to set up or tear down yet — this establishes the pattern spec.md's
Constraints require, so the first capability that needs startup/shutdown
state extends an existing hook rather than introducing the deprecated one.
`Settings` is provided to handlers via annotated dependency injection
(`Annotated[Settings, Depends(get_settings)]`), not imported directly, so it
resolves per request and is overridable in tests.

## Alternatives Considered

| Alternative | Why not |
| ----------- | ------- |
| Router auto-discovery (walk `routes/` package, import every module, register any `APIRouter` found) | Satisfies criterion 4 more literally, but adds discovery machinery (import-time side effects, ordering, silent failures on a malformed module) for a codebase with a handful of routers. Explicit registration was chosen after weighing this trade-off with the human; revisit if the router count grows large enough that the registration file itself becomes the bottleneck. |
| Custom envelope for both 422 and 500 | More consistent client-side handling, but FastAPI's default 422 shape is well documented and widely tooled against; wrapping it would mean re-deriving documentation FastAPI already generates for free, for no behavioral gain at this stage. |
| Separate `/health/live` and `/health/ready` | Anticipates future dependencies (DB, queues) that could be unready, but none exist yet — this spec's non-goals explicitly exclude persistence. Adding the split now would be speculative; add it when a real dependency exists to report on. |

## Components

### `krep.api.app`

- **Purpose:** Application factory. Builds the `FastAPI` instance with a
  `lifespan` context manager, registers the exception handlers, and includes
  every router.
- **Interface:** `create_app() -> FastAPI`.
- **Depends on:** `krep.api.routes.*`, `krep.api.errors`, `krep.api.settings`.

### `krep.api.settings`

- **Purpose:** Typed, environment-sourced configuration (service name) for
  the API process. Version is not part of this model — it is read from
  package metadata (see Approach).
- **Interface:** `Settings` Pydantic model; `get_settings() -> Settings`,
  used as a FastAPI dependency (`Annotated[Settings, Depends(get_settings)]`)
  rather than called directly by handlers.
- **Depends on:** `krep.shared` (nothing beyond).

### `krep.api.errors`

- **Purpose:** The single `ErrorResponse` model and the exception handlers
  that convert any unhandled exception and any `HTTPException` (including
  404s from unmatched routes) into it without leaking internals.
- **Interface:** `ErrorResponse` Pydantic model; `install_exception_handlers(app: FastAPI) -> None`.
- **Depends on:** `krep.shared`.

### `krep.api.routes.health`

- **Purpose:** `GET /health` — reports status and version, no I/O.
- **Interface:** `router: APIRouter` with one route taking
  `settings: Annotated[Settings, Depends(get_settings)]`; response model
  `HealthResponse`.
- **Depends on:** `krep.api.settings`.

## Data Flow

```text
Request
  │
  ▼
FastAPI app (krep.api.app)
  │
  ├─ matches a registered router ──▶ handler ──▶ Pydantic response model ──▶ 200
  │
  ├─ request body fails validation ──▶ FastAPI default 422 handler ──▶ 422
  │
  └─ handler raises ──▶ installed exception handler ──▶ ErrorResponse ──▶ 500
```

## Contracts

- `GET /health` → 200, `HealthResponse { status: Literal["ok"], version: str }`.
- `GET /openapi.json` → FastAPI-generated OpenAPI 3.x document (unmodified).
- `GET /docs` → Swagger UI (unmodified FastAPI default).
- Any unhandled exception on any route → 500, `ErrorResponse { code: str, message: str }`.
- Any unmatched route (404), wrong-method request (405), or other framework
  `HTTPException` → `ErrorResponse { code: str, message: str }` at that
  status code.
- Request validation failure on any route → 422, FastAPI's default validation
  error shape (unmodified).

## Failure Modes

| Failure | Caller sees | Retry | State left behind |
| ------- | ----------- | ----- | ------------------ |
| Request body fails Pydantic validation | 422, FastAPI's default validation error body | No | None — request never reached a handler |
| Handler raises an unhandled exception | 500, `ErrorResponse` with a generic `code`/`message`, no traceback | Caller's discretion | None — no I/O has been introduced yet |
| Router module fails to import at startup | Process fails to start; import error on stdout/stderr | N/A — fix and restart | None — nothing partially serves |
| Request hits an unmatched route, or matches a route with the wrong method | 404 or 405, `ErrorResponse` with a generic `code`/`message`, no framework detail | No | None |
| Two capability PRs each add an `include_router()` call to `krep.api.app` in the same edit window | Merge conflict on `krep.api.app`, resolved like any other merge conflict | N/A — human resolves the conflict | None — accepted cost of explicit registration (see Alternatives Considered) |

## Architecture Impact

No new edges. `api` is already declared in `ALLOWED_IMPORTS` in
`tests/architecture/test_layers.py` with the full capability-base import set;
this spec uses none of the capability packages (`agents`, `tools`, `runs`,
`hitl`, `authorization`, `connections`, `runtime`, `evaluation`) since it
delivers only the transport surface, not capability endpoints. `api` imports
only `krep.shared` for now.

## Testing Strategy

| Criterion | Test | Tier |
| --------- | ---- | ---- |
| 1 | `GET /health` returns 200 with `HealthResponse`. No I/O exists yet, so nothing needs mocking — the response assertion itself is the proof. | Integration |
| 2 | Call `create_app()` (the real factory), then call `.include_router()` on its result to add one extra router the same way `krep.api.app` does internally; assert the new route appears in `/openapi.json` paths, and a `GET /docs` request returns 200 with HTML | Integration |
| 3 | Fetch `/openapi.json`, validate against the OpenAPI 3.x spec (e.g. `openapi-spec-validator`) | Contract |
| 4 | Call `create_app()`, add a second router via `.include_router()` on the returned app, assert its route is served — proves the single registration mechanism works end-to-end. (That no *other* file needs editing is a structural property of the file layout, confirmed by human review of the diff, not something a runtime test observes.) | Integration |
| 5 | Deferred — no endpoint in this spec accepts a request body, so there is nothing to POST an invalid body against. Verify when the first request-body endpoint ships (tracked in Out of Scope, not blocking this spec). | — |
| 6 | Add a route that raises in a test app built via `create_app()` + `.include_router()` (same pattern as row 2/4), assert 500 with `ErrorResponse` and no traceback substring in the body | Integration |
| 7 | Static check: no endpoint handler takes or returns `dict` | Architecture or contract |
| 9 | Request an unregistered path and a matched route with the wrong method, assert 404/405 with `ErrorResponse` (not the framework default `{"detail": ...}` shape) | Integration |
| 8 | Run the documented single command (`uv run uvicorn krep.api.app:create_app --factory`), confirm `.env.example` lists every var `Settings` reads | Manual run |

## Out of Scope

- Any agent, tool, connection, or run endpoint — this spec delivers only the
  transport surface.
- Authentication and authorization.
- Persistence of any kind.
- SSE and streaming responses.
- Rate limiting, quotas, and API versioning beyond `/v1`.
- Liveness/readiness split — revisit once a real dependency exists to report
  on.
- Proving criterion 5 (422 on an invalid request body) — no endpoint in this
  spec has a request body. Deferred to the first capability endpoint that
  does; not blocking for this spec.
