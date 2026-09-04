# ADR-0001: FastAPI Swagger Setup

## Status

Proposed

## Context

We need a backend that supports:

- smooth creation of API endpoints
- well documented swagger docs that get created automatically
- healthcheck endpoint available

## Decision

Use fastapi dependency as external backend for API endpoint creation and automatic Swagger documentation. Use modern fastapi features and setup a health endpoint for monitoring the service status.

## Consequences

### Positive

- Smooth creation of API endpoints
- Automatic Swagger documentation
- Health endpoint for service monitoring
- Leverages modern FastAPI features

### Negative

- Runtime depends on FastAPI
- Some FastAPI concepts may leak into infrastructure code
- Framework upgrades must be managed

## Alternatives Considered

- Django
- Flask

## Status History

- 2026-09-04: Proposed
