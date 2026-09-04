# ADR-0006: Use a Modular Monolith for V1

## Status

Accepted

## Context

Krep contains distinct domains, but V1 does not yet have operational evidence
that justifies distributed deployment and network boundaries.

## Decision

Implement V1 as a modular monolith organized by domain, with integrations kept
behind explicit boundaries.

## Consequences

- The initial system has fewer deployment and consistency concerns.
- Domain ownership remains visible in the source layout.
- Modules can be extracted later if demonstrated scaling or ownership needs
  justify the operational cost.

## Alternatives

- Begin with independently deployed services.
- Organize the monolith by technical layers.
