# Plan 001: API Foundation

| Field | Value |
| ----- | ----- |
| Status | `Not started` |
| Author | sedhha |
| Created | 2026-09-06 |
| Spec | [spec.md](spec.md) |
| Design | [design.md](design.md) |

## Slices

### Slice 1 — Settings

- **Goal:** Typed, environment-sourced configuration for the API process.
- **Files:** `src/krep/api/settings.py`, `.env.example`
- **Acceptance criteria covered:** 8 (partial — `.env.example` lists every var `Settings` reads)
- **Tests to write first:** Unit test that `get_settings()` returns a `Settings` populated from environment variables, with a documented default when unset.
- **Verify:** `make verify`
- **Done when:** `Settings` and `get_settings()` exist, `.env.example` lists every variable `Settings` reads, and the unit test passes.

### Slice 2 — Error model and exception handlers

- **Goal:** The single `ErrorResponse` model and handlers that convert unhandled exceptions and any `HTTPException` (404, 405, and others) into it.
- **Files:** `src/krep/api/errors.py`
- **Acceptance criteria covered:** 6, 9
- **Tests to write first:** Against a minimal local `FastAPI()` test app with `install_exception_handlers()` applied and a throwaway route that raises — assert 500 with `ErrorResponse` and no traceback substring in the body; assert an unregistered path (404) and a matched route with the wrong method (405) both return `ErrorResponse`, not the framework default `{"detail": ...}` shape.
- **Verify:** `make verify`
- **Done when:** `ErrorResponse` and `install_exception_handlers()` exist, and both tests pass.

### Slice 3 — App factory and health endpoint

- **Goal:** `create_app()` builds the `FastAPI` instance with a `lifespan` context manager, installs the exception handlers from Slice 2, and registers `GET /health`.
- **Files:** `src/krep/api/app.py`, `src/krep/api/routes/health.py`, `src/krep/api/routes/__init__.py`
- **Acceptance criteria covered:** 1, 8 (remainder — documented single run command)
- **Tests to write first:** `GET /health` on an app built via `create_app()` returns 200 with `HealthResponse { status: "ok", version: str }`. Manual run: `uv run uvicorn krep.api.app:create_app --factory` starts the service.
- **Verify:** `make verify`
- **Done when:** the health test passes and the manual run starts the service without error.

### Slice 4 — Documentation, OpenAPI, and router registration

- **Goal:** Prove interactive docs and the OpenAPI schema stay in sync with registered routes, and that a new router is added by calling `.include_router()` on the app returned by `create_app()` — no other file edited.
- **Files:** none new — integration tests only, exercising `krep.api.app` and `krep.api.errors` as already built
- **Acceptance criteria covered:** 2, 3, 4
- **Tests to write first:**
  - Call `create_app()`, add one extra router via `.include_router()` on the result, assert the new route appears in `/openapi.json` paths and `GET /docs` returns 200 with HTML.
  - Fetch `/openapi.json` and validate it against the OpenAPI 3.x spec (e.g. `openapi-spec-validator`).
- **Verify:** `make verify`
- **Done when:** both tests pass and `openapi-spec-validator` (or equivalent) is added as a test dependency.

### Slice 5 — Pydantic boundary enforcement

- **Goal:** No endpoint handler takes or returns `dict` — the API boundary is Pydantic models only.
- **Files:** a static/architecture check (e.g. `tests/architecture/test_api_boundary.py`) — no production code change expected
- **Acceptance criteria covered:** 7
- **Tests to write first:** Inspect every route handler registered by `create_app()` (via the app's route table) and assert each request/response annotation is a Pydantic model, not `dict`.
- **Verify:** `make verify`
- **Done when:** the check exists and passes against the handlers built in Slices 1–4.

## Coverage Check

| Criterion | Slice |
| --------- | ----- |
| 1 | 3 |
| 2 | 4 |
| 3 | 4 |
| 4 | 4 |
| 5 | Deferred — no request-body endpoint exists in this spec's scope (notes.md finding 1, design.md Testing Strategy row 5, spec.md Out of Scope) |
| 6 | 2 |
| 7 | 5 |
| 8 | 1, 3 |
| 9 | 2 |

## Risks

- Slice 4 is the most likely to expand: proving criterion 4 ("no other capability file is edited") is a structural property of the file layout, not something the integration test itself observes — the test only proves the registration *mechanism* works, not that the mechanism was used correctly in every future capability. If the `openapi-spec-validator` dependency (or equivalent) pulls in more than expected, cut schema validation into its own slice rather than growing Slice 4.
- Slice 2's handlers are tested against a throwaway local app, not `create_app()`, since `create_app()` doesn't exist until Slice 3. If that mismatch causes friction once Slice 3 lands, add a short Slice 3 regression test reusing Slice 2's exact assertions against the real app rather than editing Slice 2 after the fact.
