# ADR-0005: Make Published Versions Immutable

## Status

Accepted

## Context

Runs and evaluations must be reproducible and attributable to stable agent and
tool behavior.

## Decision

Published agent and tool versions are immutable. Changes require a new version.

## Consequences

- Runs can retain stable references to the behavior they executed.
- Draft and published lifecycle states must be explicit.
- Mutable credentials remain outside published versions.

## Alternatives

- Allow published definitions to be edited in place.
- Snapshot definitions independently for every run.
