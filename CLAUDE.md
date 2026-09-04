# Krep Agent Platform — Engineering Instructions

This file is the canonical repository instruction source for coding agents.

Use GitHub CLI account `sedhha` for this repository.

## Source of Truth

Product scope:

- `docs/product/agent-platform-v1.md`

Architecture:

- `docs/architecture/`

Architectural decisions:

- `docs/adr/`

Feature designs and implementation plans:

- `docs/plans/`

When documents disagree, use this precedence:

1. Explicit user instruction
2. Product specification
3. Accepted ADR
4. Architecture documentation
5. Current feature design
6. Implementation plan
7. Existing implementation

Never silently change product behavior to make implementation easier.

## Product Scope

This project builds the V1 native LangGraph agent platform described in
`docs/product/agent-platform-v1.md`.

Features listed under "Explicitly Not V1" must not be implemented unless the
product specification is explicitly changed first.

Avoid speculative abstractions for post-V1 features.

## Engineering Workflow

For non-trivial work:

1. Understand the requested behavior.
2. Read the relevant product and architecture documentation.
3. Inspect the existing implementation before designing changes.
4. Resolve material ambiguities before implementation.
5. Produce or update a design and implementation plan when appropriate.
6. Implement the smallest complete vertical slice.
7. Follow TDD where practical.
8. Run verification.
9. Review the diff against the specification.
10. Update documentation when architectural behavior changes.

Do not refactor unrelated code.

## Architecture Principles

- Prefer a modular monolith for V1.
- Keep domain modules independently understandable.
- LangGraph is a runtime implementation detail behind the runtime abstraction.
- Route all outbound agent tool execution through the Tool Gateway.
- Keep authentication and connection definitions separate from tool definitions.
- Allow connections to rotate without creating new tool versions.
- Treat published agent and tool versions as immutable.
- Make authorization decisions outside LLM reasoning.

## Security Invariants

Secrets must never enter:

- model prompts
- LangGraph messages
- checkpoints
- logs
- telemetry
- evaluation datasets
- exception messages returned to callers

Resolve and inject all tool credentials in the Tool Gateway.

Never log raw request authorization headers.

Never commit credentials or tokens.

## Durable Execution Invariant

A durable run may depend only on durable or renewable dependencies.

Connection classifications are:

- `NONE`
- `STATIC`
- `RENEWABLE`
- `EPHEMERAL`

`EPHEMERAL` dependencies cannot be used for durable or background execution.

Validate this constraint:

1. When publishing or configuring an agent
2. When starting a durable run

## Testing

Changes should have the appropriate combination of:

- unit tests
- integration tests
- contract tests
- architecture and invariant tests
- end-to-end tests

Tests are evidence of correctness, not the definition of correctness.

Never:

- weaken assertions to make tests pass
- delete failing tests without justification
- hardcode production behavior specifically for tests

## Completion

Before declaring work complete:

- run unit and integration tests relevant to the change
- run the full configured test suite when appropriate
- run the formatter and linter
- run type checking
- inspect the final diff
- verify acceptance criteria
- verify that no secrets were introduced
- report remaining risks or unresolved decisions
