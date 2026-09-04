# ADR-0003: Support HTTP Tools Only in V1

## Status

Accepted

## Context

The platform needs a constrained, operable tool model for its first release.
Supporting arbitrary executable tools would expand the runtime and security
surface substantially.

## Decision

HTTP is the only executable V1 tool type. OpenAPI imports selected operations
into HTTP tool definitions.

## Consequences

- All V1 tool execution shares one gateway and security model.
- JSON and SSE response handling can evolve within one tool contract.
- Custom executable tools and MCP remain outside V1.

## Alternatives

- Arbitrary in-process tool code.
- Custom containers.
- Multiple protocol-specific runtimes.
