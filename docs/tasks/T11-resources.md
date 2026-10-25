# T11 — Resources

Spec: 7.1, 7.2, 7.5 (draft cap), 7.7, 8.1, 8.7, 10. Acceptance: 1, 6, 16, 22 (delete side).

## Files
- Create: `src/krep/registry/resources.py`, `src/krep/api/registry.py`, `tests/registry/test_resources.py`, `tests/api/test_registry_endpoints.py`
- Modify: `src/krep/api/__init__.py`

## Consumes
T10 `validate_spec`, `validate_resource_fields`, `get_limit`; T07 `Caller`, `require_write`; T05 `evaluate`.

## Produces (used by T12-T17)
- `resources.py`: `async def create_resource(conn, caller, body) -> dict`; `async def get_visible(conn, caller, resource_id) -> dict | None` (applies the 8.1 predicate to one row, evaluating only that row's policy); `async def can_edit(caller, row) -> bool` (owner or admin); `async def lock_resource(conn, resource_id) -> dict` (`SELECT ... FOR UPDATE`).
- Endpoints: `POST /v1/registry`, `GET /v1/registry` (own; admin all; drafts; `type`, `status` filters), `GET /v1/registry/{id}`, `PATCH /v1/registry/{id}`, `POST .../archive`, `POST .../unarchive`, `DELETE /v1/registry/{id}`.

## Steps
1. Tests: create returns the 7.2 `201` shape and writes registry + version 1 draft + subtype row in one transaction (rolled back on spec failure); `409 slug_taken`; `422 validation_failed` field list; `409 draft_limit_reached` with `{limit, current}` and parallel creates never exceed the cap (acceptance 16, advisory lock); forged `tenant_id` in the body ignored (acceptance 1).
2. Visibility matrix for get-by-id: private/tenant/restricted x creator, other user, policy-matching caller, other tenant -> 200 or 404, never 403 (acceptance 5, 6 for this endpoint).
3. PATCH: restricted requires `policy_id`; switching away keeps `policy_id`; non-owner non-admin gets 403; archived resource hidden from discovery fields but still readable by owner.
4. Delete: succeeds with no inbound links; `409 resource_in_use` with referrers otherwise (acceptance 22, final check in T15 when links exist).
5. Implement.

## Done when
Resource endpoint tests pass.
