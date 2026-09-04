# Architecture Overview

Krep is a native LangGraph agent runtime. This document describes how the
codebase is partitioned and which dependencies between partitions are legal.

Product scope lives in [the V1 product specification](../product/agent-platform-v1.md).
Decisions and their rationale live in [`docs/adr/`](../adr/README.md).

## Runtime Mental Model

```text
Customer Backend
       │
       ▼
  Agent Gateway  ──────────▶  principal + CEL authorization
       │
       ▼
 LangGraph Runtime  ───────▶  checkpoint / interrupt / resume
       │
       ▼
   Tool Gateway  ──────────▶  resolve connection → inject credential
       │
       ▼
  Customer APIs
```

Secrets resolved by the Tool Gateway must never reach LLM context, LangGraph
message state, logs, telemetry, or evaluation datasets.

## Package Layout

Every partition is a package under `src/krep/`.

| Package | Responsibility |
| ------- | -------------- |
| `shared` | Types, errors, and utilities with no internal dependencies. |
| `integrations` | Adapters to external technology: `cel`, `http`, `langgraph`, `persistence`, `secrets`. Contains no product logic. |
| `telemetry` | Structured logging, metrics, run event emission. |
| `connections` | Connection definitions and credential lifecycle classification. |
| `authorization` | CEL policy evaluation over principal / tenant / agent / tool / request. |
| `tools` | Tool definitions and the Tool Gateway. |
| `agents` | Agent definitions, versioning, and graph construction. |
| `hitl` | Human-in-the-loop approval state and resumption. |
| `runs` | Run records, status, and lifecycle persistence. |
| `runtime` | Execution orchestration: sync, async, durable, streaming. |
| `evaluation` | Offline datasets, evaluators, and scoring. |
| `api` | HTTP surface. FastAPI routers, request/response models. |
| `workers` | Background and durable execution entrypoints. |

## Layer Graph

Dependencies flow downward only. This is the repository's central architectural
invariant.

```text
        api                 workers            ← entrypoints
          └─────────┬──────────┘
                    ▼
          runtime        evaluation             ← orchestration
                    │
                    ▼
   agents   tools   runs   hitl
   authorization    connections                 ← capabilities
                    │
                    ▼
              telemetry                         ← cross-cutting
                    │
                    ▼
             integrations/*                     ← adapters
                    │
                    ▼
                 shared                         ← leaf
```

Legal edges within and across tiers are enumerated exactly in
[`tests/architecture/test_layers.py`](../../tests/architecture/test_layers.py),
which fails the build on any violation. That test file is authoritative; this
diagram is its readable summary. Changing the graph requires an ADR — it is a
Level 3 change under [`docs/WORKFLOW.md`](../WORKFLOW.md).

The rules the graph encodes:

- `shared` imports nothing internal. It stays trivially reusable.
- `integrations` depends only on `shared`. Adapters never know about product
  concepts, so an adapter can be swapped without touching capability code.
- Capability packages never import an entrypoint. `api` and `workers` are
  leaves in the reverse direction; nothing depends on a transport.
- `tools` may import `connections` and `authorization`, because the Tool Gateway
  authorizes a call and resolves its credential before dispatch.
- `api` and `workers` never import each other. They are parallel transports over
  the same runtime.

## Conventions

- Request and response bodies are Pydantic models. No untyped dictionaries cross
  the API boundary.
- Public functions and methods are fully annotated; `mypy` runs in strict mode.
- One clear purpose per module. A module that has grown past a few hundred lines
  is usually two modules.
