# T09 — Access policy API

Spec: 8.6, 8.7 (policy part), 10. Acceptance: 11, 12, 13.

## Files
- Create: `src/krep/api/policies.py`, `tests/api/test_policies.py`
- Modify: `src/krep/api/__init__.py` (register router)

## Consumes
T05 `evaluate_leaves`, `warnings_for`, `summarize`; T08 `write_policy`; T07 `require_admin`, `db`.

## Endpoints (admin only)
`POST/GET /v1/access-policies`, `GET/PUT/DELETE /v1/access-policies/{id}`, `GET .../resources`, `GET .../history`, `POST .../restore`, `POST .../test`, `POST /v1/access-policies/preview`.

## Steps
1. Tests: create from `source` and from `ast` return identical `source`/`compiled_path`/`summary`; `422 policy_parse_error` (line, column), `422 policy_too_large`, `409 rev_conflict` with `current_rev`; history keeps only the newest 20 (acceptance 11); restore writes a new revision; `409 policy_in_use` on delete; reserved policies cannot be deleted or renamed (409/422 per spec wording; pick `409 policy_reserved`, note it in progress.md); `max_policies` limit; non-admin gets 403; other tenant's policy 404.
2. `test` endpoint: the 8.6 example response including leaves and warnings, nothing persisted. `preview` returns ast, compiled path, warnings, summary.
3. `usage_count` and `/resources` reflect referencing resources (table exists from T01; resources arrive in T11, so test with rows inserted via the owner connection).
4. Implement.

## Done when
All endpoints behave per 8.6 and acceptance 11-13 pass.
