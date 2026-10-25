# T14 — Search API, synonyms, zero-result metric

Spec: 9.1, 9.4, 9.5, 10, 11 (logging). Acceptance: 6, 24, 26.

## Files
- Create: `src/krep/search/synonyms.py`, `src/krep/api/search.py`, `tests/search/test_synonyms.py`, `tests/api/test_search_endpoint.py`
- Modify: `src/krep/api/__init__.py`, `src/krep/api/registry.py` only if route order needs `/registry/search` before `/registry/{id}`

## Consumes
T13 `registry_search`, `expand`; T10 `get_limit`.

## Produces
- `synonyms.py`: `SynonymCache` per tenant (term -> groups index, refresh on write and every 60 s); `async def groups_for(conn, tenant_id) -> list[list[str]]`; CRUD with validation (2-10 terms, <= 3 words each, normalised, lowercase).
- Endpoints: `GET /v1/registry/search` (params and response per 9.1, no total count), `GET/POST /v1/search/synonyms`, `PUT/DELETE /v1/search/synonyms/{id}` (admin).
- Metric: counter `search_zero_results_total{tenant}`; normalised query logged only when `SEARCH_LOG_ZERO_RESULTS=true`.

## Steps
1. Synonym tests (acceptance 24): `reimbursement` finds a resource saying only "refund"; deleting the group removes the effect immediately; 201st group -> `409 synonym_limit_reached`; same term set -> `409 synonym_group_exists`; `A~B` and `B~C` not transitive; errors listed in 9.4.
2. Endpoint tests: param bounds (`limit` max 50, `offset` max 500), response shape, empty page rather than count; non-admin 403 on synonyms.
3. Metric tests (acceptance 26): zero-result search increments for that tenant only; log line absent by default, present and <= 100 chars when enabled; no raw query otherwise.
4. Implement.

## Done when
Acceptance 6, 24, 26 pass.
