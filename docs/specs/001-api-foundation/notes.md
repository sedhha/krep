# Review Notes 001: API Foundation

<!--
  Written by the reviewing agent in a fresh context, and by the human resolving
  its findings. This file is a working log; it is never the source of truth for
  anything.

  Findings are resolved by editing spec.md or design.md, then marking the
  finding Resolved here with one line on what changed. A finding is never
  resolved by argument alone.
-->

## Findings

| # | Severity | Finding | Resolution |
| - | -------- | ------- | ---------- |
| 1 | blocker | Acceptance criterion 5 requires testing "a request body failing validation," but the only endpoint defined anywhere in design.md's Components/Contracts is `GET /health`, which takes no body. There is no endpoint with a request model to exercise 422 against. The Testing Strategy row for criterion 5 ("POST an invalid body to an endpoint with a request model") assumes an endpoint that doesn't exist in this design. Either a component with a request body must be added, or design.md must specify a concrete test-only mechanism (e.g. a fixture endpoint mounted only in tests) for proving FastAPI's default 422 behavior. | Deferred by human decision (2026-09-06): no request-body endpoint exists in this spec's scope. design.md Testing Strategy row 5 now says "Deferred"; spec.md/design.md Out of Scope records it as tracked for the first request-body endpoint. |
| 2 | major | The Testing Strategy row for criterion 4 states it is "structural — enforced by review, not a runtime test," which contradicts spec.md's own table, which lists criterion 4's "Verified by" as "Integration test." As written, design.md silently downgrades an acceptance criterion from an automated test to a human review step. | Resolved: design.md row 4 now specifies a concrete integration test (construct `create_app()`, add a second router via `.include_router()` on the result, assert it's served) — matches spec.md's "Integration test." |
| 3 | major | The Testing Strategy row for criterion 2 only asserts that a registered router appears in `/openapi.json` paths. Criterion 2 has two parts — "documentation is served" AND "reflects every registered route" — and only the second is tested. Nothing in design.md asserts that `/docs` (the interactive Swagger UI) actually responds (e.g. 200 with HTML). | Resolved: design.md row 2 now also asserts `GET /docs` returns 200 with HTML. |
| 4 | major | Neither spec.md nor design.md addresses the response shape for 404 (unmatched route) or 405 (wrong method). These are handled by Starlette's own default exception handler, which produces a third shape distinct from both FastAPI's 422 validation body and the custom `ErrorResponse` 500 envelope. This is a gap against the stated goal of "a single settled shape ... for error responses" and against criterion 6's framing of what a caller sees on failure. | Resolved: spec.md criterion 9 added (404/405 → same `ErrorResponse` model as criterion 6). design.md Approach/Contracts/Failure Modes/Testing Strategy updated to install a shared `HTTPException` handler covering both 404 and 405. |
| 5 | major | spec.md's Constraints require "modern FastAPI idiom: lifespan handlers rather than startup events, and annotated dependency injection." design.md's Approach and Components never mention a lifespan handler, and never show an `Annotated[..., Depends(...)]` usage anywhere — `Settings` is described only as "read once at startup" with no stated mechanism. The design is silent on a constraint spec.md explicitly imposes; it should either show how these idioms are used or explain why they don't apply to a service this small. | Resolved: design.md Approach/Components now specify `create_app()` uses a `lifespan` context manager (no `on_event`), and the health handler takes `settings: Annotated[Settings, Depends(get_settings)]`. |
| 6 | minor | The Testing Strategy row for criterion 1 says to "assert no I/O via a test that fails if any patched I/O call is hit," but doesn't say what counts as I/O (sockets, filesystem, env access?) or what gets patched. As written this isn't reproducible from the design alone. | Resolved by human decision (2026-09-06): no I/O exists in this spec, so nothing needs patching — row 1 simplified to just the response assertion. |
| 7 | question | Testing Strategy rows for criteria 2 and 6 both rely on adding routes to "a test fixture app" that never appear in the production `create_app()` registration list. design.md doesn't say how tests construct an app with extra test-only routers without a second app-construction path — worth clarifying so this doesn't quietly create a second, untracked way to register routers alongside the "one file registers every router" claim the design rests on. | Resolved: rows 2, 4, 6 now specify tests call the real `create_app()` and add a router via `.include_router()` on its result — same mechanism as production, no second factory. |
| 8 | minor | design.md states the service version is "read once at startup via env vars," but doesn't reconcile this with the project's own version (e.g. `pyproject.toml`). Two independent sources of version truth can drift silently. Worth stating whether `Settings.version` mirrors the package version or is deliberately independent (e.g., deploy-injected). | Resolved by human decision (2026-09-06): version comes from `importlib.metadata.version("krep")` (derived from `pyproject.toml` at build time), not from `Settings`/env vars. One source of truth. |
| 9 | question | design.md argues criterion 4 ("a new router file is registered without editing any other capability's file") is satisfied because the registration file lives inside `krep.api` itself, not inside any capability package. This is true today only because zero capability packages exist yet — once `agents`, `tools`, etc. add routers, each one will still have to edit the same shared `krep.api.app` file. The claim rests on reading "capability's file" narrowly (only files owned by `agents`/`tools`/etc., never `api.app` itself), which spec.md never states explicitly. Worth having the human confirm this reading is the intended one, since it's the crux of the already-made router-registration decision. | Resolved by human decision (2026-09-06): confirmed — `krep.api.app` is exempt from "capability's file." Every capability editing that one shared file is the accepted cost of explicit registration. design.md Approach records this explicitly. |
| 10 | minor | The Failure Modes table doesn't record the known operational consequence of explicit registration: two capability PRs that both edit `krep.api.app` to add their own router will conflict. This trade-off was already accepted (per the Alternatives Considered entry on auto-discovery), but the concrete risk isn't recorded anywhere as a documented consequence. | Resolved: added as a row in design.md's Failure Modes table. |

<!-- Severity: blocker, major, minor, question. -->

## Decision Log

<!--
  Decisions taken during implementation that were not in design.md, with the
  reason. If an entry here describes an architectural commitment, it belongs in
  design.md or an ADR instead — move it.
-->

- {{DATE}}:
