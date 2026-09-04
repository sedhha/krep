# Spec 001: API Foundation

| Field | Value |
| ----- | ----- |
| Status | `Draft` |
| Level | 2 |
| Author | sedhha |
| Created | 2026-09-04 |
| Design | [design.md](design.md) |
| Plan | [plan.md](plan.md) |
| ADRs | [ADR-0001: FastAPI Swagger Setup](../../adr/0001-swagger-setup.md) |

<!--
  Seeded from docs/plans/fastapi-setup.md when the harness was introduced.
  The Problem and Constraints below are carried over. Review Goals, Non-Goals,
  and Acceptance Criteria before handing this to an agent — the criteria are
  drafted, not decided.
-->

## Problem

Krep has a package skeleton under `src/krep/` and no HTTP surface. Every
capability in the V1 product specification is reached through an API, so until a
transport exists with a settled shape for routing, validation, and error
responses, each capability would invent its own — and the first three would
disagree.

Deployment also needs a liveness signal before anything can be run anywhere but
a laptop.

## Goals

- A running HTTP service with a health endpoint suitable for orchestrator
  liveness and readiness probes.
- Interactive API documentation and a machine-readable OpenAPI schema, both
  derived from the code so they cannot drift from it.
- A routing layout that lets a new capability add endpoints without editing a
  shared file that every other capability also edits.
- A single settled shape for request validation and for error responses, so
  later capabilities inherit rather than invent them.

## Non-Goals

<!-- Reviewed against docs/product/agent-platform-v1.md § "Explicitly Not V1". -->

- Any agent, tool, connection, or run endpoint. This spec delivers the surface,
  not the capabilities on it.
- Authentication and authorization. API keys, OAuth2 client credentials, and CEL
  evaluation are their own capabilities and their own specs.
- Persistence. No database, migrations, or session handling.
- SSE and streaming responses.
- Rate limiting, quotas, and API versioning beyond the `/v1` prefix the product
  specification already fixes.

## Acceptance Criteria

| # | Criterion | Verified by |
| - | --------- | ----------- |
| 1 | `GET /health` returns 200 with a Pydantic-modelled body reporting service status and version, and performs no I/O. | Integration test |
| 2 | Interactive documentation is served and reflects every registered route without a manual step. | Integration test asserting a route added in the test appears in the schema |
| 3 | The OpenAPI schema is retrievable as JSON and is valid against the OpenAPI specification. | Contract test |
| 4 | A new router file placed in the routes package is registered without editing any other capability's file. | Integration test |
| 5 | A request body failing validation returns 422 with a response matching the single documented error model. | Integration test |
| 6 | An unhandled exception returns the same documented error model and leaks no traceback or internal detail. | Integration test |
| 7 | Every request and response body is a Pydantic model; no `dict` crosses the API boundary. | Architecture or contract test |
| 8 | The service starts from a documented single command, and `.env.example` lists every variable it reads. | Manual run |

## Constraints

- FastAPI, per [ADR-0001](../../adr/0001-swagger-setup.md). Modern FastAPI
  idiom: lifespan handlers rather than startup events, and annotated dependency
  injection.
- Strict Pydantic request and response models on every endpoint.
- `api` may import capability packages but nothing may import `api` — see the
  layer graph in [`docs/architecture/overview.md`](../../architecture/overview.md).
- FastAPI concepts stay inside `krep.api`. ADR-0001 records framework leakage
  into infrastructure code as an accepted risk; containing it is this spec's
  job.
- Python 3.13, `uv`, and `make verify` must pass.

## Open Questions

- Does the health endpoint need to distinguish liveness from readiness now, or
  is one unconditional endpoint enough until a dependency exists that can be
  unready?
- Is the error model shaped for machine consumption — a stable `code` plus a
  human `message` — or is the FastAPI default validation shape acceptable for
  422 specifically?
- Does route registration explicitly list routers, or discover them? Explicit is
  simpler to read; discovery satisfies criterion 4 more literally.
