# ADR-0001: Use LangGraph as the V1 Runtime

## Status

Accepted

## Context

V1 needs agent orchestration that can grow from synchronous execution into
checkpointing, resume, human review, and durable execution.

## Decision

Use LangGraph as the V1 runtime implementation behind a Krep-owned runtime
boundary.

## Consequences

- V1 can use LangGraph's execution and state primitives.
- Domain and API code must not depend directly on LangGraph details.
- LangGraph becomes a platform dependency that Krep must test and operate.

## Alternatives

- Build a custom orchestration runtime.
- Support multiple agent frameworks in V1.
