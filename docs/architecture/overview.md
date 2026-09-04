# Architecture Overview

## Status

Initial V1 constraints derived from the product specification. Detailed designs
belong in `docs/plans/` and durable decisions belong in `docs/adr/`.

## Shape

Krep begins as a modular monolith organized by platform domain. Module
boundaries should remain clear without introducing network boundaries until
operational evidence requires them.

```text
Customer Backend
       ↓
Agent Gateway
       ↓
Principal + Authorization
       ↓
Runtime
       ↓
Tool Gateway
       ↓
Connections
       ↓
Customer APIs
```

## Domain Modules

- `agents`: agent definitions, versions, and publishing
- `runs`: run lifecycle and status
- `tools`: tool definitions, versions, and gateway behavior
- `connections`: authentication configuration and credential lifecycle
- `authorization`: deterministic policy evaluation
- `runtime`: execution abstraction and orchestration
- `hitl`: interruption, approval, rejection, and resume
- `telemetry`: operational run and tool-call signals
- `evaluation`: offline datasets, evaluators, and scores

External frameworks and infrastructure adapters live under `integrations/`.

## First Vertical Slice

The first implementation milestone should exercise agent creation, HTTP tool
creation and versioning, immutable agent publication, synchronous LangGraph
execution, Tool Gateway execution, JSON responses, and basic run telemetry.
