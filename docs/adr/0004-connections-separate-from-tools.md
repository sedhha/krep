# ADR-0004: Keep Connections Separate from Tools

## Status

Accepted

## Context

Tool behavior and credential lifecycle change for different reasons. Embedding
credentials in tool versions would couple credential rotation to publication.

## Decision

Store connection definitions separately and reference them from tools.

## Consequences

- Credentials can rotate without creating tool versions.
- The Tool Gateway must resolve connections at execution time.
- Versioned behavior and mutable operational configuration have distinct
  lifecycles.

## Alternatives

- Embed authentication and credentials in each tool definition.
- Bind connections into published agent versions.
