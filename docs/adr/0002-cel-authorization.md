# ADR-0002: Use CEL for Authorization

## Status

Accepted

## Context

Agent and tool authorization requires deterministic policies over principal,
tenant, agent, tool, and request context.

## Decision

Use CEL as the V1 policy expression language and evaluate policies outside LLM
reasoning.

## Consequences

- Policies are deterministic and sandboxable.
- CEL runtime behavior becomes a platform dependency.
- Policy validation, observability, and debugging support will be required.

## Alternatives

- A custom DSL.
- OPA and Rego.
- Policies implemented directly in application code.
